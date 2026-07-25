"""Decision-maker finder — for a surviving job, find the founder/CEO/CTO + email.

Robust by construction:
  - domain-anchored: everything verified against the company's real domain
  - grounded: the LLM only reads text we actually fetched, never its own memory
  - graceful: any fetch failure is skipped, we return what we have
  - honest: a guessed email is flagged as such; we never fabricate a contact

This automates the manual research we did by hand for Kog / Cumulus / Syntropic.
"""
import html
import logging
import re
from urllib.parse import urlparse

import httpx

import config
from models.job import Job
from models.contact import DecisionMaker
from pipeline.llm_util import client, extract_json

log = logging.getLogger("prospector.enrich")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}

# Never treat a job-board / ATS host as the company's real domain.
_JOB_BOARDS = {
    "remoteok.com", "remoteok.io", "news.ycombinator.com", "ycombinator.com",
    "weworkremotely.com", "remotive.com", "ashbyhq.com", "greenhouse.io",
    "boards.greenhouse.io", "lever.co", "jobs.lever.co", "workatastartup.com",
    "linkedin.com", "twitter.com", "x.com", "github.com",
}

_PAGES = ["", "about", "team", "about-us", "contact", "careers"]

_SYSTEM = """You find the best person for a job candidate to cold-contact at the \
company at the given domain, using ONLY the provided text (no outside knowledge). \
This is a founder, CEO, CTO, or the hiring contact the text explicitly names or \
tells you to email (e.g. "email me at ..."). Only include someone tied to THIS \
company/domain.

If the text gives a contact email but no full name, derive the name from the email \
(e.g. nicolas.constant@kog.ai → Nicolas Constant).

Respond ONLY with JSON:
{"found": true, "name": "...", "title": "<title, or empty string>", "email": "<email in text, or null>"}
or {"found": false} if no contact person is present in the provided text."""


def find_decision_maker(job: Job) -> DecisionMaker | None:
    domain = _resolve_domain(job)
    if not domain:
        return None  # can't verify → caller falls back to the apply link

    text = _gather_intel(job, domain)
    data = _extract(domain, text)
    if not data or not data.get("found"):
        return None

    name = (data.get("name") or "").strip()
    if not name:
        return None

    email, conf = _resolve_email(name, data.get("email"), domain, text)
    return DecisionMaker(
        name=name,
        title=(data.get("title") or "").strip(),
        email=email,
        email_confidence=conf,
        source=domain,
    )


def run(scored: list[tuple]) -> list[tuple]:
    """scored: list[(Job, FitResult)] → list[(Job, FitResult, DecisionMaker|None)]."""
    out = []
    for job, fit in scored:
        try:
            dm = find_decision_maker(job)
        except Exception:
            log.exception("enrichment failed for %s", job.company)
            dm = None
        out.append((job, fit, dm))
    return out


# ── steps ────────────────────────────────────────────────────────────────

def _resolve_domain(job: Job) -> str | None:
    # 1. company_url, if it's a real company site (not a job board)
    d = _host(job.company_url)
    if d and d not in _JOB_BOARDS:
        return d
    # 2. first real URL in the post text (HN posts link the company). Unescape
    #    first — HN encodes slashes as &#x2F; in the raw comment HTML.
    desc = html.unescape(job.description or "")
    for url in re.findall(r'https?://[^\s<>"\')\]]+', desc):
        d = _host(url)
        if d and d not in _JOB_BOARDS:
            return d
    return None


def _gather_intel(job: Job, domain: str) -> str:
    parts = [job.description or ""]  # the post text (HN contacts live here)
    # The listing page first — YC company pages list the founders even when the
    # startup's own marketing site doesn't — then the company's own site.
    urls = ([job.source_url] if job.source_url else []) + \
           [f"https://{domain}/{p}" for p in _PAGES]
    seen = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            r = httpx.get(url, headers=_HEADERS, timeout=8, follow_redirects=True)
            if r.status_code == 200:
                parts.append(f"[{url}]\n{_strip_html(r.text)[:4000]}")
        except Exception:
            continue
    return "\n\n".join(parts)[:20000]


def _extract(domain: str, text: str) -> dict | None:
    try:
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": f"DOMAIN: {domain}\n\nTEXT:\n{text}"}],
            response_format={"type": "json_object"},
            temperature=0, max_tokens=200,
        )
        return extract_json(resp.choices[0].message.content)
    except Exception:
        log.exception("extraction failed for %s", domain)
        return None


_ROLE_INBOXES = ("founders", "founder", "hello", "team", "contact", "careers", "jobs")


def _resolve_email(name: str, llm_email: str | None, domain: str, text: str):
    # 1. a specific email on this domain, found in the text
    if llm_email and llm_email.lower().strip().endswith("@" + domain):
        return llm_email.lower().strip(), "verified"
    # 2. any email on this domain present in the text — prefer a role inbox
    on_domain = [e.lower() for e in re.findall(r"[A-Za-z0-9._%+-]+@" + re.escape(domain), text)]
    if on_domain:
        roles = [e for e in on_domain if e.split("@")[0] in _ROLE_INBOXES]
        return (roles[0] if roles else on_domain[0]), "generic"
    # 3. no email in the text → offer the likely patterns, all flagged "guessed".
    #    firstname@ is often the real, most-direct address (verify via Gmail's
    #    profile-photo hint); founders@/hello@ are the safe company inboxes.
    #    Never present these as verified — the flag + human review is the guard.
    first = re.sub(r"[^a-z]", "", name.split()[0].lower()) if name.split() else ""
    candidates = ([f"{first}@{domain}"] if first else []) + [f"founders@{domain}", f"hello@{domain}"]
    return " / ".join(candidates), "guessed"


def _host(url: str | None) -> str | None:
    if not url:
        return None
    try:
        netloc = urlparse(url if "://" in url else "https://" + url).netloc.lower()
        host = netloc.split(":")[0]
        return host[4:] if host.startswith("www.") else (host or None)
    except Exception:
        return None


def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s)
    s = re.sub(r"(?i)<\s*br\s*/?>|<\s*/p\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", html.unescape(s)).strip()
