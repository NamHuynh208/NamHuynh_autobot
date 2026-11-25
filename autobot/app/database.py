import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import aiosqlite

from .config import Settings

REPORT_SCHEMA = """
CREATE TABLE IF NOT EXISTS summaries (
    id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), created INTEGER NOT NULL,
    discord_count INTEGER NOT NULL, messenger_count INTEGER NOT NULL, body TEXT NOT NULL,
    delivery TEXT NOT NULL DEFAULT 'saved'
)
"""

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, platform TEXT NOT NULL, external_id TEXT NOT NULL,
    room TEXT NOT NULL, author TEXT NOT NULL, content TEXT NOT NULL, ts INTEGER NOT NULL,
    is_summarized INTEGER NOT NULL DEFAULT 0, server_id TEXT, parent_id TEXT, UNIQUE(platform, external_id)
);
CREATE INDEX IF NOT EXISTS messages_pending ON messages(is_summarized, id);
CREATE INDEX IF NOT EXISTS messages_time ON messages(ts);
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY, slot TEXT UNIQUE, kind TEXT NOT NULL, created INTEGER NOT NULL,
    cutoff INTEGER NOT NULL, cursor INTEGER NOT NULL DEFAULT 0, state TEXT NOT NULL DEFAULT 'queued'
);
""" + REPORT_SCHEMA + ";" + """
CREATE TABLE IF NOT EXISTS page_inbox (
    mid TEXT PRIMARY KEY, page TEXT NOT NULL, sender TEXT NOT NULL, sent INTEGER NOT NULL,
    question TEXT
);
CREATE INDEX IF NOT EXISTS page_pending ON page_inbox(sent) WHERE question IS NOT NULL;
"""


class Database:
    def __init__(self):
        self.lock = asyncio.Lock()

    async def open(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = await aiosqlite.connect(path)
        self.conn.row_factory = aiosqlite.Row
        await self.conn.create_function("casefold", 1, str.casefold, deterministic=True)
        await self.conn.executescript(SCHEMA)
        columns = {column["name"] for column in await self.rows("PRAGMA table_info(messages)")}
        async with self.tx() as conn:
            for name in ("server_id", "parent_id"):
                if name not in columns:
                    await conn.execute(f"ALTER TABLE messages ADD COLUMN {name} TEXT")
        if not any(column["name"] == "delivery" for column in await self.rows("PRAGMA table_info(summaries)")):
            async with self.tx() as conn:
                # Keep existing reports, and finish local bookkeeping for any interrupted legacy batches.
                await conn.execute("ALTER TABLE summaries RENAME TO old_summaries")
                await conn.execute(REPORT_SCHEMA)
                await conn.execute("INSERT INTO summaries(id,job_id,created,discord_count,messenger_count,body) "
                                   "SELECT id,job_id,created,discord_count,messenger_count,body FROM old_summaries")
                await conn.execute("UPDATE messages SET is_summarized=1 WHERE id IN "
                                   "(SELECT value FROM old_summaries, json_each(old_summaries.message_ids))")
                await conn.execute("UPDATE jobs SET cursor=MAX(cursor, COALESCE("
                                   "(SELECT MAX(last_message) FROM old_summaries WHERE job_id=jobs.id), cursor))")
                await conn.execute("DROP TABLE old_summaries")
        saved = await self.get("settings")
        self.settings = Settings.model_validate_json(saved) if saved else Settings.model_validate({})

    async def rows(self, sql, args=()):
        async with self.lock:
            async with self.conn.execute(sql, args) as cur:
                return [dict(row) for row in await cur.fetchall()]

    async def get(self, key):
        rows = await self.rows("SELECT value FROM state WHERE key=?", (key,))
        return rows[0]["value"] if rows else None

    @asynccontextmanager
    async def tx(self):
        async with self.lock:
            try:
                yield self.conn
                await self.conn.commit()
            except BaseException:
                await self.conn.rollback()
                raise

    async def save_settings(self, settings):
        async with self.tx() as conn:
            await conn.execute("REPLACE INTO state VALUES ('settings', ?)", (settings.model_dump_json(),))
        self.settings = settings

    async def ingest(self, records, sync_token=None, *, server_id=None, parent_id=None):
        async with self.tx() as conn:
            await conn.executemany(
                "INSERT INTO messages(platform,external_id,room,author,content,ts,server_id,parent_id) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(platform,external_id) DO NOTHING",
                (row + (server_id, parent_id) for row in records if self.settings.allows(row[0], row[2], server_id, parent_id)),
            )
            if sync_token is not None:
                await conn.execute("REPLACE INTO state VALUES ('matrix_since', ?)", (sync_token,))
