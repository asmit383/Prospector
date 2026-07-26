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

    text, emails = _gather_intel(job, domain)
    data = _extract(domain, text)
    if not data or not data.get("found"):
        return None

    name = (data.get("name") or "").strip()
    if not name:
        return None

    email, conf = _resolve_email(name, data.get("email"), domain, emails)
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


def _gather_intel(job: Job, domain: str) -> tuple[str, set[str]]:
    """Returns (text_for_llm, on_domain_emails).

    The text is stripped + truncated for the LLM. The email set is harvested
    from the FULL raw HTML of every page (before stripping/truncation) — a
    contact address often lives only in a `mailto:` link or a page footer, both
    of which the strip+truncate would otherwise destroy before we look."""
    desc = job.description or ""
    parts = [desc]                       # the post text (HN contacts live here)
    emails = _emails_in(desc, domain)    # …and an "email me at" in the post
    # The listing page first — YC company pages list the founders even when the
    # startup's own marketing site doesn't — then the company's own site.
    # Skip the listing page for HN: its post text is already in the description,
    # and re-fetching HN item pages trips their rate limit (429).
    listing = [job.source_url] if (job.source_url and job.source != "hn") else []
    urls = listing + [f"https://{domain}/{p}" for p in _PAGES]
    seen = set()
    for url in urls:
        if not url or url in seen:
            continue
        seen.add(url)
        try:
            r = httpx.get(url, headers=_HEADERS, timeout=8, follow_redirects=True)
            if r.status_code == 200:
                emails |= _emails_in(r.text, domain)  # harvest from FULL raw html
                parts.append(f"[{url}]\n{_strip_html(r.text)[:4000]}")
        except Exception:
            continue
    return "\n\n".join(parts)[:20000], emails


def _emails_in(raw: str, domain: str) -> set[str]:
    """On-domain emails in raw HTML — catches `mailto:` hrefs and inline text
    alike, because we scan BEFORE stripping tags. Unescape first so entity-
    encoded addresses (e.g. `&#64;` for @) are seen too."""
    s = html.unescape(raw or "")
    hits = re.findall(r"[A-Za-z0-9._%+-]+@" + re.escape(domain), s, re.I)
    return {e.lower() for e in hits}


def _extract(domain: str, text: str) -> dict | None:
    try:
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "system", "content": _SYSTEM},
                      {"role": "user", "content": f"DOMAIN: {domain}\n\nTEXT:\n{text}"}],
            response_format={"type": "json_object"},
            temperature=0, max_tokens=400,
        )
        return extract_json(resp.choices[0].message.content)
    except Exception:
        log.exception("extraction failed for %s", domain)
        return None


_ROLE_INBOXES = ("founders", "founder", "hello", "team", "contact", "careers", "jobs")


def _resolve_email(name: str, llm_email: str | None, domain: str, emails: set[str]):
    found = set(emails)
    llm = (llm_email or "").lower().strip()
    if llm.endswith("@" + domain):
        found.add(llm)

    # 1. a personal address on this domain matching the founder's name — the
    #    most direct, highest-reply-rate cold contact (faiz@ over connect@).
    named = sorted((e for e in found if _name_match(e.split("@")[0], name)), key=len)
    if named:
        return named[0], "verified"
    # 2. the address the post text explicitly pointed to (LLM-extracted).
    if llm.endswith("@" + domain):
        return llm, "verified"
    # 3. a shared role inbox we actually saw on the page.
    roles = [e for e in found if e.split("@")[0] in _ROLE_INBOXES]
    if roles:
        return roles[0], "generic"
    # 4. any other on-domain address we harvested.
    if found:
        return sorted(found, key=len)[0], "generic"
    # 5. nothing found → offer the likely patterns, all flagged "guessed".
    #    firstname@ is often the real, most-direct address (verify via Gmail's
    #    profile-photo hint); founders@/hello@ are the safe company inboxes.
    #    Never present these as verified — the flag + human review is the guard.
    first = re.sub(r"[^a-z]", "", name.split()[0].lower()) if name.split() else ""
    candidates = ([f"{first}@{domain}"] if first else []) + [f"founders@{domain}", f"hello@{domain}"]
    return " / ".join(candidates), "guessed"


def _name_match(local: str, name: str) -> bool:
    """Does an email's local-part belong to this person? Equality against the
    common patterns (first, firstlast, first.last, flast, …) — NOT a substring
    test, so `ana` can't match `manager@`."""
    parts = [re.sub(r"[^a-z]", "", p.lower()) for p in name.split()]
    parts = [p for p in parts if len(p) >= 2]
    if not parts:
        return False
    first, last = parts[0], (parts[-1] if len(parts) > 1 else "")
    stem = re.split(r"[._-]", local.lower().split("+")[0])[0]  # faiz.khan → faiz
    cands = {first}
    if last:
        cands |= {first + last, first[0] + last, first + last[0], last}
    return stem == first or local.lower().split("+")[0] in cands


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
