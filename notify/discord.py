import httpx

import config
from models.job import Prospect

# Discord embed limits worth knowing: title 256, field value 1024,
# description 4096, 25 fields max, total embed 6000 chars. Drafts can be long —
# truncate field values to ~1000 chars and note if clipped.

_TIER_COLOR = {
    "strong": 0x2ECC71,  # green
    "maybe": 0xF1C40F,   # yellow
}


def _truncate(text: str, limit: int = 1000) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _webhook_for(source: str) -> str:
    """YC startup leads go to their own channel (cold-outreach flow); everything
    else to the main channel. Falls back to main if the YC hook isn't set."""
    if source == "yc" and config.DISCORD_WEBHOOK_YC:
        return config.DISCORD_WEBHOOK_YC
    return config.DISCORD_WEBHOOK_URL


def _contact_line(prospect: Prospect) -> str:
    c = prospect.contact
    if not c:
        return "⚠️ no verified contact — use the source/apply link"
    title = f" — {c.title}" if c.title else ""
    email = f"\n📧 {c.email}  `[{c.email_confidence}]`" if c.email else ""
    return f"👤 **{c.name}**{title}  ·  _{c.source}_{email}"


def send(prospect: Prospect) -> None:
    job, fit = prospect.job, prospect.fit
    embed = {
        "title": _truncate(f"🎯 {job.title} @ {job.company}", 256),
        "url": job.source_url or job.company_url,
        "color": _TIER_COLOR.get(fit.tier, 0x95A5A6),
        "description": _truncate(
            f"**Fit:** {fit.score}/10 ({fit.tier}) — {fit.reason}\n\n{_contact_line(prospect)}"
        ),
        "fields": [
            {"name": "📧 Email draft", "value": _truncate(prospect.email_draft)},
            {"name": "💬 LinkedIn draft", "value": _truncate(prospect.linkedin_draft)},
            {"name": "🔗 Source", "value": job.source_url or "n/a", "inline": True},
            {"name": "📍 Via", "value": job.source, "inline": True},
        ],
    }
    resp = httpx.post(_webhook_for(job.source), json={"embeds": [embed]}, timeout=15)
    resp.raise_for_status()
