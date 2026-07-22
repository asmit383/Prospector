from db import store
from models.job import Job


def run(jobs: list[Job]) -> list[Job]:
    """Drop jobs already in the DB. In-run dedupe too: two sources can return
    the same job in one run, so track ids we've already accepted this pass."""
    fresh: list[Job] = []
    seen_this_run: set[str] = set()
    for job in jobs:
        jid = store.job_id(job)
        if jid in seen_this_run:
            continue
        if store.already_seen(job):
            continue
        seen_this_run.add(jid)
        fresh.append(job)
    return fresh
