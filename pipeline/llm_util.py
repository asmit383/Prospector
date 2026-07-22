import json
import re

from openai import OpenAI

import config

# Shared LLM client for all pipeline stages.
client = OpenAI(api_key=config.LLM_API_KEY, base_url=config.LLM_BASE_URL)

_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_FENCE_RE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def extract_json(content: str) -> dict:
    """Parse a JSON object out of an LLM response, tolerating the junk models
    sometimes wrap it in: <think> monologues, ```json fences, leading prose.
    Raises json.JSONDecodeError if no valid object is found."""
    if not content:
        raise json.JSONDecodeError("empty content", "", 0)

    text = _THINK_RE.sub("", content)          # drop <think>...</think>
    text = _FENCE_RE.sub("", text).strip()     # drop code fences

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Fallback: grab the first balanced {...} object.
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start:end + 1])
        raise
