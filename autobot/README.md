# AutoBot

AutoBot gom tin nhắn văn bản Discord và Messenger vào SQLite, tạo bản tin AI tiếng Việt, lưu trên dashboard **https://autobot.example.com** và gửi qua Facebook Page Messenger khi còn trong cửa sổ nhắn tin của Meta. Một tiến trình FastAPI phục vụ giao diện, API, Discord Gateway, Matrix sync và scheduler; không cần Node.js để build hoặc deploy.

```text
autobot/
├── .env.example, .gitignore, .dockerignore
├── Dockerfile, docker-compose.yml, requirements.txt
├── app/
│   ├── config.py, database.py, ai.py, page_chat.py, page_delivery.py
│   ├── discord_listener.py, messenger_bridge.py, summarizer.py, web_app.py
│   ├── dashboard.html, login.html
│   └── static/                 # style.css, dashboard.js, login.js
├── deploy/
│   ├── configure_matrix.py, profiles.env
│   └── autobot.service, cloudflared.yml
└── tests/                      # unittest; không cần token thật
```

## 1. Cài trên Ubuntu

Chép **nội dung thư mục `autobot/`**, gồm các dotfile, vào `/opt/autobot`. Chạy lệnh dưới đây trong shell có quyền quản lý Docker (dùng `sudo` nếu cần; quyền Docker tương đương root). Dùng Docker Engine từ 28 trở lên để tránh các vấn đề phân lập loopback đã biết ở phiên bản cũ.

```bash
cd /opt/autobot
umask 077
cp -n .env.example .env
install -d -m 0700 runtime runtime/synapse runtime/mautrix runtime/status
chmod 600 .env
openssl rand -hex 32
```

Đặt chuỗi ngẫu nhiên trên làm `ADMIN_PASSWORD` trong `.env` bằng trình soạn thảo trên server. Các giá trị bí mật để trống trong mẫu là thông tin bạn tự cấp; đừng commit `.env`, dùng `set -x`, hoặc chia sẻ đầu ra đầy đủ của `docker compose config` (có thể in secrets). Nếu giá trị chứa `$` hoặc `#`, dùng nháy đơn theo cú pháp Compose `.env`.

- **Discord (tùy chọn):** Listener dùng `DISCORD_USER_TOKEN` của chính tài khoản bạn, không dùng Bot Token hoặc Message Content Intent. Chỉ thu tin ở kênh máy chủ mà tài khoản đã được phép xem, và chỉ lưu các Channel ID trong whitelist. Bật Developer Mode trong Discord, chọn **Copy Channel ID** (thread có ID riêng) và nhập trên dashboard. Listener không gửi tin, không thu DM, bot, webhook, file đính kèm hoặc lịch sử lúc ngắt kết nối. [Discord không cho phép self-bot và có thể khóa tài khoản](https://support.discord.com/hc/en-us/articles/115002192352-Automated-User-Accounts-Self-Bots). Token là bí mật cấp phiên, không được giới hạn theo whitelist; không chia sẻ token, giữ `.env` riêng tư, và để trống biến nếu không muốn chấp nhận rủi ro. Khi nâng cấp, bỏ cấu hình token bot cũ và rebuild image. Không cài `discord.py` và `discord.py-self` chung một môi trường Python vì cả hai cùng cung cấp module `discord`.
- **AI:** Đặt `OPENAI_BASE_URL` là base URL HTTPS của nhà cung cấp (thường kết thúc bằng `/v1`, không gồm `/chat/completions`), `OPENAI_MODEL` và `OPENAI_API_KEY`. Endpoint phải hỗ trợ `POST /chat/completions`, trả JSON hoặc khối `json` trong `choices[0].message.content`. Web được chỉnh path/model và đổi origin trong danh sách `OPENAI_ALLOWED_ORIGINS` (các origin HTTPS cách nhau bằng dấu phẩy). Chỉ thêm origin đáng tin: chúng nhận cùng API key và nội dung tin nhắn. Nếu dùng CA riêng, thêm CA tin cậy vào image; không tắt TLS hoặc tự chuyển hướng request.

```bash
docker compose config --quiet
docker compose build autobot
docker compose up -d autobot
curl -fsS http://127.0.0.1:8080/healthz
```

**Theo dõi cả server Discord:** Sau khi bật Developer Mode, bấm chuột phải vào biểu tượng server → **Copy Server ID**. Dán ID vào **Cấu hình → Discord · Server IDs theo dõi** và bấm **Lưu cấu hình**. Không cần liệt kê từng Channel ID hoặc khởi động lại sau khi lưu. Bạn vẫn có thể theo dõi riêng kênh ở server khác. Thêm Channel ID hoặc Thread ID vào danh sách bỏ qua để loại trừ; bỏ qua kênh cha cũng loại các thread của kênh đó. Chỉ thêm server mà bạn được phép thu thập nội dung. Chỉ thu tin mới; lịch sử đã lưu không bị xóa, và tin cũ chưa có Server ID chỉ được truy vấn qua whitelist Channel ID.

## 2. Messenger: Synapse riêng + mautrix-meta

Chạy đoạn sau **một lần** cho cài mới. Với `sudo docker`, dùng nhất quán ở các lệnh. `runtime/mautrix` giữ session Meta; `runtime/synapse` giữ phòng/tin nhắn Matrix. AutoBot không đọc file DB của bridge. Synapse chạy SQLite cho triển khai cá nhân, mautrix-meta chạy SQLite riêng; nếu triển khai nhiều tài khoản hoặc tăng tải, chuyển Synapse sang PostgreSQL theo hướng dẫn upstream. Không chia sẻ các thư mục này giữa nhiều instance.

```bash
cd /opt/autobot
docker compose --profile messenger pull synapse mautrix-meta
docker compose --profile messenger run --rm --no-deps synapse generate
docker compose --profile messenger run --rm --no-deps mautrix-meta
docker compose run --rm --no-deps --user 0:0 --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
  -v "$PWD/runtime:/setup" autobot python deploy/configure_matrix.py configure
docker compose --profile messenger run --rm --no-deps mautrix-meta
docker compose run --rm --no-deps --user 0:0 --cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER \
  -v "$PWD/runtime:/setup" autobot python deploy/configure_matrix.py register
docker compose --profile messenger up -d
curl -fsS http://127.0.0.1:8008/_matrix/client/versions
```

Hai lần chạy `mautrix-meta` ở trên lần lượt sinh `config.yaml` và `registration.yaml`, rồi thoát. Nếu dùng Docker Compose cũ chưa có `run --cap-add`, nâng cấp plugin Compose trước. Script ghi appservice registration vào Synapse, cấp quyền chỉ đọc cho file token webhook nội bộ. `MATRIX_DOMAIN` mặc định là `matrix.autobot.internal` và **không cần DNS công khai**; không đổi sau khi tạo tài khoản.

### Tạo tài khoản Matrix và đăng nhập Meta

1. Tạo hai tài khoản Matrix cục bộ **không phải admin**. Lệnh hỏi mật khẩu qua prompt; dùng hai mật khẩu riêng, dài và ngẫu nhiên.

   ```bash
   docker compose --profile messenger exec synapse register_new_matrix_user -c /data/homeserver.yaml -u bridgeowner --no-admin http://127.0.0.1:8008
   docker compose --profile messenger exec synapse register_new_matrix_user -c /data/homeserver.yaml -u autobot-reader --no-admin http://127.0.0.1:8008
   ```

2. Từ máy cá nhân, dùng SSH port forwarding (nếu SSH dùng alias, nhập alias vào prompt). Dùng ứng dụng Matrix desktop mà bạn tin cậy có hỗ trợ homeserver tùy chỉnh và loopback HTTP, chẳng hạn Element Desktop; chọn **Other homeserver** `http://127.0.0.1:18008`. Không publish Synapse qua Tunnel.

   ```bash
   read -rp 'SSH host/alias của Ubuntu: ' SSH_HOST
   ssh -N -L 127.0.0.1:18008:127.0.0.1:8008 "$SSH_HOST"
   ```

3. Đăng nhập Matrix bằng `bridgeowner`. Mở **phòng quản lý riêng**, chỉ có bạn và `@facebookbot:matrix.autobot.internal`. Trong phòng quản lý này gửi `login messenger` và chờ bot yêu cầu cookie. Đây là lệnh Matrix, **không gửi vào phòng Messenger đã bridge**. Dùng chính tài khoản Meta của bạn, đã bật 2FA.
4. Mở cửa sổ riêng tư trên **máy cá nhân**, vào `https://www.messenger.com/`, đăng nhập bình thường. Trong DevTools → **Network** → **Fetch/XHR**, lọc `graphql`. Chọn một request tới đúng website Meta đã đăng nhập, bấm **Copy → Copy as cURL (POSIX)** hoặc Firefox **Copy as cURL**. Nếu đang dùng luồng `login facebook`, làm tương tự trên `https://www.facebook.com/`. **Không chạy lệnh cURL này**, không dán vào terminal, dashboard, dịch vụ paste hay gửi cho người khác. Dán trực tiếp vào đúng phòng quản lý riêng để bot phân tích theo [tài liệu xác thực mautrix](https://docs.mau.fi/bridges/go/meta/authentication.html). Cookie cấp quyền như phiên đăng nhập; nếu clipboard đồng bộ lên cloud thì tắt trước. Chỉ dùng cách này trên Synapse và máy mình tin cậy.
5. Sau khi bot xác nhận, xóa/redact tin cookie nếu còn hiển thị, xóa clipboard, đóng cửa sổ riêng tư. Redact **không bảo đảm** xóa khỏi backup/cơ sở dữ liệu. Nếu Meta yêu cầu checkpoint, xử lý trong ứng dụng/trang Meta chính thức; không lặp login tự động. Thu hồi phiên Meta nếu nghi lộ. Không bảo đảm tài khoản không bị checkpoint, kể cả khi chỉ thu thập. Nếu phòng quản lý bật mã hóa Matrix, bridge này không đọc được; dùng phòng quản lý riêng **không mã hóa** trên Synapse cục bộ đã cách ly.
6. Từ tài khoản `bridgeowner` trong Matrix, mời `@autobot-reader:matrix.autobot.internal` vào **chỉ các portal bạn được phép thu thập**. Không mời vào phòng quản lý. Dùng phiên đăng nhập Matrix khác của reader để chấp nhận lời mời. Trong Room Settings → Advanced lấy Room ID bắt đầu bằng `!`, dán vào danh sách Messenger trên dashboard. Reader không cần quyền quản trị phòng; không cấp quyền bridge, không sử dụng reader để gửi tin. Đừng gửi tin, typing, reaction hoặc read receipt từ client Matrix vào các portal; sau khi cấu hình xong đóng các client Matrix. `ephemeral_events=false` tắt chuyển tiếp typing/receipt từ Synapse qua appservice; nếu rebuild registration hãy giữ giá trị này.

Lấy access token bằng Python trên Ubuntu; script hỏi mật khẩu reader không hiện trên terminal, chỉ in token cho người vận hành. Dán vào `MATRIX_ACCESS_TOKEN` trong `.env`, rồi xóa clipboard. Nếu đăng xuất **thiết bị tạo token này** thì token sẽ hết hiệu lực; đây là thiết bị độc lập với phiên desktop dùng chấp nhận lời mời.

```bash
python3 - <<'PY'
import getpass, json, urllib.request
payload = json.dumps({
    'type': 'm.login.password',
    'identifier': {'type': 'm.id.user', 'user': 'autobot-reader'},
    'password': getpass.getpass('Mật khẩu Matrix reader: '),
    'initial_device_display_name': 'AutoBot ingest',
}).encode()
req = urllib.request.Request('http://127.0.0.1:8008/_matrix/client/v3/login', data=payload,
                             headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(req, timeout=15) as response:
    print(json.load(response)['access_token'])
PY
docker compose --profile messenger up -d --force-recreate autobot
docker compose --profile messenger restart mautrix-meta
```

Đợi **tin nhắn văn bản mới** gửi từ phía Messenger/Meta, không phải từ Matrix. Sync đầu tiên lấy cursor và bỏ snapshot lịch sử. Không đọc ciphertext của phòng Matrix mã hóa, không lấy attachment, reaction, edit hay tin đã xóa. `encryption.allow=false` là phía **Matrix**; bridge có thể giải mã tin đến từ **Meta** nếu phiên hợp lệ và Meta cho phép. AutoBot không tự vượt PIN, không khôi phục lịch sử mã hóa, không có mã gửi tin, đánh dấu đã đọc hay sửa dữ liệu trên Messenger. mautrix-meta upstream vẫn có khả năng gửi nếu người vận hành dùng client Matrix để nhập tin vào portal; đây không phải lớp sandbox chính sách của Meta.

## 3. Cloudflare Tunnel và systemd

Không dùng Nginx/Certbot ở phương án này. Cloudflare cấp HTTPS ở edge; cloudflared chạy **trên Ubuntu host** và kết nối `127.0.0.1:8080`, không mở 80/443 inbound. Giữ outbound Cloudflare Tunnel (7844 TCP/UDP) và outbound HTTPS cho các upstream. Cài `cloudflared` bằng [gói Cloudflare cho Ubuntu](https://pkg.cloudflare.com/). Đăng nhập từ một tài khoản có quyền quản lý zone domain của bạn.

```bash
cd /opt/autobot
cloudflared tunnel login
cloudflared tunnel create autobot
cloudflared tunnel route dns autobot autobot.example.com
read -rp 'UUID do cloudflared tunnel create in ra: ' TUNNEL_ID
sudo install -d -m 0750 /etc/cloudflared
sudo install -m 0600 "$HOME/.cloudflared/$TUNNEL_ID.json" "/etc/cloudflared/$TUNNEL_ID.json"
{ printf 'tunnel: %s\ncredentials-file: /etc/cloudflared/%s.json\n' "$TUNNEL_ID" "$TUNNEL_ID"; cat deploy/cloudflared.yml; } \
  | sudo tee /etc/cloudflared/config.yml >/dev/null
sudo chmod 600 /etc/cloudflared/config.yml
sudo cloudflared tunnel --config /etc/cloudflared/config.yml ingress validate
sudo cloudflared --config /etc/cloudflared/config.yml service install
sudo systemctl enable --now cloudflared
```

Nếu đã có record `autobot`, kiểm tra trước khi xóa record cũ rồi chạy lại `route dns`. Không copy `cert.pem` quản trị zone vào thư mục app. Kiểm tra rule `/internal` không đi qua Tunnel. Đảm bảo Cloudflare không có Cache Rule ép cache hostname này. **Khuyến nghị Cloudflare Access:** Zero Trust → Access → Applications → Add application → Self-hosted → `autobot.example.com`; tạo policy Allow chỉ email/nhóm của bạn, không để Bypass cho Everyone. Giữ cả session login của AutoBot.

```bash
sudo install -m 0644 deploy/autobot.service /etc/systemd/system/autobot.service
sudo systemctl daemon-reload
sudo systemctl enable --now autobot
docker compose --profile messenger ps
```

Nếu không cài Messenger, sửa `/opt/autobot/deploy/profiles.env` thành `COMPOSE_PROFILES=` trước khi enable systemd. Compose quản lý restart container; chỉ chạy một worker Uvicorn và một replica AutoBot. Khi đổi `.env`, chạy `sudo systemctl restart autobot`; nếu dùng Messenger, restart thêm bridge khi cần phát lại trạng thái Meta. Với cấu hình trong web, không cần restart.

`OPENAI_BASE_URL` và `OPENAI_MODEL` trong `.env` là giá trị mặc định trước khi lưu cấu hình lần đầu. Sau khi lưu, SQLite giữ giá trị đã chọn; muốn đổi endpoint sang origin mới, cập nhật allowlist ở `.env`, restart rồi đổi URL trong dashboard. Giữ origin đang dùng trong allowlist đến khi chuyển xong.

## 4. Chat hai chiều qua Facebook Page (tùy chọn)

Đây là **Facebook Page + Graph API chính thức**, độc lập với mautrix-meta. Không dùng cookie Meta, token Matrix hay tài khoản cá nhân làm danh tính gửi. Nếu để trống các biến `FB_*` và `MY_FB_PSID`, tính năng trả lời không chạy. Nên dùng một Page dành riêng cho trợ lý; Page chỉ phản hồi tài khoản đã cấu hình.

1. Trong [Meta for Developers](https://developers.facebook.com/apps/), tạo/chọn app hỗ trợ **Messenger Platform**, kết nối Page do bạn quản lý. Trong Messenger → Settings / API Setup, tạo **Page Access Token** cho Page đó (`pages_messaging`) và lưu vào `FB_PAGE_ACCESS_TOKEN`. Dùng **Page ID** hoặc lấy ID bằng `GET /me?fields=id,name` với token của Page, lưu vào `FB_PAGE_ID`. Lấy `FB_APP_SECRET` từ **App Settings → Basic → App Secret**. Với tài khoản không có vai trò app, Meta có thể yêu cầu Live mode, Advanced Access và App Review; đối với bot một người, thử trước bằng tài khoản có vai trò phù hợp trên app và Page.
2. Dùng `openssl rand -hex 32` để **tự tạo** `FB_VERIFY_TOKEN`. Điền vào `.env` và áp dụng bản build mới:

   ```bash
   cd /opt/autobot
   docker compose up -d --build autobot
   ```

3. Nếu bật **Cloudflare Access**, tạo một application cụ thể hơn cho `autobot.example.com/webhook/messenger`, với policy **Bypass chỉ trên đường dẫn webhook**. Meta không thể đăng nhập Access. Giữ policy Allow riêng cho dashboard, tránh Bypass cả hostname và không mở `/internal`. Đảm bảo không có Worker/WAF bắt challenge trình duyệt hoặc thay đổi byte payload ở đường dẫn webhook; không ghi log query `hub.verify_token` hay body chứa tin nhắn vào Cloudflare/observability nếu bạn đã bật các dịch vụ đó.
4. Trong Messenger → Webhooks, nhập callback **`https://autobot.example.com/webhook/messenger`** và Verify Token giống `.env`. Subscribe field **`messages`** ở object **Page**, rồi subscribe app cho đúng Page trong phần Page subscriptions (Meta yêu cầu `pages_manage_metadata` nếu đăng ký qua Graph API). GET xác minh vẫn hoạt động trước khi bạn có PSID; POST có chữ ký hợp lệ được ACK nhưng không xử lý câu hỏi khi chưa có PSID.
5. Từ **tài khoản cá nhân** trong Messenger, gửi một câu dễ nhận ra vào Page (không gửi dưới danh tính Page). Trong [Graph API Explorer](https://developers.facebook.com/tools/explorer/), chọn đúng app và **Page Access Token**, gọi `GET /me/conversations?platform=messenger&fields=participants,messages.limit(5){from,message}`. Tìm câu vừa gửi và lấy `from.id` của **người gửi**, không lấy ID của Page hay ID profile công khai. Đó là PSID (tương ứng `sender.id` trong webhook tin đến). Nếu không thấy hội thoại, kiểm tra token/quyền, vai trò app và phân trang kết quả. Đặt `MY_FB_PSID` trong `.env` rồi chạy lại `docker compose up -d autobot`. Đừng chia sẻ token, phản hồi Graph Explorer hoặc bật log toàn bộ webhook để tìm PSID.
6. Nhắn `/status` để kiểm tra phản hồi, rồi thử **“Có tin gì quan trọng từ sáng giờ?”** hoặc **“Tìm tin nhắn nhắc tới lịch họp”**. `/tomtat` xác nhận mã lượt ngay; nếu có tin cần tóm tắt, báo cáo sẽ lưu trên dashboard và gửi qua Messenger khi còn trong cửa sổ 24 giờ. Thử nhắn từ tài khoản khác để xác nhận Page không phản hồi.

AI dùng mẫu tin mới nhất và kết quả tìm theo từ khóa trong 30 ngày, chỉ từ nguồn hiện vẫn được cho phép; không có bộ nhớ hội thoại giữa các câu hỏi. Câu hỏi và đoạn trích được gửi cho endpoint AI đã cấu hình, câu trả lời được gửi qua Meta. Chỉ bật cho nguồn bạn được phép chia sẻ theo cách này. Chỉ trả lời trong cửa sổ 24 giờ bằng `RESPONSE`; bản tin dùng `UPDATE`. Worker xóa nội dung câu hỏi sau xử lý và giữ ID chống trùng đến hết cửa sổ. Nếu Graph API lỗi, xem log `Page Chat` và gửi câu hỏi mới sau khi xử lý sự cố. Nếu Meta ngừng phiên bản `v21.0`, cập nhật `SEND_URL` trong `app/page_delivery.py` theo tài liệu Send API.

## 5. Vận hành và kiểm chứng

- Bản tin định kỳ xử lý tin chưa được tóm tắt theo khoảng cấu hình, mặc định 120 phút, tính từ đầu ngày địa phương. Báo cáo sáng mặc định `30 7 * * *`, nhắc lại các tin của 24 giờ gần nhất kể cả đã tóm tắt. Slot trùng không được xếp lại; lượt lịch bị lỡ quá 5 phút không được chạy bù. Tin chưa xử lý vẫn nằm trong hàng đợi dữ liệu cho lượt tiếp theo. Tắt tự động không hủy lượt đã xếp. Không gửi bản tin rỗng.
- Mỗi lượt chia lô khi có nhiều tin. Bản tin, cờ đã tóm tắt và tiến độ lượt được lưu cùng giao dịch SQLite trước khi gửi. Nếu AutoBot chưa nhận được tin văn bản của bạn gửi cho Page trong 24 giờ qua, hoặc Meta từ chối gửi, bản tin vẫn có trên dashboard. Không tự gửi bù khi bạn nhắn lại. Lỗi tạo báo cáo AI vẫn được thử lại sau 60 giây.
- Dashboard cập nhật theo nhịp 6 giây khi tab hiển thị. Trạng thái **Messenger Bridge** lấy từ webhook mautrix; khi chưa có sự kiện hoặc thông tin quá hạn sẽ hiện chưa có tín hiệu. **Đồng bộ Matrix** chỉ cho biết `/sync` hoạt động. Whitelist tác động đến tin mới thu thập, không xóa dữ liệu đã lưu. `is_summarized` không phản ánh dấu đã đọc ở Discord/Messenger.
- Smoke test: đăng nhập dashboard → lưu whitelist → gửi tin văn bản mẫu → đối chiếu trong **Tin nhắn** → bấm **Quét & Tóm tắt ngay** → kiểm tra báo cáo và cờ đã tóm tắt. Để thử giao bản tin, nhắn `/status` vào Page trước rồi kiểm tra Messenger sau lần quét.
- Xem lỗi với `docker compose logs --tail 100 autobot`, `docker compose --profile messenger logs --tail 100 mautrix-meta` và `journalctl -u cloudflared -n 100`. Kiểm tra log tại server; không đăng nguyên log chứa bí mật hoặc nội dung chat.
- Dữ liệu SQLite/Matrix không được ứng dụng mã hóa khi lưu. Chỉ thu nhóm có quyền, thông báo người tham gia theo chính sách của bạn, không thu nhóm dùng chia sẻ OTP/bí mật. Tin nhắn được gửi đến AI; bản tin có thể được gửi đến Meta. Dùng disk/backup mã hóa, giữ quyền quản trị Docker giới hạn và tự đặt thời hạn lưu.

Khi nâng cấp từ bản cũ, sao lưu SQLite trước. Bản mới tự chuyển schema, giữ lịch sử và lưu trạng thái gửi Messenger riêng. Chỉ giữ các biến còn dùng theo `.env.example`, rồi chạy `docker compose up -d --build autobot`.

Backup nhất quán: dừng stack, lưu `runtime/` và volume SQLite (gồm file phụ WAL nếu có), lưu `.env` riêng và mã hóa tất cả trước khi chuyển khỏi máy. Không dùng `docker compose down -v` khi còn cần dữ liệu. Backup/recovery và kiểm tra cập nhật image/dependency trước khi nâng cấp.

### Kiểm thử local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
AUTOBOT_ENV_FILE=.env.example docker compose --env-file .env.example --profile messenger config --quiet
```
