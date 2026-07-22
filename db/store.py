import hashlib
import re

from supabase import create_client, Client

import config
from models.job import Job

_client: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)


def normalize_title(title: str) -> str:
    """Lowercase, strip seniority noise and punctuation so the same role from
    two sources collapses to one dedupe key."""
    t = title.lower()
    for noise in ("senior", "sr.", "sr", "junior", "jr.", "jr", "staff",
                  "lead", "principal", "i", "ii", "iii"):
        t = re.sub(rf"\b{re.escape(noise)}\b", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    return t


def job_id(job: Job) -> str:
    key = f"{job.company.lower().strip()}|{normalize_title(job.title)}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def already_seen(job: Job) -> bool:
    """True if this job id already exists in the jobs table."""
    resp = _client.table("jobs").select("id").eq("id", job_id(job)).execute()
    return len(resp.data) > 0


def save_job(job: Job, fit_score: int, fit_tier: str, fit_reason: str) -> None:
    _client.table("jobs").upsert({
        "id": job_id(job),
        "title": job.title,
        "company": job.company,
        "company_url": job.company_url,
        "description": job.description,
        "salary_min": job.salary_min,
        "salary_max": job.salary_max,
        "location": job.location,
        "tags": job.tags,
        "source": job.source,
        "source_url": job.source_url,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "fit_score": fit_score,
        "fit_tier": fit_tier,
        "fit_reason": fit_reason,
    }).execute()
