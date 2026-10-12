import google.generativeai as gemini
from anthropic import Anthropic
from openai import OpenAI


def _call_anthropic(api_key: str, model: str, prompt: str, temperature: float) -> str:
    """Send a prompt to Anthropic and return the first response text."""
    anthropic = Anthropic(api_key=api_key)

    result = anthropic.messages.create(
        model=model,
        max_tokens=3000,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )

    return result.content[0].text


def _call_openai(api_key: str, model: str, prompt: str, temperature: float) -> str:
    """Send a chat prompt to OpenAI and return the first response content."""
    openai_client = OpenAI(api_key=api_key)
    result = openai_client.chat.completions.create(
        model=model,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return result.choices[0].message.content


def _call_google(
    api_key: str,
    model: str,
    prompt: str,
    temperature: float,  # noqa: ARG001
) -> str:
    """Send a prompt to Gemini and return the generated text."""
    gemini.configure(api_key=api_key)
    genai_model = gemini.GenerativeModel(model)

    result = genai_model.generate_content(prompt)

    return result.text
