from .config import Settings, env


async def complete(client, settings, messages):
    # Revalidate saved configuration against the current server-side endpoint allowlist.
    Settings.model_validate(settings.model_dump())
    key = env("OPENAI_API_KEY")
    if not key:
        raise ValueError("Thiếu OPENAI_API_KEY")
    response = await client.post(settings.base_url + "/chat/completions", headers={"Authorization": f"Bearer {key}"},
                                 json={"model": settings.model, "messages": messages})
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"].strip()
