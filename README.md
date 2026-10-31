# Super Net · Content Marketing

Website tiếng Việt để quản lý nhân viên và thực tập sinh Content Marketing trên mạng nội bộ. Mọi người đăng nhập bằng tài khoản riêng và dùng chung dữ liệu SQLite trên máy chủ. Không cần cài thư viện Python bên ngoài.

## Chạy trên Windows — cổng 5001

1. Cài **Python 3.10 trở lên** từ https://www.python.org/downloads/windows/ nếu chưa có. Chọn **Add Python to PATH** khi cài.
2. Tải repository hoặc cập nhật bản đang có:

   ```powershell
   git clone https://github.com/supernetec01/manage-task.git
   cd manage-task
   ```

   Nếu đã clone, mở PowerShell trong thư mục `manage-task` rồi chạy `git pull origin main`.
3. Nhấp đúp **start.bat**, hoặc chạy:

   ```powershell
   py -3 server.py --host 0.0.0.0 --port 5001
   ```

4. Trên **chính máy chủ**, mở http://localhost:5001. Lần đầu, tạo tài khoản quản trị qua màn hình thiết lập. Không có tài khoản hay mật khẩu mặc định. Chỉ máy chủ truy cập bằng loopback mới được tạo quản trị đầu tiên.
5. Giữ cửa sổ terminal đang chạy. Đóng cửa sổ sẽ dừng website.

Nếu không có lệnh `py` nhưng `python --version` hiển thị Python 3, dùng `python server.py --port 5001`.

## Chạy trên macOS/Linux

```sh
git clone https://github.com/supernetec01/manage-task.git
cd manage-task
./start.sh
```

Lệnh chạy trực tiếp tương đương: `python3 server.py --host 0.0.0.0 --port 5001`. Không dùng đường dẫn `/workspace/manage-task` trên máy cá nhân; đó là đường dẫn trong môi trường cloud.

## Cho nhân viên truy cập trong cùng mạng

Sau khi quản trị đầu tiên được tạo, người quản lý tạo tài khoản cho từng nhân viên. Máy khác cùng mạng mở `http://<IP-LAN-máy-chủ>:5001`, thay phần IP bằng địa chỉ IPv4 LAN thật của máy chủ (xem bằng `ipconfig` trên Windows). Không dùng `localhost` trên điện thoại/máy nhân viên vì nó trỏ đến chính thiết bị đó.

Cho phép TCP 5001 trong tường lửa cho mạng **Private** và phạm vi mạng nội bộ nếu cần. Không tắt toàn bộ tường lửa hoặc chuyển tiếp cổng này ra Internet. Bản chạy LAN dùng HTTP; triển khai qua Internet hoặc mạng không tin cậy cần HTTPS, cấu hình reverse proxy và kiểm tra triển khai riêng.

Có thể đổi cổng bằng `py -3 server.py --port 5002` hoặc `PORT=5002 ./start.sh` trên macOS/Linux.

## Vai trò và quy trình

- **Quản trị:** quản lý tài khoản, cấp vai trò, giao việc, kiểm tra và xem báo cáo toàn đội.
- **Trưởng nhóm:** quản lý task Content Marketing, phân công từng khâu, duyệt bàn giao, xem và phản hồi báo cáo. Không được nâng quyền thành quản trị.
- **Nhân viên Content / thực tập sinh:** xem việc mình phụ trách hoặc được giao một khâu; cập nhật tiến độ, minh chứng, vướng mắc và gửi báo cáo của bản thân.

## Giao việc nhanh và triển khai sau

Ở Tổng quan, Việc của tôi, Tất cả nhiệm vụ và Lịch công việc đều dùng chung form **Tạo nhiệm vụ** gồm 5 mục:

1. **Nhiệm vụ cần làm** — bắt buộc.
2. **Người thực hiện** — bắt buộc; mặc định bản thân ở Việc của tôi, hoặc theo nhân viên đang được lọc khi quản lý giao việc.
3. **Deadline** — ngày và giờ Việt Nam; bắt buộc khi giao việc, không bắt buộc khi lưu nháp.
4. **Mô tả chi tiết** — tùy chọn, gộp yêu cầu, đầu ra và tiêu chí nghiệm thu.
5. **Tài liệu liên quan** — tùy chọn, nhiều liên kết (mỗi dòng một link), chọn/kéo thả tệp hoặc dán ảnh.

Phần **Tùy chọn thêm** mặc định thu gọn: chiến dịch, ưu tiên (Bình thường), người duyệt và mẫu triển khai. Kênh/Pillar/Angle/Series được bổ sung trong **Kế hoạch nội dung** ở chi tiết nhiệm vụ. Bước tiếp theo do người thực hiện cập nhật sau khi nhận việc. Giờ dự kiến không bắt buộc.

**Lưu nháp** giữ nhiệm vụ riêng cho người tạo (và quản trị viên). Chưa giao cho nhân viên, không tính dashboard công việc đã giao, lịch hoặc báo cáo. Mở tab **Bản nháp** để bổ sung deadline rồi giao việc. Bản nháp cần có tên nhiệm vụ.

Nhân viên và thực tập sinh được tự tạo nhiệm vụ cho bản thân; không tự giao cho người khác hoặc tự duyệt. Quản lý có thể chọn **Quản lý phụ trách** trong tài khoản từng người. Khi nhân viên tự tạo, người duyệt lấy theo thiết lập này; nếu chưa thiết lập hoặc quản lý đã bị khóa, chọn trưởng nhóm đang hoạt động, rồi mới đến quản trị. Với nhiệm vụ quản lý giao, mặc định người duyệt là người giao; có thể đổi trong tùy chọn.

Luồng việc ngắn: **Nhận việc → Cập nhật tiến độ / Báo vướng mắc → Nộp kết quả → Đạt / Cần sửa**. Nhân viên có thể **Cần làm rõ** trước khi nhận. Tiến độ chỉ cần ghi đã làm gì và bước tiếp theo, không yêu cầu phần trăm. Kết quả bàn giao có thể là nội dung trả lời, tệp hoặc đường dẫn; không bắt buộc dùng link cho công việc có đầu ra là văn bản. Vướng mắc phải được xác nhận đã giải quyết trước khi nộp.

Checkpoint không tự áp dụng cho mọi nhiệm vụ. Có thể chọn mẫu **Video: Kịch bản → Quay → Dựng** hoặc thêm checklist trong chi tiết. Quản lý sửa tên bước, người thực hiện, thời hạn; nhân viên chỉ sửa tiến độ/ghi chú của bước mình được giao. Nhân viên có thể đề xuất các bước hoặc deadline, nhưng chỉ có hiệu lực khi quản lý xác nhận. Khi tiến độ đã đổi sau đề xuất, cần đề xuất lại để tránh ghi đè. Duyệt và đăng bài theo dõi riêng, không đồng nhất “dựng xong” với “đã đăng”.

Báo cáo **ngày/tuần** giữ riêng số nhiệm vụ đến hạn và danh sách nhiệm vụ có thao tác cập nhật của người báo cáo trong kỳ. Người báo cáo bổ sung nhận định, vướng mắc và kế hoạch tiếp theo; không suy ra chỉ số kinh doanh từ số việc. Bản gửi giữ snapshot tại thời điểm gửi, không thay đổi khi task thay đổi. Quản lý phản hồi báo cáo. Mật khẩu, mã phiên và mã CSRF không nằm trong dữ liệu xuất.

Tài liệu tối đa **5 MB/tệp**, **10 tệp/phần** (hỗ trợ, kết quả hoặc cập nhật), **20 liên kết/phần**. Tệp lưu trong SQLite cùng dữ liệu, chỉ người có quyền xem nhiệm vụ mới tải được; tải xuống dạng attachment, không thực thi trong website. Tệp tải lên nhưng chưa gắn vào nhiệm vụ chỉ người tải được xem, tối đa 30 tệp chưa gắn; được dọn khi có lần upload tiếp theo sau 24 giờ. Nếu bỏ form, tệp chưa gắn không tự thành tài liệu công việc.

## Dữ liệu, sao lưu và nâng cấp

- Dữ liệu mặc định ở `data/supernet.db`, không đưa vào Git. Đặt `SUPERNET_DATA_DIR` để dùng thư mục dữ liệu khác.
- Trước khi nâng cấp hoặc sao lưu: dừng máy chủ bằng **Ctrl+C**, sao chép toàn bộ thư mục `data` đến nơi an toàn, rồi khởi động lại. Giữ file sao lưu như dữ liệu nội bộ có quyền truy cập hạn chế.
- Khôi phục: dừng máy chủ, giữ một bản sao dữ liệu hiện tại, thay thư mục `data` bằng bản sao lưu tương thích, rồi khởi động lại. Không chạy hai máy chủ cùng quản lý một file dữ liệu trên ổ mạng.
- Dữ liệu localStorage của bản demo cũ **không tự động chuyển** sang hệ thống dùng chung. Có thể xuất JSON từ bản demo để giữ lại; chưa có chức năng nhập bản JSON đó hoặc nhập Excel trực tiếp.
- Bản nâng cấp giữ task và báo cáo đã có. Deadline cũ chỉ có ngày được hiểu là 23:59:59 ngày đó ở Việt Nam; các checkpoint cũ được giữ. Báo cáo đã chốt không bị viết lại.
- Các tài khoản tạo mới bắt đầu với dữ liệu thật do người quản lý nhập; không tự đưa dữ liệu nhân viên từ file Excel vào hệ thống.

## Phạm vi hiện tại

Tập trung Content Marketing: tài khoản, phân quyền máy chủ, nhiệm vụ chung, bản nháp, tài liệu và checklist tùy chọn, theo dõi xuất bản, báo cáo ngày/tuần, quản lý đội ngũ và xuất dữ liệu. Những vị trí khác, nhập Excel có rà soát, thư viện footage, gửi email nhắc hạn, tích hợp TikTok và chấm KPI tự động được triển khai sau.

## Kiểm tra

```sh
python3 -m unittest discover -s tests -v
node --check app.js
```

Trên Windows có thể thay `python3` bằng `py -3`. Bộ kiểm thử API dùng dữ liệu tạm riêng, kiểm tra xác thực, quyền truy cập, CSRF, vòng đời công việc và báo cáo; không sửa cơ sở dữ liệu đang sử dụng.

Kiểm thử trình duyệt tùy chọn: `node tests/browser_smoke.cjs` (cần Node 18+, Playwright và Chromium có sẵn). Có thể chọn binary Chromium qua `CHROMIUM_EXECUTABLE` và Python qua `PYTHON_TEST_EXECUTABLE`. Bài kiểm tra tự tạo máy chủ và database tạm, chạy luồng quản lý/nhân viên/thực tập sinh, báo cáo ngày/tuần và giao diện mobile. Các công cụ kiểm thử này không phải dependencies để chạy website.

## Khắc phục lỗi khởi động

| Lỗi | Cách xử lý |
| --- | --- |
| Không tìm thấy `py`/`python` | Cài Python 3, chọn Add Python to PATH và mở lại terminal. |
| `can't open file server.py` | Mở terminal trong thư mục có `server.py`, hoặc nhấp đúp `start.bat`. |
| `WinError 10048` / `Address already in use` | Cổng 5001 đang được dùng. Không chạy thêm bản thứ hai; kiểm tra cửa sổ máy chủ cũ, hoặc dùng cổng khác. |
| `Connection refused` | Kiểm tra cửa sổ máy chủ còn chạy và đúng cổng. |
| Máy chủ mở được nhưng máy khác không mở được | Dùng IP LAN của máy chủ, cùng mạng và kiểm tra tường lửa Private. |
| Không tạo được quản trị ban đầu từ máy nhân viên | Mở `http://localhost:5001` trên máy chủ để thực hiện thiết lập đầu tiên. |
| Task/báo cáo chưa hiện thay đổi từ máy khác | Tải lại dữ liệu trên giao diện hoặc tải lại trang; kiểm tra các máy đang dùng cùng địa chỉ máy chủ. |
