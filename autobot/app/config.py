import os
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from croniter import croniter
from pydantic import BaseModel, Field, field_validator


def env(name, default=""):
    return os.getenv(name, default).strip()


def ai_origin(url):
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.query or parsed.fragment or any(ch.isspace() or ch == "\\" for ch in url)):
        raise ValueError("URL AI phải là HTTPS, không có thông tin đăng nhập, query hoặc fragment.")
    port = parsed.port
    host = parsed.hostname.lower()
    return "https://" + (f"[{host}]" if ":" in host else host) + (f":{port}" if port not in (None, 443) else "")


def default_ai_url():
    return env("OPENAI_BASE_URL", "https://api.openai.com/v1")


class Settings(BaseModel):
    automatic: bool = True
    discord_servers: list[str] = Field(default_factory=list, max_length=200)
    discord_rooms: list[str] = Field(default_factory=list, max_length=200)
    discord_ignore: list[str] = Field(default_factory=list, max_length=200)
    matrix_rooms: list[str] = Field(default_factory=list, max_length=200)
    matrix_ignore: list[str] = Field(default_factory=list, max_length=200)
    system_prompt: str = Field(default="Ưu tiên hạn chót, câu hỏi trực tiếp, thay đổi lịch và việc cần phản hồi.", max_length=4000)
    interval_minutes: int = Field(default=120, ge=5, le=1440)
    morning_cron: str = Field(default="30 7 * * *", max_length=80)
    base_url: str = Field(default_factory=default_ai_url, min_length=8, max_length=500)
    model: str = Field(default_factory=lambda: env("OPENAI_MODEL", "gpt-4o-mini"), min_length=1, max_length=160)

    @field_validator("discord_servers", "discord_rooms", "discord_ignore")
    @classmethod
    def discord_ids(cls, items):
        if any(not item.isascii() or not item.isdecimal() or not 15 <= len(item) <= 22 for item in items):
            raise ValueError("Discord ID phải gồm 15–22 chữ số.")
        return sorted(set(items))

    @field_validator("matrix_rooms", "matrix_ignore")
    @classmethod
    def matrix_ids(cls, items):
        if any(not item.startswith("!") or not 2 <= len(item) <= 255 or any(c.isspace() for c in item) for item in items):
            raise ValueError("Matrix Room ID phải bắt đầu bằng !; không dùng tên hoặc alias #.")
        return sorted(set(items))

    @field_validator("morning_cron")
    @classmethod
    def cron(cls, cron):
        if len(cron.split()) != 5 or not croniter.is_valid(cron) or any(not c.isascii() for c in cron):
            raise ValueError("Lịch tổng hợp cần cron hợp lệ gồm 5 trường.")
        return cron

    @field_validator("base_url")
    @classmethod
    def approved_url(cls, url):
        allowed = {ai_origin(default_ai_url())} | {ai_origin(item.strip()) for item in env("OPENAI_ALLOWED_ORIGINS").split(",") if item.strip()}
        if ai_origin(url) not in allowed:
            raise ValueError("Origin chưa có trong OPENAI_ALLOWED_ORIGINS trên server.")
        return url.rstrip("/")

    def allows(self, platform, room, server_id=None, parent_id=None):
        if platform == "discord":
            return (room not in self.discord_ignore and parent_id not in self.discord_ignore
                    and (room in self.discord_rooms or server_id in self.discord_servers))
        return room in self.matrix_rooms and room not in self.matrix_ignore


def timezone():
    return ZoneInfo(env("APP_TIMEZONE", "Asia/Ho_Chi_Minh"))
