"""Prospector v1 — API sources → filter → dedupe → score → draft → Discord.

Run daily via cron. Human-in-the-loop: it drafts, you review and send.
"""
import logging

from sources.hn_algolia import HackerNews
from sources.remoteok import RemoteOK
from sources.remotive import Remotive
from sources.wwr import WeWorkRemotely
from sources.yc import YCombinator
from sources.wellfound import Wellfound
from pipeline import prefilter, deduper, scorer, drafter
from enrichment import finder
from notify import discord
from db import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("prospector")

SOURCES = [RemoteOK(), HackerNews(), Remotive(), WeWorkRemotely(), YCombinator(), Wellfound()]


def gather_jobs():
    """Fetch from every source. Source isolation: one failing source logs and
    is skipped, the rest still run."""
    jobs = []
    for src in SOURCES:
        try:
            found = src.fetch()
            log.info("source %s → %d jobs", src.name, len(found))
            jobs.extend(found)
        except Exception:
            log.exception("source %s failed, skipping", src.name)
    return jobs


def main():
    jobs = gather_jobs()
    log.info("gathered %d raw jobs", len(jobs))

    jobs = prefilter.run(jobs)
    log.info("%d after prefilter", len(jobs))

    jobs = deduper.run(jobs)
    log.info("%d after dedupe", len(jobs))

    scored_all = scorer.run(jobs)
    # Record the "no"s NOW so the deduper skips them next run — a reject scores
    # the same tomorrow, so it must never hit the LLM twice. Survivors stay
    # unsaved until they're actually delivered (below), so a crash mid-run
    # re-surfaces a strong lead instead of silently marking it seen and losing it.
    scored = []
    for job, fit in scored_all:
        if fit.tier in ("strong", "maybe"):
            scored.append((job, fit))
        else:
            store.save_job(job, fit.score, fit.tier, fit.reason)
    log.info("%d scored, %d strong/maybe kept", len(scored_all), len(scored))

    enriched = finder.run(scored)
    found = sum(1 for _, _, dm in enriched if dm)
    log.info("%d/%d decision-makers found", found, len(enriched))

    prospects = drafter.run(enriched)
    log.info("%d prospects drafted", len(prospects))

    for p in prospects:
        try:
            discord.send(p)
        except Exception:
            log.exception("failed to notify for %s @ %s", p.job.title, p.job.company)
        # Persist regardless of notify outcome so we don't re-surface it tomorrow.
        store.save_job(p.job, p.fit.score, p.fit.tier, p.fit.reason)

    log.info("done")


if __name__ == "__main__":
    main()
