import yaml

import config
from models.job import Job, FitResult, Prospect
from pipeline.llm_util import client as _client, extract_json

# Two drafts per prospect: a professional email and a shorter, casual LinkedIn
# message. Both personalized to the company + role, grounded in the profile.
# Human-in-the-loop: these are DRAFTS Asmit reviews and sends, never auto-sent.
_SYSTEM = """You write cold outreach for a job seeker reaching out to startups.

Given the candidate profile and a job, write two drafts. Follow the candidate's
`voice` guidance. Lead with a specific hook tied to THIS company/role. No "I hope
this finds you well." Keep it tight and technical.

Respond ONLY with JSON:
{"email": "<subject line + body>", "linkedin": "<1-3 sentence connection message>"}"""

_PROFILE_STR = yaml.safe_dump(config.PROFILE, sort_keys=False)


def draft(job: Job, fit: FitResult) -> tuple[str, str]:
    user_msg = (
        f"CANDIDATE PROFILE:\n{_PROFILE_STR}\n\n"
        f"JOB:\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
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


def run(scored: list[tuple[Job, FitResult]]) -> list[Prospect]:
    prospects = []
    for job, fit in scored:
        email_draft, linkedin_draft = draft(job, fit)
        prospects.append(Prospect(
            job=job, fit=fit,
            email_draft=email_draft, linkedin_draft=linkedin_draft,
        ))
    return prospects
