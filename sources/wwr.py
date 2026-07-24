import html
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

import httpx

from models.job import Job
from sources.base import BaseSource

# We Work Remotely — continuously updated, delivered as per-category RSS.
# Titles are "Company: Role"; region is the location; description is escaped HTML.
FEEDS = [
    "https://weworkremotely.com/categories/remote-programming-jobs.rss",
    "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss",
]
_HEADERS = {"User-Agent": "Mozilla/5.0"}


class WeWorkRemotely(BaseSource):
    name = "wwr"

    def fetch(self) -> list[Job]:
        jobs: list[Job] = []
        for feed in FEEDS:
            try:  # per-feed isolation: one bad feed doesn't kill the source
                resp = httpx.get(feed, headers=_HEADERS, timeout=30)
                resp.raise_for_status()
                jobs.extend(self._parse(resp.text))
            except Exception:
                continue
        return jobs

    def _parse(self, xml: str) -> list[Job]:
        out: list[Job] = []
        for item in re.findall(r"<item>(.*?)</item>", xml, re.DOTALL):
            title = _tag(item, "title")
            if not title:
                continue
            company, role = _split_title(title)
            out.append(Job(
                title=role,
                company=company,
                company_url="",
                description=_strip_html(_tag(item, "description")),
                location=_tag(item, "region") or "remote",
                tags=[],
                source=self.name,
                source_url=_tag(item, "link"),
                posted_at=_parse_rfc822(_tag(item, "pubDate")),
            ))
        return out


def _tag(item: str, name: str) -> str:
    m = re.search(rf"<{name}>(.*?)</{name}>", item, re.DOTALL)
    if not m:
        return ""
    val = m.group(1).strip()
    return re.sub(r"^<!\[CDATA\[|\]\]>$", "", val).strip()


def _split_title(title: str) -> tuple[str, str]:
    """WWR titles are 'Company: Role'."""
    if ":" in title:
        company, role = title.split(":", 1)
        return company.strip()[:80], role.strip()[:120]
    return "(WWR)", title[:120]


def _strip_html(s: str) -> str:
    s = html.unescape(s)  # WWR escapes its HTML (&lt;p&gt; ...)
    s = re.sub(r"(?i)<\s*br\s*/?>", "\n", s)
    s = re.sub(r"(?i)<\s*p\s*>", "\n", s)
    s = re.sub(r"<[^>]+>", "", s)
    return s.strip()


def _parse_rfc822(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
