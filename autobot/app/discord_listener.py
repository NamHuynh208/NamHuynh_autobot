import asyncio
import logging

import discord


def place(channel):
    """'#kênh', or '#kênh › chủ đề' for a thread or forum post."""
    name = getattr(channel, "name", None)
    if not name:
        return None
    parent = getattr(getattr(channel, "parent", None), "name", None)
    return f"#{parent} › {name}" if parent else f"#{name}"


async def name_old_rows(db, client):
    # Rows stored before channel names were recorded. Cache first; one fetch per still-unnamed room
    # (archived threads are not cached), so this costs nothing once every room is named.
    rows = await db.rows("SELECT DISTINCT room FROM messages WHERE platform='discord' AND instr(author,' · ')=0")
    updates = []
    for row in rows:
        channel = client.get_channel(int(row["room"]))
        if channel is None:
            try:
                channel = await client.fetch_channel(int(row["room"]))
            except Exception:
                continue
        if where := place(channel):
            updates.append((" · " + where, row["room"]))
    if updates:
        async with db.tx() as conn:
            await conn.executemany("UPDATE messages SET author=substr(author || ?,1,160) "
                                   "WHERE platform='discord' AND room=? AND instr(author,' · ')=0", updates)


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
            try:
                await name_old_rows(db, client)
            except Exception as exc:
                logging.warning("Discord: chưa đặt được tên kênh cho tin cũ (%s).", type(exc).__name__)

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
                where = place(message.channel)
                author = f"{message.author.display_name} · {where}" if where else message.author.display_name
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
