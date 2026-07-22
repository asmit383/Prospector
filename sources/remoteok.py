from datetime import datetime

import httpx

from models.job import Job
from sources.base import BaseSource

# RemoteOK exposes a public JSON API. The first element of the array is a
# legal/metadata blob — skip it. Each job dict has fields like:
#   position, company, description, tags, location, salary_min, salary_max,
#   date, id, url, apply_url
# Feed: https://remoteok.com/api
API_URL = "https://remoteok.com/api"

# RemoteOK 403s the default httpx User-Agent — send a browser-like one.
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    )
}


class RemoteOK(BaseSource):
    name = "remoteok"

    def fetch(self) -> list[Job]:
        resp = httpx.get(API_URL, headers=_HEADERS, timeout=30)
        resp.raise_for_status()

        # First element is the legal/metadata blob — drop it.
        raw_jobs = resp.json()[1:]

        jobs: list[Job] = []
        for r in raw_jobs:
            # Skip malformed entries (RemoteOK occasionally has junk rows).
            if not r.get("position") or not r.get("company"):
                continue

            jobs.append(Job(
                title=r["position"],
                company=r["company"],
                # RemoteOK gives no company domain — use the listing URL for now.
                # v1.5 enrichment resolves the real domain.
                company_url=r.get("url", ""),
                description=r.get("description", ""),
                # salary_min/max are 0 when unlisted → treat 0 as None.
                salary_min=r.get("salary_min") or None,
                salary_max=r.get("salary_max") or None,
                location=r.get("location") or "remote",
                tags=r.get("tags") or [],
                source=self.name,
                source_url=r.get("url") or r.get("apply_url", ""),
                posted_at=_parse_date(r.get("date")),
            ))
        return jobs


def _parse_date(value: str | None) -> datetime | None:
    """RemoteOK dates are ISO 8601 strings like '2026-07-21T13:20:49+00:00'."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
