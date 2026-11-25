> Cập nhật: 2026-11-20

- `autobot/app`: Một tiến trình FastAPI phục vụ HTML/CSS/JS, Discord Gateway, Matrix Client API và scheduler.
- Discord Gateway dùng `discord.py-self` với `DISCORD_USER_TOKEN`, lọc theo Server ID hoặc Channel ID; SQLite lưu server/kênh cha để áp dụng bộ lọc cho hỏi đáp.
- SQLite WAL trên volume; báo cáo và tiến độ được lưu trước khi thử gửi qua Graph API trong cửa sổ 24 giờ.
- Profile Compose `messenger`: mautrix-meta và Synapse dùng DB riêng. AutoBot xác thực webhook trạng thái Meta độc lập với `/sync`.
- Webhook Facebook Page ký HMAC và lọc Page/PSID, nhận nhanh vào `page_inbox`; worker dùng cấu hình AI chung và Graph Send API, không qua mautrix.
- `autobot/deploy`: bootstrap appservice, systemd và Cloudflare Tunnel nối tới dashboard loopback Ubuntu.
