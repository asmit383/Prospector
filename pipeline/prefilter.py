from datetime import datetime, timezone

import config
from models.job import Job


def _text(job: Job) -> str:
    """Lowercased haystack of the fields we keyword-match against."""
    return f"{job.title} {' '.join(job.tags)}".lower()


def _too_old(job: Job) -> bool:
    """True if the post is older than max_age_days. Unknown date → not old."""
    max_age = config.FILTERS.get("max_age_days")
    if not max_age or job.posted_at is None:
        return False
    age_days = (datetime.now(timezone.utc) - job.posted_at).days
    return age_days > max_age


def passes(job: Job) -> bool:
    """Cheap, no-LLM gate. True if the job is worth an LLM call."""
    f = config.FILTERS
    title = job.title.lower()
    hay = _text(job)

    # 0. Freshness: drop stale posts before anything else.
    if _too_old(job):
        return False

    # 1. Remote check. RemoteOK is all-remote, but other sources aren't —
    #    drop anything that names a non-remote location.
    if f.get("remote_only") and "remote" not in job.location.lower() \
            and job.location.lower() not in ("", "anywhere", "worldwide"):
        # location isn't clearly remote — only keep if the source is remote-only
        if job.source not in ("remoteok",):
            return False

    # 2. Title exclusions (too senior / wrong function).
    if any(bad in title for bad in f.get("exclude_title_keywords", [])):
        return False

    # 3. Salary floor: drop only if a max IS listed and it's below the floor.
    #    Unknown salary (None) is kept — most posts don't list one.
    floor = f.get("min_salary")
    if floor and job.salary_max is not None and job.salary_max < floor:
        return False

    # 4. Must match at least one include keyword in title or tags.
    if not any(kw in hay for kw in f.get("include_keywords", [])):
        return False

    return True


def run(jobs: list[Job]) -> list[Job]:
    return [j for j in jobs if passes(j)]
