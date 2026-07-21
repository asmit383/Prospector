# Prospector — Architecture

## What It Does
Scans job boards and company sites for remote ML/automation roles, finds the decision-maker (CTO/CEO), drafts personalized cold outreach, and delivers everything to Discord for human review. Runs daily on a VPS via cron.

## System Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                          CONFIG                                 │
│  my_profile.yaml · filters.yaml · targets.yaml · .env          │
└──────────────────────────┬──────────────────────────────────────┘
                           │
          ┌────────────────┴────────────────┐
          │           [1] SOURCES            │
          │                                 │
          │   API track (httpx)             │   Stealth track (Playwright)
          │   ├── HN Algolia                │   ├── Wellfound
          │   ├── RemoteOK                  │   ├── YC Work at a Startup
          │   ├── Remotive                  │   ├── Target company careers
          │   └── We Work Remotely          │   └── Greenhouse/Lever boards
          └────────────────┬────────────────┘
                           │
                    list[RawJob] (per source)
                           │
                ┌──────────▼──────────┐
                │   [2] NORMALIZE      │
                │   → list[Job]        │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │   [3] PREFILTER      │   no LLM, no cost
                │   remote? salary?    │
                │   keywords? titles?  │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │   [4] DEDUPE         │   SQLite seen_jobs
                │   skip if seen       │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │   [5] LLM FIT-SCORE  │   survivors only
                │   score 1-10         │   drop < 6
                │   + reasoning        │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────────────────────────────┐
                │   [6] FIND DECISION-MAKER                    │
                │                                              │
                │   A. Scrape /team, /about (Playwright)       │
                │      → LLM extract {name, title}             │
                │                                              │
                │   B. Email discovery (automation)             │
                │      → scrape domain for exposed emails      │
                │      → infer pattern (first@, first.last@)   │
                │      → SMTP verify                           │
                │                                              │
                │   C. LinkedIn resolution                     │
                │      → search: "name company site:li/in"     │
                │      → extract profile URL                   │
                └──────────┬──────────────────────────────────┘
                           │
                ┌──────────▼──────────┐
                │   [7] LLM DRAFT      │
                │   email version      │
                │   LinkedIn version   │
                │   personalized to    │
                │   company + role     │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │   [8] DISCORD NOTIFY │   webhook embed
                │   job + score +      │
                │   contact + drafts   │
                └──────────┬──────────┘
                           │
                ┌──────────▼──────────┐
                │   [9] PERSIST        │   SQLite
                │   jobs · contacts    │
                │   outreach_log       │
                └─────────────────────┘

                      ▼
              I review + send
```

## Directory Structure

```
prospector/
├── main.py                  # entry point — orchestrates the pipeline
├── config/
│   ├── __init__.py          # load + validate config
│   ├── my_profile.yaml      # skills, experience, what I'm looking for
│   ├── filters.yaml         # remote, salary, keywords, exclusions
│   └── targets.yaml         # specific companies to watch
│
├── sources/                 # one module per source, all return list[Job]
│   ├── __init__.py          # source registry
│   ├── base.py              # BaseSource interface
│   ├── hn_algolia.py        # HN "Who is Hiring" via Algolia API
│   ├── remoteok.py          # RemoteOK JSON API
│   ├── remotive.py          # Remotive REST API
│   ├── wwr.py               # We Work Remotely RSS
│   ├── wellfound.py         # Wellfound stealth scrape
│   ├── yc_startup.py        # YC "Work at a Startup" stealth scrape
│   └── company_careers.py   # scrape career pages from targets.yaml
│
├── scraper/                 # stealth automation core
│   ├── __init__.py
│   ├── browser.py           # Playwright setup, anti-detection, fingerprints
│   ├── proxy.py             # proxy rotation
│   └── stealth.py           # evasion techniques, TLS fingerprint config
│
├── pipeline/                # processing stages
│   ├── __init__.py
│   ├── normalizer.py        # raw source data → Job schema
│   ├── prefilter.py         # fast keyword/salary/remote filtering
│   ├── deduper.py           # SQLite-backed seen-job check
│   ├── scorer.py            # LLM fit-scoring
│   └── drafter.py           # LLM outreach drafting
│
├── enrichment/              # decision-maker finder
│   ├── __init__.py
│   ├── team_scraper.py      # scrape company /team, /about pages
│   ├── email_finder.py      # pattern discovery + SMTP verify
│   └── linkedin_finder.py   # programmatic LinkedIn URL resolution
│
├── notify/
│   ├── __init__.py
│   └── discord.py           # webhook embed formatting + POST
│
├── db/
│   ├── __init__.py
│   └── store.py             # SQLite schema + queries (jobs, contacts, outreach)
│
├── models/                  # data schemas
│   ├── __init__.py
│   ├── job.py               # Job dataclass
│   └── contact.py           # DecisionMaker dataclass
│
├── .env.example             # template for secrets
├── requirements.txt
└── README.md
```

## Tech Stack

| Component          | Tech                              | Why                                      |
|--------------------|-----------------------------------|------------------------------------------|
| HTTP client        | httpx                             | async, modern, good for APIs             |
| Stealth browser    | Playwright + stealth patches      | core skill demo, handles JS-heavy sites  |
| Anti-detection     | custom fingerprinting, TLS config | portfolio flex — shows depth             |
| Database           | SQLite                            | zero-infra, portable, enough for v1-v2   |
| LLM                | OpenAI-compatible API             | fit-scoring + drafting, provider-agnostic |
| Notifications      | Discord webhook                   | free, instant, rich embeds               |
| Deployment         | VPS + cron                        | simple, reliable daily runs              |
| Language           | Python 3.11+                      | best ecosystem for scraping + ML         |

## Design Principles

1. **Source isolation** — each source is its own module with a common interface. If one breaks, the rest keep running.
2. **LLM is expensive, use it late** — prefilter and dedupe happen before any LLM call. Only survivors get scored and drafted.
3. **API where it exists, scrape where it doesn't** — shows engineering judgment, not just one trick.
4. **Human-in-the-loop** — the tool finds, scores, drafts. I review and send. No auto-sending.
5. **Stealth as a first-class concern** — the scraper isn't an afterthought. Fingerprint rotation, proxy support, anti-detection are built into the core.

## Data Schemas

```python
@dataclass
class Job:
    title: str
    company: str
    company_url: str
    description: str
    salary_min: int | None
    salary_max: int | None
    location: str            # "remote" or specific
    tags: list[str]
    source: str              # "hn", "remoteok", "wellfound", etc.
    source_url: str
    posted_at: datetime | None

@dataclass
class DecisionMaker:
    name: str
    title: str               # "CTO", "CEO", "Founder"
    email: str | None
    email_verified: bool
    linkedin_url: str | None
    company: str
    company_url: str

@dataclass
class Prospect:              # a Job + its DecisionMaker + drafts
    job: Job
    fit_score: int
    fit_reason: str
    contact: DecisionMaker | None
    email_draft: str
    linkedin_draft: str
```

## SQLite Schema (core tables)

```sql
CREATE TABLE jobs (
    id TEXT PRIMARY KEY,     -- hash(company + title + source)
    title TEXT,
    company TEXT,
    company_url TEXT,
    description TEXT,
    salary_min INTEGER,
    salary_max INTEGER,
    location TEXT,
    tags TEXT,                -- JSON array
    source TEXT,
    source_url TEXT,
    posted_at TEXT,
    discovered_at TEXT,
    fit_score INTEGER,
    fit_reason TEXT
);

CREATE TABLE contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    title TEXT,
    email TEXT,
    email_verified INTEGER DEFAULT 0,
    linkedin_url TEXT,
    company TEXT,
    company_url TEXT,
    discovered_at TEXT
);

CREATE TABLE outreach (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT REFERENCES jobs(id),
    contact_id INTEGER REFERENCES contacts(id),
    channel TEXT,            -- "email" or "linkedin"
    draft TEXT,
    status TEXT DEFAULT 'drafted',  -- drafted / sent / replied / ignored
    created_at TEXT,
    sent_at TEXT
);
```
