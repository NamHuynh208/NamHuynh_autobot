import re
import time

from .config import env

WINDOW_MS = 24 * 3600 * 1000
SEND_URL = "https://graph.facebook.com/v21.0/me/messages"


def enabled():
    return (all(env(name) for name in ("FB_APP_SECRET", "FB_VERIFY_TOKEN", "FB_PAGE_ACCESS_TOKEN"))
            and all(re.fullmatch(r"[0-9]{1,32}", env(name)) for name in ("FB_PAGE_ID", "MY_FB_PSID")))


def fresh(sent):
    age = int(time.time() * 1000) - sent
    return -300_000 <= age < WINDOW_MS


def chunks(text):
    start, units = 0, 0
    for index, char in enumerate(text):
        width = 2 if ord(char) > 0xFFFF else 1
        if units + width > 2000:
            yield text[start:index]
            start, units = index, 0
        units += width
    if start < len(text):
        yield text[start:]


async def send_text(client, text, sent, *, messaging_type):
    delivered = False
    for part in chunks(text):
        if not fresh(sent):
            return False
        result = await client.post(SEND_URL, headers={"Authorization": f"Bearer {env('FB_PAGE_ACCESS_TOKEN')}"},
                                   json={"recipient": {"id": env("MY_FB_PSID")}, "messaging_type": messaging_type,
                                         "message": {"text": part}})
        result.raise_for_status()
        if not result.json().get("message_id"):
            raise ValueError("Graph API chưa xác nhận message_id")
        delivered = True
    return delivered
