import json
import re

import httpx

from models.job import Job
from sources.base import BaseSource

# YC's company directory is Algolia-backed. The search key isn't in the JS
# bundle — it's injected into the companies page as `window.AlgoliaOpts`. We
# extract it fresh each run (survives YC rotating the key) and replay the API
# directly, no browser. Returns companies, not job posts — which suits the
# strategy: small YC startups are exactly the founder-reachable cold targets.
COMPANIES_PAGE = "https://www.ycombinator.com/companies"
INDEX = "YCCompany_production"
DEFAULT_APP = "45BWZJ1SGC"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}
_OPTS_RE = re.compile(r"window\.AlgoliaOpts\s*=\s*(\{.*?\})\s*;", re.DOTALL)

# Founder-reachable startups only — small teams (your cold-outreach sweet spot).
MAX_TEAM = 50
MAX_PAGES = 6  # 100/page → up to 600 hiring startups

# Keep only companies YC categorizes into the candidate's lanes. YC's own
# taxonomy is far more reliable than keyword-matching a terse one-liner.
RELEVANT_TAGS = {
    "AI", "Artificial Intelligence", "Machine Learning", "Generative AI",
    "AI Assistant", "Conversational AI", "Infrastructure", "Developer Tools",
    "Automation", "Workflow Automation", "Engineering, Product and Design",
}


class YCombinator(BaseSource):
    name = "yc"

    def fetch(self) -> list[Job]:
        app, key = self._creds()
        if not key:
            return []  # extraction failed — source isolation, skip cleanly

        jobs: list[Job] = []
        for c in self._query(app, key):
            name = c.get("name")
            if not name:
                continue
            cats = set((c.get("industries") or []) + (c.get("tags") or []))
            if not (RELEVANT_TAGS & cats):
                continue  # not in the candidate's lanes by YC's own taxonomy
            one = c.get("one_liner") or ""
            slug = c.get("slug", "")
            # regions carry the remote signal ("Remote"/"Fully Remote"/"Partly
            # Remote") — use it for location so the remote filter works. The
            # all_locations field is just the HQ city.
            regions = c.get("regions") or []
            remote = any("remote" in r.lower() for r in regions)
            jobs.append(Job(
                # keyword-rich title so the title-only prefilter matches the
                # company's actual domain (e.g. "Kagi — LLM search engine").
                title=f"{name} — {one}"[:200],
                company=name,
                company_url=c.get("website") or f"https://www.ycombinator.com/companies/{slug}",
                description=c.get("long_description") or one,
                location="remote" if remote else (c.get("all_locations") or ""),
                tags=(c.get("industries") or []) + (c.get("tags") or []),
                source=self.name,
                source_url=f"https://www.ycombinator.com/companies/{slug}",
                posted_at=None,  # companies have no post date; dedupe handles repeats
            ))
        return jobs

    def _creds(self) -> tuple[str, str]:
        try:
            html = httpx.get(COMPANIES_PAGE, headers=_HEADERS, timeout=20,
                             follow_redirects=True).text
            m = _OPTS_RE.search(html)
            if not m:
                return DEFAULT_APP, ""
            opts = json.loads(m.group(1))
            return opts.get("app", DEFAULT_APP), opts.get("key", "")
        except Exception:
            return DEFAULT_APP, ""

    def _query(self, app: str, key: str) -> list[dict]:
        out: list[dict] = []
        for page in range(MAX_PAGES):
            try:
                r = httpx.post(
                    f"https://{app.lower()}-dsn.algolia.net/1/indexes/{INDEX}/query",
                    headers={"X-Algolia-Application-Id": app,
                             "X-Algolia-API-Key": key,
                             "User-Agent": _HEADERS["User-Agent"]},
                    json={"query": "", "hitsPerPage": 100, "page": page,
                          "filters": f"isHiring:true AND team_size < {MAX_TEAM}"},
                    timeout=20,
                )
                r.raise_for_status()
                data = r.json()
            except Exception:
                break
            out.extend(data.get("hits", []))
            if page >= data.get("nbPages", 1) - 1:
                break
        return out
