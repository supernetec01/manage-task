# Super Net Workspace

Website dùng thử bằng tiếng Việt cho đội marketing, kinh doanh và thực tập sinh.

## Chạy

Yêu cầu Python 3, không cần cài dependencies:

```sh
cd /workspace/manage-task
./start.sh
```

Mở ứng dụng qua địa chỉ máy chủ mà hệ thống triển khai cung cấp. Kiểm tra nội bộ: `curl -f http://127.0.0.1:5001/`.

## Phạm vi

- Tổng quan, danh sách/bảng trạng thái, tìm kiếm và lọc theo người/chuyên môn/trạng thái.
- Tạo task theo mẫu, checklist, bước tiếp theo, deadline, ưu tiên, minh chứng, báo vướng mắc và lịch sử.
- Nhận việc → thực hiện → nộp duyệt → yêu cầu sửa / nghiệm thu. Nộp duyệt yêu cầu checklist đầy đủ và link minh chứng.
- Khối lượng dự kiến theo nhân viên/thực tập sinh; nhóm task theo chiến dịch.
- Báo cáo tuần, bản chụp dữ liệu của người báo cáo lúc chốt, xuất JSON.
- Responsive và lưu dữ liệu trên localStorage của trình duyệt. Dữ liệu khởi tạo được ghi rõ là minh họa.

Đây là bản dùng thử trên một thiết bị: chưa có backend, xác thực, phân quyền bảo mật, đồng bộ nhiều người, email nhắc hạn hoặc tích hợp sàn. Trước khi dùng thật cần bổ sung các thành phần này và sao lưu dữ liệu. Nút xuất dữ liệu tải JSON về máy, chưa có chức năng nhập lại trong giao diện. Không nhập thông tin nhạy cảm vào bản dùng thử.

Font Be Vietnam Pro tải từ Google Fonts; khi không truy cập được, ứng dụng dùng Arial.

## Chạy trên máy nội bộ

```sh
git clone https://github.com/supernetec01/manage-task.git
cd manage-task
./start.sh
```

Trên chính máy chủ, mở `http://localhost:5001`. Máy khác cùng mạng mở `http://<IP-LAN-máy-chủ>:5001`; thay phần IP bằng địa chỉ thật của máy chủ. Nếu có tường lửa, cho phép TCP 5001 từ mạng nội bộ. Máy chủ phải tiếp tục chạy để truy cập được. Không chuyển tiếp cổng này ra Internet.

Có thể thay cổng bằng `PORT=5002 ./start.sh`. Máy chủ chỉ phục vụ các tệp giao diện đã cho phép, không công khai Git metadata hoặc danh sách thư mục. Đây là máy chủ dùng thử trong mạng tin cậy, chưa có TLS hay xác thực.

Chạy trên mạng nội bộ không tự tạo đồng bộ dữ liệu: mỗi trình duyệt vẫn có bộ dữ liệu riêng. Để dùng chung task thực tế giữa nhân viên cần backend và cơ sở dữ liệu.
