import json
import re
from datetime import datetime, timezone

from camoufox.sync_api import Camoufox

from models.job import Job
from sources.base import BaseSource

# Wellfound (AngelList Talent) is behind DataDome + Cloudflare. Plain httpx — and
# even TLS impersonation (curl_cffi, chrome120) — gets 403: DataDome requires
# solving its JS device-fingerprint challenge to mint a `datadome` cookie.
# Camoufox (Firefox with C++-level fingerprint spoofing, invisible to DataDome's
# JS inspection) solves the challenge and loads the page. Job data is server-
# rendered into __NEXT_DATA__, under each StartupResult.highlightedJobListings.
SEARCH_URLS = [
    "https://wellfound.com/role/l/machine-learning-engineer/remote",
    "https://wellfound.com/role/l/backend-engineer/remote",
    "https://wellfound.com/role/l/full-stack-engineer/remote",
]
_NEXT_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)


class Wellfound(BaseSource):
    name = "wellfound"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        try:
            with Camoufox(headless=True, humanize=True) as browser:
                page = browser.new_page()
                for url in SEARCH_URLS:
                    try:
                        page.goto(url, wait_until="networkidle", timeout=45000)
                        page.wait_for_timeout(4000)  # let DataDome settle + render
                        jobs.extend(self._parse(page.content()))
                    except Exception:
                        continue  # per-search isolation
        except Exception:
            return []  # browser/DataDome failure → source isolation, skip cleanly

        # de-dupe within the run (searches overlap)
        seen, out = set(), []
        for j in jobs:
            if j.source_url in seen:
                continue
            seen.add(j.source_url)
            out.append(j)
        return out

    def _parse(self, html: str) -> list[Job]:
        m = _NEXT_RE.search(html)
        if not m:
            return []
        data = json.loads(m.group(1))
        # Normalized Apollo cache: keys like "JobListingSearchResult:123".
        # A startup's highlightedJobListings holds {"__ref": "..."} pointers.
        cache = (data.get("props", {}).get("pageProps", {})
                 .get("apolloState", {}).get("data")) or {}

        out: list[Job] = []
        for val in cache.values():
            if not isinstance(val, dict) or val.get("__typename") != "StartupResult":
                continue
            name = val.get("name")
            if not name:
                continue
            slug = val.get("slug", "")
            concept = val.get("highConcept") or ""
            for ref in val.get("highlightedJobListings") or []:
                jl = cache.get(ref.get("__ref")) if isinstance(ref, dict) else None
                if not jl:
                    continue
                title = jl.get("title") or jl.get("primaryRoleTitle")
                if not title:
                    continue
                comp = jl.get("compensation") or ""
                out.append(Job(
                    title=title,
                    company=name,
                    company_url=f"https://wellfound.com/company/{slug}",
                    description=f"{concept}\n\n{jl.get('description') or ''}\n\ncompensation: {comp}",
                    location="remote" if jl.get("remote") else ", ".join(jl.get("locationNames") or []) or "remote",
                    tags=[],
                    source=self.name,
                    source_url=f"https://wellfound.com/jobs/{jl.get('id')}-{jl.get('slug', '')}",
                    posted_at=_epoch(jl.get("liveStartAt")),
                ))
        return out


def _epoch(ts) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError):
        return None
