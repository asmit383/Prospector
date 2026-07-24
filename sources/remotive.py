from datetime import datetime, timezone

import httpx

from models.job import Job
from sources.base import BaseSource

# Remotive JSON API — continuously updated remote-job board.
# Response: {"job-count": N, "jobs": [ {...}, ... ]}
# Job fields: title, company_name, description, tags, job_type,
#   publication_date, candidate_required_location, salary, url
API_URL = "https://remotive.com/api/remote-jobs"
_HEADERS = {"User-Agent": "Mozilla/5.0"}


class Remotive(BaseSource):
    name = "remotive"

    def fetch(self) -> list[Job]:
        resp = httpx.get(API_URL, headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        raw = resp.json().get("jobs") or []

        jobs: list[Job] = []
        for r in raw:
            if not r.get("title") or not r.get("company_name"):
                continue
            jobs.append(Job(
                title=r["title"],
                company=r["company_name"],
                company_url="",  # Remotive gives no company domain
                description=r.get("description", ""),
                # salary is a free-form string ("" / "$50k-$70k") — don't half-parse
                # it; the LLM reads salary from the description if present.
                salary_min=None,
                salary_max=None,
                location=r.get("candidate_required_location") or "remote",
                tags=r.get("tags") or [],
                source=self.name,
                source_url=r.get("url", ""),
                posted_at=_parse_date(r.get("publication_date")),
            ))
        return jobs


def _parse_date(value: str | None) -> datetime | None:
    """Remotive dates look like '2026-07-22T06:22:11' (naive) — assume UTC."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
