# AutoBot · Design

## Direction

Dashboard vận hành tiếng Việt, ưu tiên báo cáo mới nhất. Thanh điều hướng ngắn, nội dung trắng, cột trạng thái nền lam nhạt. Báo cáo giữ cùng thứ tự và nhãn ưu tiên trong khung mới nhất và lịch sử. Không dùng font CDN, ảnh hoặc thư viện giao diện.

## Tokens

| Vai trò | Giá trị |
| --- | --- |
| Chữ chính | `#15233a` |
| Chữ phụ | `#50627a` |
| Viền | `#dce4ef` |
| Điều khiển / focus | `#254cbd` |
| Điều khiển hover | `#1b3995` |
| Nền vận hành | `#f2f6fd` |
| Nền nội dung | `#ffffff` |
| Khẩn cấp | `#9b2944` |
| Bo góc nút / panel | `7px` / `12px` |
| Nút / trường nhập | tối thiểu `44px` |
| Ngắt bố cục | `700px` |

Ngăn giữa các nhóm tin bằng đường kẻ, không chỉ bằng màu. Desktop đọc báo cáo và trạng thái song song; điện thoại đọc báo cáo trước, bảng tin nhắn đổi thành các hàng xếp dọc. Dùng focus outline rõ, tab có `aria-current`, toàn bộ dữ liệu tin nhắn được gắn dưới dạng văn bản thuần.

## Review

Đã xem ảnh kết xuất Chromium 1440px và 390px với dữ liệu mẫu. Đã kiểm thử đăng nhập, mở báo cáo, chuyển tab, tin nhắn dài, lưu cấu hình, kích hoạt thủ công và đăng xuất. Việc hiển thị dữ liệu production phụ thuộc các tích hợp được cấu hình trên Ubuntu.
