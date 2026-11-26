import asyncio
import hmac
import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient

from app import page_chat
from app.page_delivery import SEND_URL
from app.config import Settings
from app.database import Database
from app.web_app import PUBLIC_ORIGIN, app


CONFIG = {"FB_APP_SECRET": "test-secret", "FB_VERIFY_TOKEN": "test-verify", "FB_PAGE_ACCESS_TOKEN": "test-page-token",
          "FB_PAGE_ID": "123", "MY_FB_PSID": "456"}
PATH = "/webhook/messenger"
CHANNEL = "123456789012345678"
OTHER = "123456789012345679"


def signed(body):
    return {"X-Hub-Signature-256": "sha256=" + hmac.digest(CONFIG["FB_APP_SECRET"].encode(), body, "sha256").hex()}


class WebhookTests(unittest.TestCase):
    def test_verification_signature_allowlist_and_dedupe(self):
        async def no_worker(*args):
            pass

        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, CONFIG | {
            "ADMIN_PASSWORD": "test admin password only", "DATABASE_PATH": str(Path(temp) / "app.db"),
            "DISCORD_USER_TOKEN": "", "MATRIX_ACCESS_TOKEN": "",
        }), patch.object(page_chat, "run_page_chat", no_worker), TestClient(app, base_url=PUBLIC_ORIGIN) as client:
            params = {"hub.mode": "subscribe", "hub.verify_token": "test-verify", "hub.challenge": "00123"}
            self.assertEqual(client.get(PATH, params=params).text, "00123")
            self.assertEqual(client.get(PATH, params=params | {"hub.verify_token": "wrong"}).status_code, 403)
            now = int(time.time() * 1000)
            event = {"sender": {"id": "456"}, "recipient": {"id": "123"}, "timestamp": now}
            payload = {"object": "page", "entry": [{"id": "123", "messaging": [
                event | {"message": {"mid": "allowed", "text": "Lịch họp?"}},
                event | {"sender": {"id": "789"}, "message": {"mid": "other", "text": "/tomtat"}},
                event | {"message": {"mid": "echo", "text": "/status", "is_echo": True}},
                event | {"timestamp": now - page_chat.WINDOW_MS, "message": {"mid": "old", "text": "Hi"}},
                event | {"recipient": {"id": "321"}, "message": {"mid": "wrong-page", "text": "Hi"}},
            ]}]}
            body = json.dumps(payload, ensure_ascii=False).encode()
            self.assertEqual(client.post(PATH, content=body).status_code, 403)
            self.assertEqual(client.post(PATH, content=body + b" ", headers=signed(body)).status_code, 403)
            self.assertEqual(client.post(PATH, content=b"{", headers=signed(b"{")).status_code, 400)
            large = b"x" * 200_001
            self.assertEqual(client.post(PATH, content=large, headers=signed(large)).status_code, 413)
            for _ in range(2):
                self.assertEqual(client.post(PATH, content=body, headers=signed(body)).text, "EVENT_RECEIVED")
            with patch.dict(os.environ, {"MY_FB_PSID": ""}):
                self.assertEqual(client.post(PATH, content=body.replace(b"allowed", b"disabled"),
                                             headers=signed(body.replace(b"allowed", b"disabled"))).status_code, 200)
            rows = client.portal.call(app.state.db.rows, "SELECT mid,question FROM page_inbox")
            self.assertEqual(rows, [{"mid": "allowed", "question": "Lịch họp?"}])


class ReplyTests(unittest.IsolatedAsyncioTestCase):
    async def test_worker_clears_question_but_keeps_dedup_key(self):
        db = Database()
        await db.open(":memory:")
        self.addAsyncCleanup(db.conn.close)
        stamp = int(time.time() * 1000)
        async with db.tx() as conn:
            await conn.execute("INSERT INTO page_inbox VALUES('new','123','456',?,'/status')", (stamp,))
            await conn.execute("INSERT INTO page_inbox VALUES('old','123','456',?,'/status')", (stamp - page_chat.WINDOW_MS,))
        state = SimpleNamespace(page_wake=asyncio.Event())
        sent = asyncio.Event()

        async def fake_reply(db, state, client, job, services):
            self.assertEqual(job["mid"], "new")
            sent.set()

        with patch.dict(os.environ, CONFIG), patch.object(page_chat, "reply", fake_reply):
            task = asyncio.create_task(page_chat.run_page_chat(db, state, None))
            try:
                await asyncio.wait_for(sent.wait(), 3)
                self.assertEqual(await db.rows("SELECT mid,question FROM page_inbox"), [{"mid": "new", "question": None}])
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)

    async def test_context_respects_current_whitelist_and_commands_skip_ai(self):
        db = Database()
        await db.open(":memory:")
        self.addAsyncCleanup(db.conn.close)
        server_id, ignored_thread = "123456789012345680", "123456789012345681"
        await db.save_settings(Settings(discord_servers=[server_id], discord_rooms=[CHANNEL, OTHER]))
        now = int(time.time())
        await db.ingest([("discord", "old", CHANNEL, "An", "LỊCH HỌP thứ sáu", now - 86400),
                         ("discord", "hidden", OTHER, "An", "Nội dung phòng đã bỏ theo dõi", now)]
                         + [("discord", f"recent-{i}", CHANNEL, "An", f"Tin mới {i}", now) for i in range(30)],
                        server_id=server_id)
        await db.ingest([("discord", "thread", ignored_thread, "An", "Lịch họp bí mật", now)],
                        server_id=server_id, parent_id=OTHER)
        await db.save_settings(Settings(discord_servers=[server_id], discord_ignore=[OTHER]))
        await db.ingest([("discord", "ignored", ignored_thread, "An", "Không lưu", now)], server_id=server_id, parent_id=OTHER)
        self.assertFalse(await db.rows("SELECT id FROM messages WHERE external_id='ignored'"))
        calls = []
        long_answer = "📅" * 1001 + "a" * 2000

        def upstream(request):
            payload = json.loads(request.content)
            calls.append((str(request.url), payload))
            if request.url.path.endswith("chat/completions"):
                context = json.loads(payload["messages"][1]["content"])
                if "cau_noi" in context:
                    return httpx.Response(200, json={"choices": [{"message": {"content": "{\"action\": \"none\"}"}}]})
                assert any(row["content"] == "LỊCH HỌP thứ sáu" for row in context["messages"])
                assert any(row["content"].startswith("Tin mới") for row in context["messages"])
                assert all(row["room"] == CHANNEL and "+07:00" in row["ts"] for row in context["messages"])
                return httpx.Response(200, json={"choices": [{"message": {"content": long_answer}}]})
            assert str(request.url) == SEND_URL
            assert request.headers["Authorization"] == "Bearer test-page-token"
            assert payload["recipient"] == {"id": "456"}
            assert payload["messaging_type"] == "RESPONSE"
            return httpx.Response(200, json={"message_id": "sent"})

        state = SimpleNamespace(wake=asyncio.Event())
        services = lambda _: {"discord": "ready", "matrix": "ready", "meta": "CONNECTED", "scheduler": "ready"}
        job = {"page": "123", "sender": "456", "sent": int(time.time() * 1000)}
        with patch.dict(os.environ, CONFIG | {"OPENAI_API_KEY": "mock", "APP_TIMEZONE": "Asia/Ho_Chi_Minh"}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
                await page_chat.reply(db, state, client, job | {"question": "Tìm tin nhắn nhắc tới lịch họp"}, services)
                parts = [payload["message"]["text"] for url, payload in calls if url == SEND_URL]
                self.assertEqual("".join(parts), long_answer)
                self.assertTrue(all(len(text.encode("utf-16-le")) // 2 <= 2000 for text in parts))
                for command in ("/status", "/tomtat"):
                    await page_chat.reply(db, state, client, job | {"question": command}, services)
                await page_chat.reply(db, state, client, job | {"sender": "789", "question": "/status"}, services)
                self.assertEqual(len(calls), 7)
                self.assertIn("Scheduler: hoạt động", calls[-2][1]["message"]["text"])
                self.assertIn("dashboard", calls[-1][1]["message"]["text"])
                self.assertTrue(state.wake.is_set())
                self.assertEqual(await db.rows("SELECT kind FROM jobs"), [{"kind": "manual"}])


class AdvisorTest(unittest.IsolatedAsyncioTestCase):
    async def test_escalation_picks_newest_sol_and_falls_back(self):
        db = Database()
        await db.open(":memory:")
        self.addAsyncCleanup(db.conn.close)
        await db.save_settings(Settings(discord_rooms=[CHANNEL]))
        await db.ingest([("discord", "m1", CHANNEL, "An · #chung", "Dự án trễ hạn", int(time.time()))])
        models = []

        def upstream(request):
            if request.url.path.endswith("/models"):
                return httpx.Response(200, json={"data": [{"id": "gpt-6-luna"}, {"id": "gpt-6.2-sol"}, {"id": "gpt-6.10-sol"}]})
            payload = json.loads(request.content)
            models.append((payload["model"], payload.get("reasoning_effort")))
            if len(models) == 1:
                return httpx.Response(200, json={"choices": [{"message": {"content": page_chat.ESCALATE}}]})
            if payload["model"].endswith("-sol"):
                return httpx.Response(404)
            return httpx.Response(200, json={"choices": [{"message": {"content": "Lời khuyên"}}]})

        env = {"OPENAI_API_KEY": "mock", "OPENAI_ADVISOR_EFFORT": "medium", "OPENAI_REASONING_EFFORT": "max"}
        with patch.dict(os.environ, env):
            async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
                text = await page_chat.answer(db, client, "Nên xử lý dự án trễ hạn thế nào?")
        self.assertEqual(models[1], ("gpt-6.10-sol", "medium"))
        self.assertEqual(models[2][1], "max")
        self.assertTrue(text.startswith("(Sol chưa dùng được") and text.endswith("Lời khuyên"))


class SourceMuteTest(unittest.IsolatedAsyncioTestCase):
    async def test_natural_language_mute_list_unmute(self):
        db = Database()
        await db.open(":memory:")
        self.addAsyncCleanup(db.conn.close)
        room = "!nhom:matrix.autobot.internal"
        thread = "123456789012345690"
        await db.save_settings(Settings(discord_rooms=[CHANNEL, thread], matrix_rooms=[room]))
        now = int(time.time())
        await db.ingest([("messenger", "m1", room, "An · Nhóm CLB", "a", now),
                         ("discord", "d1", CHANNEL, "Bình · #chung", "b", now)])
        await db.ingest([("discord", "d2", thread, "Chi · #chung › Kế hoạch", "c", now)], parent_id=CHANNEL)
        plans = iter([{"action": "mute", "ids": [room, CHANNEL, "!bịa:x"]}, {"action": "list"},
                      {"action": "mute", "ids": [], "hoi_lai": "Ý bạn là #chung hay #chung › Kế hoạch?"},
                      {"action": "unmute", "ids": [CHANNEL]}, {"action": "none"}])

        def upstream(request):
            sent = json.loads(json.loads(request.content)["messages"][1]["content"])
            assert {s["id"] for s in sent["nguon"]} == {room, CHANNEL, thread}
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(next(plans))}}]})

        with patch.dict(os.environ, {"OPENAI_API_KEY": "mock"}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
                ask = lambda: page_chat.manage_sources(db, client, "câu nói")
                self.assertIn("Đã tắt tóm tắt: Nhóm CLB, #chung", await ask())
                self.assertEqual((db.settings.matrix_ignore, db.settings.discord_ignore), ([room], [CHANNEL]))
                # Thread under the muted channel is skipped too.
                self.assertEqual(await db.rows("SELECT is_summarized FROM messages"), [{"is_summarized": 1}] * 3)
                listing = await ask()
                self.assertIn("Nhóm CLB", listing)
                self.assertIn("Kế hoạch", await ask())
                self.assertIn("Đã bật lại", await ask())
                self.assertEqual(db.settings.discord_ignore, [])
                self.assertIsNone(await ask())
