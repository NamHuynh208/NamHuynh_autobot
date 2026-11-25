# NamHuynh_autobot

AutoBot gom tin nhắn văn bản từ **Discord** và **Messenger** vào SQLite, dùng AI (API tương thích OpenAI) để tạo bản tin tóm tắt tiếng Việt theo lịch, hiển thị trên dashboard web và gửi báo cáo qua **Facebook Page Messenger**.

## Tính năng

- Thu thập tin nhắn Discord (lọc theo Server ID / Channel ID, hỗ trợ danh sách bỏ qua).
- Thu thập tin nhắn Messenger qua Synapse + mautrix-meta (profile Compose `messenger`, tùy chọn).
- Tóm tắt bằng AI theo lịch, lưu lịch sử báo cáo trong SQLite.
- Dashboard web (FastAPI + HTML/CSS/JS thuần, không cần build Node) có đăng nhập admin.
- Chat với Facebook Page: hỏi đáp trên dữ liệu đã thu, lệnh nhanh như `/tomtat`, `/status`.
- Deploy bằng Docker Compose + systemd + Cloudflare Tunnel.

## Cấu trúc

```text
.
├── autobot/            # Mã nguồn chính (xem autobot/README.md để cài đặt chi tiết)
│   ├── app/            # FastAPI, listener Discord/Matrix, AI, dashboard
│   ├── deploy/         # systemd, Cloudflare Tunnel, bootstrap Matrix
│   ├── tests/          # unittest, không cần token thật
│   ├── .env.example    # Mẫu biến môi trường
│   └── docker-compose.yml, Dockerfile, requirements.txt
├── memory/             # Ghi chú tiến độ dự án
└── DESIGN.md, PRODUCT.md
```

## Bắt đầu nhanh

```bash
cd autobot
cp .env.example .env      # điền ADMIN_PASSWORD, OPENAI_API_KEY, token... (KHÔNG commit .env)
docker compose up -d autobot
curl -fsS http://127.0.0.1:8080/healthz
```

Chạy test:

```bash
cd autobot
python -m unittest discover tests
```

Hướng dẫn đầy đủ (Messenger bridge, Facebook Page webhook, Cloudflare Tunnel, systemd): [autobot/README.md](autobot/README.md).

## Bảo mật

- Mọi bí mật nằm trong `autobot/.env` (đã bị `.gitignore`); repo chỉ chứa `autobot/.env.example` với giá trị trống.
- `runtime/` và `data/` (session Meta, DB Synapse, SQLite) không được commit.
- `DISCORD_USER_TOKEN` là token tài khoản cá nhân (self-bot) — vi phạm điều khoản Discord và có thể bị khóa tài khoản; để trống nếu không chấp nhận rủi ro.
