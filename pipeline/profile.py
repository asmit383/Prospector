"""Builds the candidate profile the LLM sees: static YAML (intent, private work,
voice) + a distilled summary of the user's live public GitHub repos (evidence).

Hybrid on purpose: GitHub knows your public projects but NOT your target roles,
goal, consulting work, or tone — those stay in my_profile.yaml. Falls back to
static-only if GitHub is unreachable (source isolation)."""
import base64
import functools
import logging
import re

import httpx
import yaml

import config
from pipeline.llm_util import client

log = logging.getLogger("prospector.profile")

_API = "https://api.github.com"
_THINK = re.compile(r"<think>.*?</think>", re.DOTALL)

_DISTILL_SYSTEM = (
    "You are given a candidate's public GitHub repositories (name, language, "
    "description, README excerpt). Distill their strongest, most relevant "
    "projects into a compact list for a job-outreach tool. One bullet per notable "
    "project: what it is and what skill/domain it demonstrates (ML systems, LLM "
    "inference, automation, backend, etc.). Skip trivial or empty repos. Max 8 "
    "bullets. Plain text, no preamble."
)


def _headers() -> dict:
    h = {"User-Agent": "Prospector", "Accept": "application/vnd.github+json"}
    if config.GITHUB_TOKEN:
        h["Authorization"] = f"Bearer {config.GITHUB_TOKEN}"
    return h


def _username() -> str:
    if config.GITHUB_USERNAME:
        return config.GITHUB_USERNAME
    url = config.PROFILE.get("github", "")
    return url.rstrip("/").split("/")[-1] if url else ""


def _readme(user: str, repo: str) -> str:
    try:
        r = httpx.get(f"{_API}/repos/{user}/{repo}/readme", headers=_headers(), timeout=15)
        if r.status_code != 200:
            return ""
        return base64.b64decode(r.json().get("content", "")).decode("utf-8", "ignore")
    except Exception:
        return ""


def _github_projects_summary() -> str:
    user = _username()
    if not user:
        return ""
    try:
        r = httpx.get(f"{_API}/users/{user}/repos",
                      params={"sort": "pushed", "per_page": 100},
                      headers=_headers(), timeout=20)
        r.raise_for_status()
        repos = [x for x in r.json() if not x.get("fork")]
    except Exception:
        log.exception("github repo fetch failed; using static profile only")
        return ""

    # Strongest first (stars), take the top handful for README fetch.
    repos.sort(key=lambda x: x.get("stargazers_count", 0), reverse=True)
    chunks = []
    for repo in repos[:8]:
        readme = _readme(user, repo["name"])[:1500]
        chunks.append(
            f"### {repo['name']} ({repo.get('language') or '-'})\n"
            f"{repo.get('description') or ''}\n{readme}"
        )

    # Exact repo links (name → URL), so drafts can cite the specific repo.
    links = "\n".join(f"- {r['name']}: {r['html_url']}" for r in repos[:8] if r.get("html_url"))

    try:
        resp = client.chat.completions.create(
            model=config.LLM_MODEL,
            messages=[{"role": "system", "content": _DISTILL_SYSTEM},
                      {"role": "user", "content": "\n\n".join(chunks)[:12000]}],
            temperature=0, max_tokens=500,
        )
        summary = _THINK.sub("", resp.choices[0].message.content or "").strip()
        return f"{summary}\n\nREPO LINKS (cite the specific one when naming a project):\n{links}"
    except Exception:
        log.exception("github distill failed; using static profile only")
        return f"REPO LINKS:\n{links}" if links else ""


@functools.lru_cache(maxsize=1)
def get_profile_text() -> str:
    """Merged profile string, built once per process."""
    static = yaml.safe_dump(config.PROFILE, sort_keys=False)
    gh = _github_projects_summary()
    if gh:
        log.info("profile enriched with live GitHub projects")
        return f"{static}\n\nPUBLIC GITHUB PROJECTS (live):\n{gh}"
    return static
