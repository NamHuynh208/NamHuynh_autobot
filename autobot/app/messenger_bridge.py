import asyncio
import json
import logging
from urllib.parse import quote

import httpx

from .config import env


def message(room, event, domain):
    sender = event.get("sender", "")
    if not (event.get("type") == "m.room.message" and sender.startswith("@facebook_")
            and sender.endswith(":" + domain)):
        return None
    content = event.get("content", {})
    body = content.get("body")
    if (content.get("msgtype") != "m.text" or not isinstance(body, str) or not body.strip()
            or content.get("m.relates_to", {}).get("rel_type") == "m.replace"):
        return None
    return ("messenger", event["event_id"], room, sender[:160], body[:8000], event["origin_server_ts"] // 1000)


async def lookup(get, cache, key, path, field):
    # Failed lookups are not cached, so a transient error retries on the next message.
    if key not in cache:
        try:
            cache[key] = (await get(path, {})).get(field) or ""
        except Exception:
            return ""
    return cache[key]


async def run_matrix(db, health):
    token = env("MATRIX_ACCESS_TOKEN")
    if not token:
        health["matrix"] = "disabled"
        return
    health["matrix"] = "connecting"
    domain = env("MATRIX_DOMAIN", "matrix.autobot.internal")
    since = await db.get("matrix_since")
    names = {}
    filter_config = json.dumps({"room": {"timeline": {"limit": 100, "types": ["m.room.message"]},
                                        "state": {"types": []}, "ephemeral": {"types": []}},
                                "presence": {"types": []}})
    async with httpx.AsyncClient(base_url=env("MATRIX_URL", "http://synapse:8008"), trust_env=False,
                                 headers={"Authorization": f"Bearer {token}"}, timeout=45) as client:
        async def get(path, params):
            response = await client.get("/_matrix/client/v3/" + path, params=params)
            response.raise_for_status()
            return response.json()

        while True:
            try:
                params = {"timeout": 25000 if since else 0, "filter": filter_config, "set_presence": "offline"}
                if since:
                    params["since"] = since
                data = await get("sync", params)
                for room, info in data.get("rooms", {}).get("join", {}).items():
                    if not since or not db.settings.allows("messenger", room):
                        continue
                    timeline = info.get("timeline", {})

                    async def insert(events):
                        rows = [row for event in events if (row := message(room, event, domain))]
                        where = await lookup(get, names, "r" + room, f"rooms/{quote(room, safe='')}/state/m.room.name", "name")
                        out = []
                        for row in rows:
                            who = await lookup(get, names, "u" + row[3], f"profile/{quote(row[3], safe='')}", "displayname") or row[3]
                            out.append(row[:3] + ((f"{who} · {where}" if where else who)[:160],) + row[4:])
                        await db.ingest(out)

                    if timeline.get("limited") and timeline.get("prev_batch"):
                        cursor = timeline["prev_batch"]
                        while cursor and cursor != since and db.settings.allows("messenger", room):
                            page = await get(f"rooms/{quote(room, safe='')}/messages", {
                                "from": cursor, "to": since, "dir": "b", "limit": 100,
                                "filter": json.dumps({"types": ["m.room.message"]}),
                            })
                            await insert(page.get("chunk", []))
                            end = page.get("end")
                            if end == cursor:
                                break
                            cursor = end
                    await insert(timeline.get("events", []))
                await db.ingest([], data["next_batch"])
                since = data["next_batch"]
                health["matrix"] = "ready"
            except Exception as exc:
                health["matrix"] = "error"
                logging.warning("Matrix /sync: %s; thử lại sau 15 giây.", type(exc).__name__)
                await asyncio.sleep(15)
