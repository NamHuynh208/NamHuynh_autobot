import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.database import Database
from app.messenger_bridge import message
from app.summarizer import enqueue, process_job, scheduled_slots
from app.web_app import PUBLIC_ORIGIN, app


CHANNEL = "123456789012345678"
ROOM = "!inbox:matrix.autobot.internal"
ORIGIN = {"Origin": PUBLIC_ORIGIN}


class SettingsTests(unittest.TestCase):
    def test_scheduled_slots_use_local_morning_and_dedup_key(self):
        settings = Settings()
        morning = datetime.fromisoformat("2026-11-19T07:30:00+07:00")
        self.assertEqual([name for name, _ in scheduled_slots(settings, morning)], ["morning"])
        self.assertEqual(list(scheduled_slots(settings, morning.replace(minute=34))), list(scheduled_slots(settings, morning)))
        self.assertEqual(list(scheduled_slots(settings, morning.replace(minute=35))), [])
        self.assertEqual([name for name, _ in scheduled_slots(settings, morning.replace(hour=8, minute=0))], ["interval"])
        self.assertEqual(list(scheduled_slots(Settings(automatic=False), morning)), [])

    def test_safe_defaults_and_url_allowlist(self):
        with patch.dict(os.environ, {"OPENAI_BASE_URL": "https://trusted.example/v1", "OPENAI_ALLOWED_ORIGINS": "https://second.example:8443"}):
            self.assertFalse(Settings().allows("discord", CHANNEL))
            for url in ("http://trusted.example/v1", "https://evil.example/v1", "https://trusted.example@evil.example", "https://second.example/v1"):
                with self.subTest(url=url), self.assertRaises(ValidationError):
                    Settings(base_url=url)
            self.assertEqual(Settings(base_url="https://second.example:8443/v1/").base_url, "https://second.example:8443/v1")

    def test_matrix_reader_only_accepts_ghost_text(self):
        event = {"sender": "@facebook_123:matrix.autobot.internal", "type": "m.room.message", "event_id": "$msg",
                 "origin_server_ts": 2000, "content": {"msgtype": "m.text", "body": "Chào"}}
        self.assertEqual(message(ROOM, event, "matrix.autobot.internal"), ("messenger", "$msg", ROOM, event["sender"], "Chào", 2))
        self.assertIsNone(message(ROOM, event | {"sender": "@bridgeowner:matrix.autobot.internal"}, "matrix.autobot.internal"))
        self.assertIsNone(message(ROOM, event | {"type": "m.room.encrypted"}, "matrix.autobot.internal"))


class DatabaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_reports_are_saved_with_expired_failed_and_successful_delivery(self):
        db = Database()
        await db.open(":memory:")
        self.addAsyncCleanup(db.conn.close)
        await db.save_settings(Settings(automatic=False, discord_rooms=[CHANNEL], matrix_rooms=[ROOM], matrix_ignore=[ROOM]))
        now = int(time.time())
        rows = [("discord", f"m{i}", CHANNEL, "An", "Hạn nộp lúc 18:00!" + "x" * 7000, now) for i in range(3)]
        rows.append(("messenger", "ignored", ROOM, "Bình", "Bị bỏ qua", now))
        await db.ingest(rows, "cursor1")
        await db.ingest(rows, "cursor2")
        self.assertEqual(await db.get("matrix_since"), "cursor2")
        self.assertEqual(len(await db.rows("SELECT * FROM messages")), 3)
        manual_id, queued = await enqueue(db, "manual")
        self.assertTrue(queued)
        self.assertEqual(await enqueue(db, "manual"), (manual_id, False))
        self.assertTrue((await enqueue(db, "interval", "slot1"))[1])
        self.assertFalse((await enqueue(db, "interval", "slot1"))[1])
        calls = []

        def upstream(request):
            calls.append(request.url.host)
            if request.url.path.endswith("/chat/completions"):
                assert "18:00" in request.content.decode()
                return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps({
                    "urgent": "Hạn chót 18:00!", "important": "", "casual": ""})}}]})
            body = json.loads(request.content)
            assert body["messaging_type"] == "UPDATE"
            assert body["recipient"] == {"id": "456"}
            assert "18:00!" in body["message"]["text"]
            if calls.count("graph.facebook.com") == 1:
                return httpx.Response(503)
            return httpx.Response(200, json={"message_id": "sent"})

        with patch.dict(os.environ, {"OPENAI_API_KEY": "mock", "FB_APP_SECRET": "secret", "FB_VERIFY_TOKEN": "verify",
                                     "FB_PAGE_ACCESS_TOKEN": "token", "FB_PAGE_ID": "123", "MY_FB_PSID": "456"}):
            async with httpx.AsyncClient(transport=httpx.MockTransport(upstream)) as client:
                async with db.tx() as conn:
                    await conn.execute("INSERT INTO page_inbox VALUES('old','123','456',?,NULL)", ((now - 86401) * 1000,))
                for expected in ("saved", "failed", "sent"):
                    if expected == "failed":
                        async with db.tx() as conn:
                            await conn.execute("INSERT INTO page_inbox VALUES('new','123','456',?,NULL)", (now * 1000,))
                    job = (await db.rows("SELECT * FROM jobs WHERE id=?", (manual_id,)))[0]
                    await process_job(db, client, job)
                    self.assertEqual(await db.rows("SELECT delivery FROM summaries ORDER BY id DESC LIMIT 1"), [{"delivery": expected}])
                self.assertEqual(len(calls), 5)
                self.assertEqual(await db.rows("SELECT is_summarized FROM messages"), [{"is_summarized": 1}] * 3)

    async def test_legacy_history_and_unfinished_batch_survive_upgrade(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "app.db"
            old = Database()
            await old.open(path)
            try:
                async with old.tx() as conn:
                    await conn.execute("DROP TABLE summaries")
                    await conn.execute("CREATE TABLE summaries(id INTEGER PRIMARY KEY, job_id, created, discord_count, "
                                       "messenger_count, body, last_message, message_ids, old_receipt)")
                    await conn.execute("INSERT INTO jobs(id,kind,created,cutoff) VALUES(1,'manual',100,2)")
                    await conn.execute("ALTER TABLE messages DROP COLUMN server_id")
                    await conn.execute("ALTER TABLE messages DROP COLUMN parent_id")
                    await conn.execute("INSERT INTO messages VALUES(2,'discord','m',?,'An','Test',100,0)", (CHANNEL,))
                    await conn.execute("INSERT INTO summaries VALUES(7,1,100,1,0,'{}',2,'[2]',NULL)")
            finally:
                await old.conn.close()
            db = Database()
            await db.open(path)
            try:
                self.assertEqual(await db.rows("SELECT id,body,delivery FROM summaries"), [{"id": 7, "body": "{}", "delivery": "saved"}])
                self.assertEqual(await db.rows("SELECT cursor FROM jobs"), [{"cursor": 2}])
                self.assertEqual(await db.rows("SELECT is_summarized,server_id,parent_id FROM messages"),
                                 [{"is_summarized": 1, "server_id": None, "parent_id": None}])
            finally:
                await db.conn.close()


class WebTests(unittest.TestCase):
    def test_login_csrf_settings_trigger_and_logout(self):
        password = "Local test password (not for production)"
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {
            "ADMIN_PASSWORD": password, "DATABASE_PATH": str(Path(temp) / "test.db"),
            "DISCORD_USER_TOKEN": "", "MATRIX_ACCESS_TOKEN": "", "META_AS_TOKEN_FILE": str(Path(temp) / "hook"),
        }):
            Path(temp, "hook").write_text("test-hook-secret")
            with TestClient(app, base_url=PUBLIC_ORIGIN) as client:
                self.assertEqual(client.get("/api/messages").status_code, 401)
                self.assertEqual(client.get("/static/dashboard.html").status_code, 404)
                self.assertEqual(client.post("/api/login", json={"password": password}).status_code, 403)
                login = client.post("/api/login", headers=ORIGIN, json={"password": password})
                self.assertEqual(login.status_code, 200)
                self.assertIn("HttpOnly", login.headers["set-cookie"])
                self.assertIn("SameSite=strict", login.headers["set-cookie"])
                self.assertEqual(client.put("/api/automatic", headers=ORIGIN, json={"automatic": False}).status_code, 200)
                data = client.get("/api/settings").json()
                self.assertFalse(data["automatic"])
                bad = client.put("/api/settings", headers=ORIGIN, json=data | {"morning_cron": "bad"})
                self.assertEqual(bad.status_code, 422)
                self.assertEqual(client.put("/api/settings", headers=ORIGIN, json=data | {"discord_rooms": [CHANNEL]}).status_code, 200)
                server_id = "987654321098765432"
                self.assertEqual(client.put("/api/settings", headers=ORIGIN, json=data | {"discord_servers": ["invalid"]}).status_code, 422)
                self.assertEqual(client.put("/api/settings", headers=ORIGIN, json=data | {"discord_servers": [server_id]}).status_code, 200)
                self.assertEqual(client.get("/api/settings").json()["discord_servers"], [server_id])
                self.assertEqual(client.get("/api/messages?q=%25").json(), [])
                job = client.post("/api/summarize", headers=ORIGIN, json={})
                self.assertEqual(job.status_code, 202)
                self.assertGreater(job.json()["id"], 0)
                hook = {"state_event": "CONNECTED", "remote_id": "test"}
                self.assertEqual(client.post("/internal/meta-status", json=hook).status_code, 403)
                self.assertEqual(client.post("/internal/meta-status", headers={"Authorization": "Bearer test-hook-secret"}, json=hook).status_code, 204)
                self.assertEqual(client.get("/api/overview").json()["services"]["meta"], "CONNECTED")
                self.assertEqual(client.post("/api/logout", headers=ORIGIN, json={}).status_code, 200)
                self.assertEqual(client.get("/api/overview").status_code, 401)
