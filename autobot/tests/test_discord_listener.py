import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call, patch

import discord

from app.config import Settings
from app.discord_listener import run_discord


class DiscordListenerTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_collects_whitelisted_guild_text_and_stops_on_rejected_login(self):
        allowed = "123456789012345678"
        ignored = "123456789012345679"
        server, other, thread = "123456789012345680", "123456789012345681", "123456789012345682"
        db = SimpleNamespace(settings=Settings(discord_servers=[server], discord_rooms=[allowed, ignored],
                                               discord_ignore=[ignored]), ingest=AsyncMock())
        health = {}
        callbacks = {}
        client = MagicMock()

        def register(callback):
            callbacks[callback.__name__] = callback
            return callback

        async def start(token):
            self.assertEqual(token, "mock-token")
            await callbacks["on_ready"]()
            self.assertEqual(health["discord"], "ready")
            message = dict(id=1, guild=SimpleNamespace(id=int(other)), channel=SimpleNamespace(id=int(allowed)), content="Lịch sáng mai",
                           author=SimpleNamespace(bot=False, display_name="An"), webhook_id=None,
                           created_at=datetime.fromtimestamp(100, timezone.utc))
            tracked = SimpleNamespace(id=int(server))
            for override in ({}, {"id": 2, "guild": tracked, "channel": SimpleNamespace(id=int(thread), parent_id=int(allowed))},
                             {"guild": tracked, "channel": SimpleNamespace(id=int(thread), parent_id=int(ignored))},
                             {"channel": SimpleNamespace(id=int(thread))}, {"guild": None},
                             {"guild": tracked, "channel": SimpleNamespace(id=int(ignored))}, {"content": " "},
                             {"author": SimpleNamespace(bot=True)}, {"webhook_id": 42}):
                await callbacks["on_message"](SimpleNamespace(**(message | override)))
            raise discord.LoginFailure("test rejection")

        client.event.side_effect = register
        client.start = AsyncMock(side_effect=start)
        with patch("app.discord_listener.discord.Client", return_value=client) as factory:
            await run_discord(db, "mock-token", health)
        factory.assert_called_once()
        self.assertEqual(db.ingest.await_args_list, [
            call([("discord", "1", allowed, "An", "Lịch sáng mai", 100)], server_id=other, parent_id=None),
            call([("discord", "2", thread, "An", "Lịch sáng mai", 100)], server_id=server, parent_id=allowed),
        ])
        self.assertEqual(health["discord"], "error")

    async def test_names_channels_threads_and_old_rows(self):
        from app.database import Database
        from app.discord_listener import name_old_rows, place

        general = SimpleNamespace(name="chung")
        thread = SimpleNamespace(name="Kế hoạch", parent=general)
        self.assertEqual(place(general), "#chung")
        self.assertEqual(place(thread), "#chung › Kế hoạch")
        self.assertIsNone(place(SimpleNamespace(id=1)))
        db = Database()
        await db.open(":memory:")
        self.addAsyncCleanup(db.conn.close)
        room, gone = "123456789012345678", "123456789012345679"
        await db.save_settings(Settings(discord_rooms=[room, gone]))
        await db.ingest([("discord", "1", room, "An", "a", 1), ("discord", "2", room, "Bình · #cũ", "b", 1),
                         ("discord", "3", gone, "Chi", "c", 1)])
        async def fetch(cid):
            raise discord.NotFound(MagicMock(status=404), "gone")
        client = SimpleNamespace(get_channel=lambda cid: thread if str(cid) == room else None, fetch_channel=fetch)
        await name_old_rows(db, client)
        self.assertEqual([r["author"] for r in await db.rows("SELECT author FROM messages ORDER BY external_id")],
                         ["An · #chung › Kế hoạch", "Bình · #cũ", "Chi"])
