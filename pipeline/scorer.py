import config
from models.job import Job, FitResult
from pipeline.llm_util import client as _client, extract_json
from pipeline.profile import get_profile_text

# Force structured output. We gate on `tier`, not the raw number — the score
# is only for ranking within a tier.
_SYSTEM = """You are a job-fit evaluator. Given a candidate profile and a job
posting, judge how well they match for the candidate's goals.

Respond ONLY with JSON of exactly this shape:
{"score": <integer 1-10>, "tier": "strong"|"maybe"|"no", "reason": "<one sentence>"}

tier guidance:
- "strong": clearly matches the candidate's skills AND target roles; worth reaching out.
- "maybe": partial fit or adjacent; could be worth it.
- "no": wrong domain, wrong seniority, or unrelated."""

def score(job: Job) -> FitResult:
    user_msg = (
        f"CANDIDATE PROFILE:\n{get_profile_text()}\n\n"
        f"JOB POSTING:\n"
        f"Title: {job.title}\n"
        f"Company: {job.company}\n"
        f"Tags: {', '.join(job.tags)}\n"
        f"Salary: {job.salary_min}-{job.salary_max}\n"
        f"Description: {job.description[:2000]}"
    )

    resp = _client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user_msg},
        ],
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=300,
    )
    data = extract_json(resp.choices[0].message.content)
    return FitResult(
        score=int(data.get("score", 0)),
        tier=str(data.get("tier", "no")).lower(),
        reason=str(data.get("reason", "")),
    )


def run(jobs: list[Job]) -> list[tuple[Job, FitResult]]:
    """Score each job and return EVERY verdict, including "no".

    The caller persists all of them: a job scored "no" today scores "no"
    tomorrow, so recording the verdict means the deduper skips it next run and
    the LLM never re-scores it. Returning only survivors here would leave the
    rejects unrecorded — and re-scored on every daily run until they age out."""
    return [(job, score(job)) for job in jobs]
