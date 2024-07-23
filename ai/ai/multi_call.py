from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from threading import get_ident

from loguru import logger

from .prompts import DEFAULT
from .providers import AiCall, ai_calls, get_env_keys


def complete(
    prompts: dict[str, str],
    keys: dict[str, str] | None = None,
    temperature: float = 0.6,
    calls: Iterable[AiCall] | None = None,
) -> dict[str, tuple[str | None, Exception | None]]:
    if calls is None:
        calls = ai_calls
    if keys is None:
        keys = get_env_keys({provider for provider, _, _ in calls})

    def _execute_ai_call(ai_call: AiCall) -> tuple[str, str | None, Exception | None]:
        provider, model_name, model_call = ai_call
        logger.info(f"Calling {provider}: {model_name} on thread #{get_ident()}")
        prompt = prompts.get(provider) or prompts.get(DEFAULT)
        key = keys[provider]
        try:
            error = None
            result = model_call(key, model_name, prompt, temperature)
        except Exception as e:  # noqa: BLE001
            error = e
            result = None
        logger.info(f"Completed {provider}: {model_name}")
        return model_name, result, error

    with ThreadPoolExecutor() as executor:
        # Mapping the read_first_line function over all file paths
        results = executor.map(_execute_ai_call, calls)
        return {r[0]: (r[1], r[2]) for r in results}
