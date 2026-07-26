from dataclasses import dataclass, field
from datetime import datetime

from models.contact import DecisionMaker


@dataclass
class Job:
    title: str
    company: str
    company_url: str
    description: str
    source: str
    source_url: str
    salary_min: int | None = None
    salary_max: int | None = None
    location: str = "remote"
    tags: list[str] = field(default_factory=list)
    posted_at: datetime | None = None


@dataclass
class FitResult:
    score: int
    tier: str  # "strong" | "maybe" | "no"
    reason: str


@dataclass
class Prospect:
    job: Job
    fit: FitResult
    email_draft: str
    linkedin_draft: str
    email_subject: str = ""
    contact: DecisionMaker | None = None
