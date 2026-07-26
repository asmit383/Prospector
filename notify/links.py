"""One-click outreach links for the Discord embed.

Web-Gmail has a compose URL that pre-fills recipient/subject/body — clicking it
opens a compose window with everything filled, so the human just reviews + sends.
This is the human-in-the-loop "one click to draft, you send" flow, no desktop
mail client needed.
"""
from urllib.parse import quote

_GMAIL_COMPOSE = "https://mail.google.com/mail/?view=cm&fs=1"


def gmail_compose(to: str, subject: str, body: str) -> str:
    """A Gmail web compose URL with the fields pre-filled. safe='' so '@', '/'
    and newlines are all percent-encoded (Gmail decodes %0A → line breaks)."""
    return (
        f"{_GMAIL_COMPOSE}"
        f"&to={quote(to, safe='')}"
        f"&su={quote(subject, safe='')}"
        f"&body={quote(body, safe='')}"
    )


def first_email(email: str | None) -> str | None:
    """A contact email may be a guessed multi-candidate string
    ("sam@x / founders@x") — take the first as the compose recipient; the human
    edits it in Gmail if wrong. Returns None if there's nothing usable."""
    if not email:
        return None
    return (email.split("/")[0].strip() or None)
