from dataclasses import dataclass


@dataclass
class DecisionMaker:
    name: str
    title: str
    email: str | None
    # "verified" (real email found on their domain), "generic" (a role inbox like
    # founders@), "guessed" (inferred first@domain), "none"
    email_confidence: str
    source: str                 # where the contact was found (the domain)
    linkedin_url: str | None = None
