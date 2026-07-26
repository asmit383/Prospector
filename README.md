# Prospector

**An automated job-prospecting pipeline.** It scans job boards, reverse-engineers startup directories, scores each role against your profile with an LLM, drafts personalized outreach, and delivers everything to Discord for human review — every day, on its own.

It's two things at once: a tool I actually use to run my own job hunt, and a small-scale **GTM-automation** demo — *find targets → LLM-personalized outreach → deliver at scale* — which is the exact shape of problem a lot of automation-and-LLM companies are built around.

---

## The pipeline

```
 CONFIG (profile · filters · webhooks · LLM key)
    │
    ▼
 [1] SOURCES ── APIs, RSS, a reverse-engineered search backend, a stealth browser
    │           RemoteOK · Remotive · We Work Remotely · HN "Who's Hiring" · YC · Wellfound
    ▼
 [2] NORMALIZE ── every source → one Job schema
    │
    ▼
 [3] PREFILTER ── remote? region-eligible? in-lane? fresh?      (cheap, no LLM)
    │
    ▼
 [4] DEDUPE ── source-agnostic hash, Postgres-backed
    │
    ▼
 [5] LLM FIT-SCORE ── {score, tier, reason}, gate on tier       (survivors only)
    │
    ▼
 [6] FIND DECISION-MAKER ── founder/CTO + email, grounded + confidence-flagged
    │
    ▼
 [7] LLM DRAFT ── personalized email + LinkedIn, addressed to the contact
    │
    ▼
 [8] NOTIFY ── Discord embeds + one-click Gmail-compose (separate channels)
    │
    ▼
 [9] PERSIST ── Supabase (jobs · contacts · outreach)
    │
    ▼
 I review + send · runs daily via cron
```

---

## Design principles

The interesting part isn't the pipeline — it's the judgment behind it.

1. **API where it exists, reverse-engineer where it doesn't, stealth where it fights back.**
   The six sources deliberately span the spectrum: clean JSON APIs (RemoteOK, Remotive), an RSS feed (We Work Remotely), freeform text that needs LLM extraction (HN "Who's Hiring"), a **JS-app whose data lives behind a client-side search API** (YC), and — where a site actively blocks automated access (Wellfound, behind DataDome) — a **fingerprint-spoofing stealth browser**. Each source uses the *lightest tool that clears it*: an API call where one exists, a browser only where the site leaves no other way in.

2. **The LLM is expensive; use it late — and only once.**
   Every deterministic filter — remote, region, salary, lane keywords, freshness, dedupe — runs *before* any LLM call. The model only ever sees pre-qualified survivors. And **every fit-score verdict is persisted (including the rejects)**, so the deduper skips a job on later runs and the LLM scores it *exactly once, ever* — a job that scored "no" today isn't re-scored tomorrow. This isn't just cost: deterministic code is faster, testable, and reproducible, so the LLM is confined to the two things code genuinely can't do — **subjective fit-scoring** and **natural-language drafting**.

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
| **Wellfound** | **Stealth browser** (Camoufox) | Behind DataDome + Cloudflare; TLS impersonation alone gets `403` — see below |

### The YC source

YC's company directory is a single-page app — the HTML ships no data; it's loaded client-side from a hosted **search backend**. Rather than driving a headless browser to render and scrape the DOM, Prospector recognizes the pattern and goes straight to the source: it extracts the search credentials the page hands the browser at runtime, then **queries the same JSON API the browser uses** — directly, with no browser at all.

Because any client-side search *must* expose its key to the browser to function, that key is always recoverable — and hitting the API directly is faster, cleaner, and far more robust than DOM scraping. The credential is re-extracted on every run, so it survives key rotation. The result: a filtered stream of small, hiring, in-lane startups where the founder is reachable — exactly the cold-outreach sweet spot.

### The Wellfound source

Wellfound sits behind **DataDome + Cloudflare** bot protection. Plain HTTP — and even `curl_cffi` TLS/JA3 impersonation of a real Chrome — gets a `403`: DataDome requires its in-browser JavaScript **fingerprint challenge** to be solved before it will issue a session cookie. This is the one source where no API call, at any TLS layer, gets you in.

So it uses **Camoufox**, a Firefox build that spoofs the browser fingerprint at the **C++ engine level** — the browser reports a consistent, human-looking fingerprint that DataDome's JS inspection can't distinguish from a real one, so the challenge passes and the page loads. Job data is then read from the page's embedded `__NEXT_DATA__` (a normalized Apollo cache, resolved through its `__ref` pointers) — not by scraping the rendered DOM.

It's the deliberate far end of principle #1: an API call clears most sources, but where a site genuinely fights back, the tool escalates to match. And it stays **source-isolated** — if DataDome ever flags a run, that source just skips and the other five continue.

---

## Finding the decision-maker

For every strong-fit survivor, Prospector finds *who to email* — the founder/CTO — so the outreach lands in a person's inbox, not an ATS queue. It's built to be **robust before comprehensive**, because a confidently-wrong contact is worse than none:

- **Domain-anchored** — resolves the company's real domain first; every candidate is verified against it (so a same-named company can't leak in).
- **Grounded** — the LLM extracts a name/title/email *only from text actually fetched* (the job post, the YC page, the company's `/about` · `/team` · `/contact`). It cannot invent a name that isn't in the source.
- **Thorough on the email** — on-domain addresses are harvested from the *full raw HTML* of each page, including `mailto:` links a text-scrape would miss; when the founder's name is known it prefers their **personal address** (`faiz@`) over a shared inbox (`connect@`).
- **Confidence-flagged** — a real email found in the text is `verified`; a company role-inbox is `generic`; a pattern guess is `guessed`. It **never presents a guess as fact**, and never fabricates a specific person's email as if it were known.
- **Graceful** — any blocked or missing page is skipped; it returns what it has, or falls back to the apply link.

The result in the Discord card: the contact's name and title, a usable email (labeled by confidence), and the source it came from — so a human reviews and sends with the right level of trust.

---

## Tech stack

| Component | Choice |
|---|---|
| Language | Python 3.12 |
| HTTP | `httpx` |
| Stealth browser | Camoufox (Firefox, engine-level fingerprint spoofing) |
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
enrichment/        decision-maker finder (domain-anchored, grounded)
notify/            Discord embed formatting + per-channel routing
db/                Supabase store + schema
models/            Job · FitResult · DecisionMaker · Prospect
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

**Working:** 6 sources (incl. Wellfound, past DataDome via a stealth browser) → filter (lane · freshness · salary · **region-eligibility**) → dedupe → LLM score → **decision-maker finder** → LLM draft → dual-channel Discord with **one-click Gmail-compose** → Supabase persistence, plus self-updating GitHub profile enrichment.

**Next:** MX/SMTP contact verification (turn `guessed` → `verified`), an outreach tracker (sent · replied · ignored), and VPS/cron deployment.

---

*Built to solve a real problem — and to be the kind of thing worth showing.*
