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

Mỗi nội dung có kênh, pillar, angle, series/chiến dịch, người chịu trách nhiệm, người duyệt, deadline và tiêu chí nghiệm thu. Ba khâu **Kịch bản → Quay → Dựng** có người phụ trách và tiến độ riêng. Nhân viên chỉ cập nhật khâu mình được giao; người quản lý điều phối toàn bộ.

Luồng công việc: **Chờ nhận → Đang làm → Chờ duyệt → Cần sửa / Đã nghiệm thu**. Nộp duyệt cần các khâu hoàn thành và link sản phẩm hợp lệ. Xuất bản được theo dõi riêng với lịch đăng và link bài, không đồng nhất “dựng xong” với “đã đăng”. Lịch sử thay đổi và hạn ban đầu được giữ lại.

Báo cáo **ngày và tuần** tổng hợp công việc có liên quan trong kỳ, rồi người báo cáo bổ sung kết quả, vướng mắc và kế hoạch tiếp theo. Bản đã gửi giữ một snapshot dữ liệu tại thời điểm gửi; thay đổi task sau đó không âm thầm sửa bản báo cáo. Người quản lý xem và phản hồi báo cáo. Mật khẩu, mã phiên đăng nhập và mã CSRF không nằm trong dữ liệu xuất; tên đăng nhập được giữ để quản lý đối chiếu tài khoản.

## Dữ liệu, sao lưu và nâng cấp

- Dữ liệu mặc định ở `data/supernet.db`, không đưa vào Git. Đặt `SUPERNET_DATA_DIR` để dùng thư mục dữ liệu khác.
- Trước khi nâng cấp hoặc sao lưu: dừng máy chủ bằng **Ctrl+C**, sao chép toàn bộ thư mục `data` đến nơi an toàn, rồi khởi động lại. Giữ file sao lưu như dữ liệu nội bộ có quyền truy cập hạn chế.
- Khôi phục: dừng máy chủ, giữ một bản sao dữ liệu hiện tại, thay thư mục `data` bằng bản sao lưu tương thích, rồi khởi động lại. Không chạy hai máy chủ cùng quản lý một file dữ liệu trên ổ mạng.
- Dữ liệu localStorage của bản demo cũ **không tự động chuyển** sang hệ thống dùng chung. Có thể xuất JSON từ bản demo để giữ lại; chưa có chức năng nhập bản JSON đó hoặc nhập Excel trực tiếp.
- Các tài khoản tạo mới bắt đầu với dữ liệu thật do người quản lý nhập; không tự đưa dữ liệu nhân viên từ file Excel vào hệ thống.

## Phạm vi hiện tại

Tập trung Content Marketing: tài khoản, phân quyền máy chủ, task theo khâu, theo dõi xuất bản, báo cáo ngày/tuần, quản lý đội ngũ và xuất dữ liệu. Những vị trí khác, nhập Excel có rà soát, thư viện footage, gửi email nhắc hạn, tích hợp TikTok và chấm KPI tự động được triển khai sau.

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
