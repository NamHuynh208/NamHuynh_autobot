> Cập nhật: 2026-11-26

- Đã xây dựng `autobot/`; dashboard ưu tiên báo cáo mới nhất theo lựa chọn của người dùng.
- Cloudflare Tunnel; Discord Gateway và Matrix `/sync` chỉ thu thập tin văn bản.
- Đã thêm Facebook Page chat chính thức, tách riêng mautrix; chỉ xử lý Page ID và PSID đã cấu hình.
- Gỡ kênh gửi cũ; báo cáo mới chỉ gửi Messenger khi cửa sổ của Meta còn hiệu lực.
- Listener Discord đã chuyển sang token tài khoản người dùng theo yêu cầu; không thêm mã né phát hiện. Discord có thể khóa tài khoản.
- Dashboard cho phép theo dõi Discord bằng Server ID hoặc Channel ID; bỏ qua kênh cha áp dụng cả thread.
- Còn cần người vận hành cấp token và kiểm tra Docker/Meta/Cloudflare trên Ubuntu thật.

## Deploy (2026-11-20)
- VM Ubuntu, mã nguồn ở /opt/autobot, Docker, cloudflared tunnel -> domain riêng (đã chạy).
- Dashboard + AI (endpoint tương thích OpenAI) + Facebook Page chat (/status) đã hoạt động; systemd autobot đã enable.
- Chưa bật: nguồn Discord (DISCORD_USER_TOKEN là self-bot, cố ý không điền), mautrix-meta, Cloudflare Access.
- Lưu ý: SQLite giữ base_url cũ; đổi OPENAI_BASE_URL phải sửa cả bảng state.settings.

## Messenger qua mautrix-meta (2026-11-20)
- Đăng nhập bằng luồng Facebook (cookie facebook.com/messages); luồng messenger.com lỗi "user id zero".
- Đã chọn một số phòng cần theo dõi; autobot-reader đã vào và matrix_rooms (SQLite) lưu ID phòng. COMPOSE_PROFILES=messenger.
- Synapse đã nới rc_joins/rc_invites trong runtime/synapse/homeserver.yaml.
- File danh sách phòng (tên liên hệ) giữ cục bộ, không commit.

## GitHub (2026-11-25)
- Repo public trên GitHub, nhánh main. danh-sach-phong.md, .env, runtime/ bị .gitignore.

## Tóm tắt theo nguồn + Sol (2026-11-26)
- Báo cáo mới: JSON {important, sources[{name, summary}]}; gom tin theo (platform, room), tên lấy từ author "Người · Phòng/#kênh". Dashboard vẫn đọc báo cáo cũ (urgent/important/casual).
- Discord author giờ kèm "#tên-kênh".
- Tóm tắt dùng reasoning_effort=OPENAI_REASONING_EFFORT (VM: max). Page chat: Luna trả lời, trả "__SOL__" hoặc /tuvan -> model *-sol mới nhất (/models) hoặc OPENAI_ADVISOR_MODEL, effort OPENAI_ADVISOR_EFFORT (medium); lỗi HTTP thì lùi về Luna.
- Sol (gpt-6.2-sol) đã dùng được ở mức medium (2026-11-26, sau vài lần proxy trả 404).
