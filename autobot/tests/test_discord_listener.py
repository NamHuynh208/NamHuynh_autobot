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
