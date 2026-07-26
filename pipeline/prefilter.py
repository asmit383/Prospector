from datetime import datetime, timezone

import config
from models.job import Job

# Boards that only list remote jobs — their location fields are often junk
# ("Jobs Cabin", "Anywhere in the World"), so skip the remote check for them.
_REMOTE_SOURCES = {"remoteok", "remotive", "wwr", "wellfound"}
_REMOTE_HINTS = ("remote", "anywhere", "worldwide", "global", "distributed")

# Sources already filtered to the candidate's lanes by their own taxonomy
# (YC categorizes companies) — skip the include-keyword gate for them.
_CATEGORY_FILTERED = {"yc"}


def _text(job: Job) -> str:
    """Keyword-match against the title only. Tags are unreliable — RemoteOK spams
    tech tags onto non-tech listings, Remotive adds off-target ones — while the
    role title is the honest signal (real tech jobs put the stack in the title).
    (HN titles are the full 'Company | Role | stack' header, so they're rich.)"""
    return job.title.lower()


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

    # 1. Remote check. Boards that are remote-only by definition always pass;
    #    other sources (HN, scraped) must name a remote-ish location.
    if f.get("remote_only") and job.source not in _REMOTE_SOURCES:
        loc = job.location.lower()
        if loc and not any(k in loc for k in _REMOTE_HINTS):
            return False

    # 2. Title exclusions (too senior / wrong function).
    if any(bad in title for bad in f.get("exclude_title_keywords", [])):
        return False

    # 3. Salary floor: drop only if a max IS listed and it's below the floor.
    #    Unknown salary (None) is kept — most posts don't list one.
    floor = f.get("min_salary")
    if floor and job.salary_max is not None and job.salary_max < floor:
        return False

    # 4. Must match at least one include keyword — unless the source already
    #    filtered to the candidate's lanes by its own taxonomy (e.g. YC).
    if job.source not in _CATEGORY_FILTERED:
        if not any(kw in hay for kw in f.get("include_keywords", [])):
            return False

    return True


def run(jobs: list[Job]) -> list[Job]:
    return [j for j in jobs if passes(j)]
