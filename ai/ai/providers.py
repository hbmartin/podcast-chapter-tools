from collections.abc import Callable, Iterable
from os import environ
from typing import TypeAlias

from podcast_transcript_tools.ai.api_calls import (
    _call_anthropic,
    _call_google,
    _call_openai,
)

# provider, model, callable function
AiCall: TypeAlias = tuple[str, str, Callable[[str, str, str, float], str]]

OPENAI = "openai"
ANTHROPIC = "anthropic"
GOOGLE = "google"

ANTHROPIC_MODEL = environ.get("ANTHROPIC_MODEL") or "claude-3-5-sonnet-20240620"
GPT_MODEL = environ.get("GPT_MODEL") or "gpt-4o-2024-05-13"
GEMINI_MODEL = environ.get("GEMINI_MODEL") or "gemini-1.5-pro-latest"


ai_calls: set[AiCall] = {
    (OPENAI, GPT_MODEL, _call_openai),
    (ANTHROPIC, ANTHROPIC_MODEL, _call_anthropic),
    (GOOGLE, GEMINI_MODEL, _call_google),
}


def get_env_keys(providers: Iterable[str]) -> dict[str, str]:
    keys: dict[str, str] = {
        provider: environ[f"{provider.upper()}_API_KEY"].strip()
        for provider in providers
    }
    return {k: v for k, v in keys.items() if v}
