import re

from .config import Settings, env


def _key():
    key = env("OPENAI_API_KEY")
    if not key:
        raise ValueError("Thiếu OPENAI_API_KEY")
    return key


async def complete(client, settings, messages, *, model=None, effort=""):
    # Revalidate saved configuration against the current server-side endpoint allowlist.
    Settings.model_validate(settings.model_dump())
    body = {"model": model or settings.model, "messages": messages}
    if effort:
        body["reasoning_effort"] = effort
    response = await client.post(settings.base_url + "/chat/completions", headers={"Authorization": f"Bearer {_key()}"},
                                 json=body)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()


async def advisor_model(client, settings):
    """Newest '*-sol' model the key can list, else OPENAI_ADVISOR_MODEL."""
    Settings.model_validate(settings.model_dump())
    try:
        response = await client.get(settings.base_url + "/models", headers={"Authorization": f"Bearer {_key()}"})
        response.raise_for_status()
        sols = [m["id"] for m in response.json().get("data", []) if "sol" in str(m.get("id", "")).split("-")]
        if sols:
            return max(sols, key=lambda name: tuple(int(n) for n in re.findall(r"\d+", name)))
    except Exception:
        pass
    return env("OPENAI_ADVISOR_MODEL", "gpt-6.2-sol")
