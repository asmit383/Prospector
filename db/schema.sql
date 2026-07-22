-- Run this once in the Supabase SQL editor to create the tables.

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,          -- hash(company + normalized_title), source-agnostic
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    company_url TEXT,
    description TEXT,
    salary_min INT,
    salary_max INT,
    location TEXT,
    tags JSONB DEFAULT '[]',
    source TEXT NOT NULL,
    source_url TEXT,
    posted_at TIMESTAMPTZ,
    discovered_at TIMESTAMPTZ DEFAULT NOW(),
    fit_score INT,
    fit_tier TEXT,               -- 'strong' | 'maybe' | 'no'
    fit_reason TEXT
);

CREATE TABLE IF NOT EXISTS contacts (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    title TEXT,
    email TEXT,
    email_verified BOOLEAN DEFAULT FALSE,
    linkedin_url TEXT,
    company TEXT NOT NULL,
    company_url TEXT,
    discovered_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS outreach (
    id SERIAL PRIMARY KEY,
    job_id TEXT REFERENCES jobs(id),
    contact_id INT REFERENCES contacts(id),
    channel TEXT NOT NULL,       -- 'email' | 'linkedin'
    draft TEXT,
    status TEXT DEFAULT 'drafted',  -- drafted | sent | replied | ignored
    created_at TIMESTAMPTZ DEFAULT NOW(),
    sent_at TIMESTAMPTZ
);
