import config
from models.job import Job, FitResult, Prospect
from models.contact import DecisionMaker
from pipeline.llm_util import client as _client, extract_json
from pipeline.profile import get_profile_text

# Two drafts per prospect: a professional email and a shorter, casual LinkedIn
# message. Both personalized to the company + role, grounded in the profile.
# Human-in-the-loop: these are DRAFTS Asmit reviews and sends, never auto-sent.
_SYSTEM = """You write cold outreach for a job seeker reaching out to startups.

Given the candidate profile and a job, write two drafts. Follow the candidate's
`voice` guidance. Lead with a specific hook tied to THIS company/role. No "I hope
this finds you well." Keep it tight and technical.

Whenever you name a specific project (e.g. leankv, LLM-Doc), include ITS GitHub
repo link inline from the profile's REPO LINKS — link the specific repo, not just
the profile. Only use links present in the profile; never invent one.

Respond ONLY with JSON:
{"email": "<subject line + body>", "linkedin": "<1-3 sentence connection message>"}"""

def draft(job: Job, fit: FitResult, contact: DecisionMaker | None) -> tuple[str, str]:
    # Address the email to the decision-maker by name when we found one.
    who = f"{contact.name} ({contact.title})" if contact and contact.title else \
          (contact.name if contact else "the team")
    user_msg = (
        f"CANDIDATE PROFILE:\n{get_profile_text()}\n\n"
        f"JOB:\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Address the outreach to: {who}\n"
        f"Why it fits: {fit.reason}\n"
        f"Description: {job.description[:1500]}"
    )

    resp = _client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0.7,
        max_tokens=800,
    )
    data = extract_json(resp.choices[0].message.content)
    return data.get("email", ""), data.get("linkedin", "")


def run(enriched: list[tuple]) -> list[Prospect]:
    """enriched: list[(Job, FitResult, DecisionMaker|None)]."""
    prospects = []
    for job, fit, contact in enriched:
        email_draft, linkedin_draft = draft(job, fit, contact)
        prospects.append(Prospect(
            job=job, fit=fit,
            email_draft=email_draft, linkedin_draft=linkedin_draft,
            contact=contact,
        ))
    return prospects
