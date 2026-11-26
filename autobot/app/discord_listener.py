import asyncio
import logging

import discord


async def run_discord(db, token, health):
    if not token:
        health["discord"] = "disabled"
        return
    while True:
        health["discord"] = "connecting"
        client = discord.Client(max_messages=None, chunk_guilds_at_startup=False, sync_presence=False)

        @client.event
        async def on_ready():
            health["discord"] = "ready"

        @client.event
        async def on_resumed():
            health["discord"] = "ready"

        @client.event
        async def on_disconnect():
            health["discord"] = "connecting"

        @client.event
        async def on_message(message):
            if message.guild is None or not message.content.strip() or message.author.bot or message.webhook_id:
                return
            room = str(message.channel.id)
            server_id = str(message.guild.id)
            parent = getattr(message.channel, "parent_id", None)
            parent_id = str(parent) if parent is not None else None
            if db.settings.allows("discord", room, server_id, parent_id):
                channel = getattr(message.channel, "name", None)
                author = f"{message.author.display_name} · #{channel}" if channel else message.author.display_name
                await db.ingest([("discord", str(message.id), room, author[:160],
                                  message.content[:8000], int(message.created_at.timestamp()))],
                                server_id=server_id, parent_id=parent_id)

        @client.event
        async def on_error(event, *args, **kwargs):
            logging.error("Discord: lỗi callback %s", event)
            health["discord"] = "error"

        try:
            async with client:
                await client.start(token)
        except (discord.LoginFailure, discord.Forbidden, discord.CaptchaRequired):
            health["discord"] = "error"
            logging.error("Discord: phiên không hợp lệ, bị từ chối hoặc cần xác minh; listener đã dừng.")
            return
        except discord.ConnectionClosed as exc:
            if exc.code in {4004, 4005, 4008, 4010, 4011, 4012, 4013, 4014}:
                health["discord"] = "error"
                logging.error("Discord: Gateway đóng phiên (mã %s); listener đã dừng.", exc.code)
                return
            logging.warning("Discord: Gateway đóng kết nối (mã %s); thử lại sau 30 giây.", exc.code)
        except Exception as exc:
            logging.warning("Discord: %s; thử lại sau 30 giây.", type(exc).__name__)
        health["discord"] = "error"
        await asyncio.sleep(30)
