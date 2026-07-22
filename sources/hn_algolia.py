import html
import re
from datetime import datetime, timezone

import httpx

from models.job import Job
from sources.base import BaseSource

# HN "Who is Hiring" is a monthly thread posted by user 'whoishiring'. Each
# top-level comment is one job posting — freeform text, no structured fields.
# Posters loosely follow: "Company | Role | Location | REMOTE | stack..."
#
# Two-step: find the latest thread via Algolia, then fetch its comments.
SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{story_id}"
HN_ITEM_LINK = "https://news.ycombinator.com/item?id={cid}"

_HEADERS = {"User-Agent": "Mozilla/5.0"}


class HackerNews(BaseSource):
    name = "hn"

    def fetch(self) -> list[Job]:
        story_id = self._latest_thread_id()
        if story_id is None:
            return []

        resp = httpx.get(ITEM_URL.format(story_id=story_id), headers=_HEADERS, timeout=30)
        resp.raise_for_status()
        children = resp.json().get("children") or []

        jobs: list[Job] = []
        for c in children:
            raw = c.get("text")
            if not raw:  # deleted comment or a meta note
                continue

            text = _strip_html(raw)
            first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
            if not first_line:
                continue

            company, _role = _parse_header(first_line)
            remote = bool(re.search(r"\bremote\b", text, re.IGNORECASE))

            jobs.append(Job(
                # Use the keyword-rich header line as the title so the prefilter
                # can match on it (HN posts have no tags).
                title=first_line[:200],
                company=company,
                company_url="",
                description=text,
                location="remote" if remote else "onsite",
                tags=[],
                source=self.name,
                source_url=HN_ITEM_LINK.format(cid=c.get("id")),
                posted_at=_epoch_to_dt(c.get("created_at_i")),
            ))
        return jobs

    def _latest_thread_id(self) -> int | None:
        resp = httpx.get(
            SEARCH_URL,
            params={"query": "Ask HN: Who is hiring?",
                    "tags": "story,author_whoishiring", "hitsPerPage": 1},
            headers=_HEADERS, timeout=20,
        )
        resp.raise_for_status()
        hits = resp.json().get("hits") or []
        return int(hits[0]["objectID"]) if hits else None


def _strip_html(s: str) -> str:
    s = re.sub(r"(?i)<\s*br\s*/?>", "\n", s)
    s = re.sub(r"(?i)<\s*p\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def _parse_header(first_line: str) -> tuple[str, str]:
    """Best-effort: 'Company | Role | ...' → (company, role)."""
    parts = [p.strip() for p in first_line.split("|") if p.strip()]
    if len(parts) >= 2:
        return parts[0][:80], parts[1][:120]
    return "(HN post)", first_line[:120]


def _epoch_to_dt(epoch: int | None) -> datetime | None:
    if not epoch:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc)
