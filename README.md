# Prospector

**An automated job-prospecting pipeline.** It scans job boards, reverse-engineers startup directories, scores each role against your profile with an LLM, drafts personalized outreach, and delivers everything to Discord for human review — every day, on its own.

It's two things at once: a tool I actually use to run my own job hunt, and a small-scale **GTM-automation** demo — *find targets → LLM-personalized outreach → deliver at scale* — which is the exact shape of problem a lot of automation-and-LLM companies are built around.

---

## The pipeline

```
 CONFIG (profile · filters · webhooks · LLM key)
    │
    ▼
 [1] SOURCES ── APIs, RSS, and a reverse-engineered search backend
    │           RemoteOK · Remotive · We Work Remotely · HN "Who's Hiring" · YC
    ▼
 [2] NORMALIZE ── every source → one Job schema
    │
    ▼
 [3] PREFILTER ── remote? in-lane? fresh? title exclusions?     (cheap, no LLM)
    │
    ▼
 [4] DEDUPE ── source-agnostic hash, Postgres-backed
    │
    ▼
 [5] LLM FIT-SCORE ── {score, tier, reason}, gate on tier       (survivors only)
    │
    ▼
 [6] LLM DRAFT ── personalized email + LinkedIn message
    │
    ▼
 [7] NOTIFY ── Discord embeds (job leads + startup leads, separate channels)
    │
    ▼
 [8] PERSIST ── Supabase (jobs · contacts · outreach)
    │
    ▼
 I review + send · runs daily via cron
```

---

## Design principles

The interesting part isn't the pipeline — it's the judgment behind it.

1. **API where it exists, reverse-engineer where it doesn't.**
   The five sources deliberately span the spectrum: clean JSON APIs (RemoteOK, Remotive), an RSS feed (We Work Remotely), freeform text that needs LLM extraction (HN "Who's Hiring"), and a **JS-app whose data lives behind a client-side search API** (YC). Each source uses the *lightest tool that clears it* — no headless browser where an API call will do.

2. **The LLM is expensive; use it late.**
   Every deterministic filter — remote, salary, lane keywords, freshness, dedupe — runs *before* any LLM call. The model only ever sees pre-qualified survivors. This isn't just cost: deterministic code is faster, testable, and reproducible, so the LLM is confined to the two things code genuinely can't do — **subjective fit-scoring** and **natural-language drafting**.

3. **Human-in-the-loop, always.**
   The tool finds, scores, and drafts. It never sends. A human reviews every message before it goes out — the step that catches an LLM-hallucinated name or a misquoted metric before it reaches a founder's inbox.

4. **Source isolation.**
   Each source is a self-contained module behind a common interface. One source breaking (a 500, a layout change, a rotated key) logs and is skipped — the rest of the run continues.

---

## Sources

| Source | Access method | Notes |
|---|---|---|
| **RemoteOK** | Public JSON API | UA-gated; tags are spammed onto every listing, so matching is title-only |
| **Remotive** | Public JSON API | Continuously updated |
| **We Work Remotely** | RSS (per category) | Escaped-HTML descriptions, `Company: Role` titles |
| **HN "Who's Hiring"** | HN Algolia API | Freeform comment text → the normalizer is really an LLM/regex extraction |
| **YC** | **Reverse-engineered client-side search** | See below |

### The YC source

YC's company directory is a single-page app — the HTML ships no data; it's loaded client-side from a hosted **search backend**. Rather than driving a headless browser to render and scrape the DOM, Prospector recognizes the pattern and goes straight to the source: it extracts the search credentials the page hands the browser at runtime, then **queries the same JSON API the browser uses** — directly, with no browser at all.

Because any client-side search *must* expose its key to the browser to function, that key is always recoverable — and hitting the API directly is faster, cleaner, and far more robust than DOM scraping. The credential is re-extracted on every run, so it survives key rotation. The result: a filtered stream of small, hiring, in-lane startups where the founder is reachable — exactly the cold-outreach sweet spot.

---

## Tech stack

| Component | Choice |
|---|---|
| Language | Python 3.12 |
| HTTP | `httpx` |
| Database | Supabase (Postgres) |
| LLM | OpenAI-compatible API (provider-agnostic) |
| Notifications | Discord webhooks |
| Deployment | VPS + cron |

The profile the LLM scores against is **self-updating**: it merges a static profile file with a distilled summary of the candidate's live public GitHub repos, so new projects flow into the outreach automatically.

---

## Layout

```
main.py            orchestration (source isolation, staged pipeline)
sources/           one module per source, common BaseSource interface
pipeline/          prefilter · deduper · scorer · drafter · profile · llm_util
enrichment/        decision-maker finder (v1.5)
notify/            Discord embed formatting + per-channel routing
db/                Supabase store + schema
models/            Job · FitResult · Prospect
config/            env secrets + profile/filters YAML
```

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env                              # fill in keys
cp config/my_profile.example.yaml config/my_profile.yaml
cp config/filters.example.yaml   config/filters.yaml
# run db/schema.sql in the Supabase SQL editor

python main.py                                    # or wire to cron for daily runs
```

---

## Status

**Working:** 5 sources → filter → dedupe → LLM score → LLM draft → dual-channel Discord → Supabase persistence, plus self-updating GitHub profile enrichment.

**Next:** decision-maker/email finder (domain-anchored + verified), one-click Gmail-compose delivery, VPS/cron deployment.

---

*Built to solve a real problem — and to be the kind of thing worth showing.*
