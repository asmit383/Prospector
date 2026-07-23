import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

load_dotenv()

_CONFIG_DIR = Path(__file__).parent


def _load_yaml(name: str) -> dict:
    path = _CONFIG_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Missing config file: {path}. Copy {name.replace('.yaml', '.example.yaml')} and fill it in."
        )
    with open(path) as f:
        return yaml.safe_load(f)


# Secrets from environment
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]
LLM_API_KEY = os.environ["LLM_API_KEY"]
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = os.environ.get("LLM_MODEL", "gpt-4o-mini")
DISCORD_WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]

# Optional — enrich the profile from live GitHub. Username falls back to the
# `github:` URL in my_profile.yaml. Token is optional (60→5000 req/hr).
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")

# Personal config from YAML
PROFILE = _load_yaml("my_profile.yaml")
FILTERS = _load_yaml("filters.yaml")
