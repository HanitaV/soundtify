# 🎵 Soundtify CLI

Soundtify CLI là một ứng dụng nghe nhạc qua dòng lệnh (Command Line Interface) siêu nhẹ, được thiết kế để tiết kiệm tối đa dung lượng RAM. Nó hỗ trợ stream âm thanh trực tiếp từ nhiều nền tảng phổ biến.

## ✨ Tính năng nổi bật

*   **Siêu Nhẹ (AIO Player):** Tích hợp công nghệ tự động tải `ffplay` chạy ngầm. Không cần mở các giao diện nặng nề, chỉ cần gõ lệnh và nghe nhạc với mức RAM tiêu thụ chỉ dưới 50MB.
*   **Hỗ Trợ Đa Nền Tảng:**
    *   **YouTube Music:** Tìm kiếm và phát trực tiếp nhạc chất lượng cao.
    *   **SoundCloud:** Tìm kiếm mọi bài hát, bản mix từ cộng đồng SoundCloud.
    *   **Spotify:** Hỗ trợ tìm kiếm theo cấu trúc của Spotify (tự động mapping qua hệ thống YouTube để nghe nhạc miễn phí không cần Premium).
*   **An Toàn & Bảo Mật:** Bộ nhớ đệm (cache), file cấu hình được bảo mật và xác minh tính toàn vẹn bằng thuật toán băm `SHA-256`.

## 🚀 Hướng dẫn cài đặt & Chạy ứng dụng

Bạn có thể chạy dự án theo 2 cách:

### Cách 1: Sử dụng file chạy trực tiếp (Pre-compiled)
Ứng dụng đã được đóng gói thành file `.exe` độc lập. Bạn không cần cài đặt Python hay bất kỳ phần mềm lập trình nào.
1. Tải file `soundtify.exe` ở phần Release.
2. Mở Terminal (PowerShell/CMD) và chạy file, hoặc đơn giản là nhấp đúp (Double-click) vào file.

### Cách 2: Chạy từ mã nguồn (Dành cho Developer)
1. Yêu cầu hệ thống đã cài đặt Python 3.10+.
2. Clone repository và cài đặt thư viện cần thiết:
   ```bash
   pip install -r requirements.txt
   ```
3. Chạy ứng dụng:
   ```bash
   python main.py
   ```
   Mặc định ứng dụng mở giao diện TUI có hỗ trợ chuột. Nếu muốn dùng giao diện lệnh cổ điển:
   ```bash
   python main.py --classic
   ```

## 📦 Tự động build & release

Repository đã có GitHub Actions tại `.github/workflows/release.yml` để tự động kiểm tra mã nguồn, compile bằng PyInstaller và đóng gói file `soundtify.exe`.

*   Khi push lên `main`/`master` hoặc mở Pull Request: workflow sẽ cài dependencies, chạy `compileall`, build `.exe` và upload artifact.
*   Khi push tag dạng `v*` như `v1.0.0`: workflow sẽ tạo GitHub Release và đính kèm file `soundtify-windows-x64.zip`.
*   Có thể chạy thủ công trong tab **Actions** bằng `workflow_dispatch`; nhập version/tag như `v1.0.0` nếu muốn publish release.

Tạo release mới bằng tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

## 🎮 Cách sử dụng lệnh (Commands)

Khi ứng dụng chạy, mặc định bạn sẽ thấy giao diện Home kiểu SoundCloud tối giản:

*   Cột trái: Home, Trending, Recently played, Playlist, Account Manager, Help và chọn provider.
    *   Nếu màn hình nhỏ, cột trái có thể cuộn bằng chuột để xem đủ nút.
    *   Các nút luôn hiển thị chữ mô tả tác dụng thay vì chỉ icon.
*   Ô tìm kiếm phía trên: nhập bài hát, nghệ sĩ hoặc tâm trạng rồi bấm `Search`.
*   Bảng gợi ý ở giữa: click một bài để chọn, double click/Enter để phát.
*   Thanh phát phía dưới: xem bài đang phát, tác giả, giây hiện tại theo thời gian thực, tiến độ và các nút `Back`, `-15s`, `Play`, `+30s`, `Next`, `Add`, `Share URL`, `Stop`.
*   Nút `Share URL`: copy link bài đang phát hoặc bài đang chọn vào clipboard.
*   Nút `Connect provider`, `Sync library`, `Logout provider`: thao tác tài khoản bằng chuột.

Phím tắt trong giao diện mới:

*   `S`: focus vào ô tìm kiếm.
*   `Space`: phát bài đang chọn.
*   `P`: start/stop bài đang phát. Nếu đã stop bằng `P`, bấm lại `P` để phát tiếp từ vị trí đã dừng.
*   `J`: tua lùi 15 giây.
*   `K`: tua tới 15 giây.
*   `N`: bài tiếp theo.
*   `B`: bài trước.
*   `R`: về Home.
*   `Q`: thoát.

Khi thoát hoặc khi client gặp lỗi Python, ứng dụng sẽ tự dừng tiến trình `ffplay` đang phát nền để tránh nhạc tiếp tục chạy sau khi UI bị đóng.

Giao diện classic (`python main.py --classic`) vẫn dùng dấu nhắc lệnh `soundtify> ` và hỗ trợ các lệnh sau:

*   `search <từ khóa>` hoặc `s <từ khóa>`: Tìm kiếm một bài hát. Ví dụ: `search em cua ngay hom qua`.
    *   Sau khi tìm kiếm, nhập số để phát ngay.
    *   Nhập `a <số>` để thêm kết quả vào hàng chờ (queue).
    *   Nhập `p <số>` để thêm kết quả vào playlist hiện tại.
*   `provider <tên nguồn>`: Đổi nguồn nhạc. Hỗ trợ: `ytmusic`, `soundcloud`, `spotify`.
*   `now`, `status`, `home`: Hiển thị dashboard gồm bài đang phát, tiến độ, queue, playlist và tài khoản.
*   `suggest <từ khóa>` hoặc `g <từ khóa>`: Gợi ý bài hát liên quan. Nếu bỏ trống từ khóa, ứng dụng gợi ý theo bài đang phát.
*   `add <số> queue`: Thêm kết quả tìm kiếm gần nhất vào queue.
*   `add <số> pl <tên playlist>`: Thêm kết quả tìm kiếm gần nhất vào playlist. Nếu bỏ tên playlist, dùng playlist hiện tại.
*   `queue`: Xem hàng chờ phát.
*   `queue clear`: Xóa toàn bộ hàng chờ phát.
*   `queue remove <số>`: Xóa một bài khỏi hàng chờ phát.
*   `playlist` hoặc `pl`: Xem playlist hiện tại.
*   `playlist use <tên playlist>`: Chuyển hoặc tạo playlist đang dùng.
*   `playlist remove <số>`: Xóa một bài khỏi playlist hiện tại.
*   `seek <+giây|-giây|m:ss>` hoặc `tua <+giây|-giây|m:ss>`: Tua bài đang phát. Ví dụ: `seek +30`, `seek -15`, `seek 1:20`.
*   `next` hoặc `n`: Phát bài tiếp theo trong queue; nếu queue trống thì phát bài tiếp theo trong playlist.
*   `back` hoặc `b`: Quay lại bài trước trong lịch sử phát.
*   `stop`: Dừng phát bài hát hiện tại.
*   `login <ytmusic|soundcloud|spotify> <tên> [token]`: Lưu trạng thái đăng nhập local cho từng nền tảng.
*   `accounts`: Xem các tài khoản đã lưu.
*   `sync`: Đồng bộ snapshot local của queue, history và playlist vào bộ nhớ bảo mật SHA-256.
*   `logout <ytmusic|soundcloud|spotify>`: Xóa trạng thái đăng nhập local.
*   `quit`, `exit`, `q`: Thoát ứng dụng.

> Lưu ý: `login`/`sync` hiện lưu trạng thái và snapshot local an toàn bằng SHA-256. Đồng bộ remote thật với tài khoản Spotify/SoundCloud/YouTube cần credential OAuth chính thức của từng nền tảng.

## Đăng nhập OAuth và đồng bộ

Ứng dụng có thể tạo link OAuth thật nếu bạn cấu hình client credentials riêng. Tạo file bảo mật local trong thư mục dữ liệu app tên `auth_config.json`, hoặc đặt biến môi trường:

```json
{
  "spotify": {
    "client_id": "SPOTIFY_CLIENT_ID",
    "redirect_uri": "http://127.0.0.1:8765/callback"
  },
  "ytmusic": {
    "client_id": "GOOGLE_OAUTH_CLIENT_ID",
    "redirect_uri": "http://127.0.0.1:8765/callback"
  },
  "soundcloud": {
    "client_id": "SOUNDCLOUD_CLIENT_ID",
    "client_secret": "SOUNDCLOUD_CLIENT_SECRET",
    "redirect_uri": "http://127.0.0.1:8765/callback"
  }
}
```

Biến môi trường tương ứng:

*   `SOUNDTIFY_SPOTIFY_CLIENT_ID`
*   `SOUNDTIFY_GOOGLE_CLIENT_ID`
*   `SOUNDTIFY_SOUNDCLOUD_CLIENT_ID`
*   `SOUNDTIFY_SOUNDCLOUD_CLIENT_SECRET`

Cách dùng trong TUI:

1. Chọn provider ở sidebar.
2. Mở tab `Account Manager` để xem tài khoản đã liên kết, trạng thái pending, token và lần sync gần nhất.
3. Trong `Account Manager`, chọn một dòng tài khoản rồi bấm Enter/click để mở menu hành động.
4. Menu hành động có `Login / Connect`, `Sync now`, `Disconnect`, `Setup guide`, `Back to Account Manager`.
5. Nếu bấm provider ở sidebar khi đang ở `Account Manager`, app cũng mở menu hành động cho provider đó.
6. `Setup guide` tự mở `http://127.0.0.1:8766/?provider=<provider>` trong trình duyệt.
7. Trang setup local có input `client_id`, `client_secret`, `redirect_uri`; bấm Save sẽ ghi vào `auth_config.json` trong app data, không cần nhập biến môi trường thủ công.
8. `Login / Connect` sẽ mở trình duyệt, copy login URL vào clipboard và chạy callback listener local.
9. Nếu redirect URI là `http://127.0.0.1:8765/callback` và đã được đăng ký trong app dashboard, Soundtify sẽ tự nhận callback và lưu token.
10. Nếu provider không redirect được về loopback, copy callback URL hoặc riêng giá trị `code`, paste vào ô Search rồi chọn `Login / Connect` lần nữa.
11. `Sync now` lưu snapshot queue/history/playlist vào tài khoản đã kết nối.

Spotify dùng Authorization Code with PKCE. Google dùng OAuth desktop/installed app với YouTube Data API scopes. SoundCloud dùng OAuth 2.1/PKCE và hiện vẫn cần `client_secret` để đổi token.

## 📁 Cấu trúc thư mục

*   `src/ui/`: Xử lý giao diện CLI tương tác (Rich, prompt_toolkit).
*   `src/core/`: Logic mã hóa bảo mật cache (`security.py`) và điều khiển stream nhạc ngầm (`player.py`).
*   `src/providers/`: Chứa các module tương tác API nguồn nhạc (YT Music, SoundCloud, Spotify).
*   `main.py`: Tệp khởi chạy chính.
*   `requirements.txt`: Danh sách các thư viện phụ thuộc.

---
*Dự án được xây dựng bằng phong cách "Vibe Coding" với giao diện CLI tối giản và hiệu quả.*
