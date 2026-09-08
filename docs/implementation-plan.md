# Implementation plan

Chưa triển khai code. Thực hiện lần lượt bốn bước; không tạo trước bộ khung cho các khả năng chưa dùng.

Ưu tiên một luồng nhỏ chạy được. Ca publish không rõ kết quả được dừng để kiểm tra thủ công; chưa xây cơ chế phục hồi tự động tổng quát.

## Bước 1 — SharePoint spike

- Viết script thử đọc/upload và conditional update/create trong folder test; chứng minh byte nội dung và ETag thuộc cùng phiên bản, kể cả khi file đổi giữa các lần đọc.
- Kiểm tra identity người gửi, xác thực reviewer và quyền bảo vệ wiki/history.
- Kiểm tra render Markdown và trạng thái review trên kênh đọc hiện tại.
- Ghi kết quả cùng giới hạn API, không đưa secret vào repo.

Xong khi chứng minh được cơ chế xác thực và chống ghi đè. Chưa có tenant thì dùng fixture cho bước tiếp theo, ghi rõ chưa kiểm chứng tích hợp.

## Bước 2 — Submit và review

- Tạo chương trình Python nhỏ, SQLite và các lệnh `scan`, `review`, `status`; dùng chung process lock cho các thao tác đổi trạng thái ngay từ bước này.
- Parse manifest, kiểm tra path/hash/giới hạn file; đóng băng bundle và xử lý proposal ID trùng.
- Hiển thị diff, nguồn, lý do và file cuối cùng có khối trạng thái; lưu quyết định gắn bundle/artifact hashes và identity đã xác thực.
- Chặn self-review và payload thay đổi sau tiếp nhận.

Xong khi người phụ trách review được một proposal và mọi lần retry vẫn trỏ đúng một bundle.

## Bước 3 — Publish và phục hồi

- Thêm `publish` dùng chung process lock, lưu target/artifact hash/điều kiện ghi trước remote write và dùng conditional operation đã spike.
- Xuất bản nguyên artifact đã duyệt, lưu base/proposed/artifact hashes cùng kết quả remote; hoàn tất history trước khi báo published.
- Khi restart, kiểm tra các lần ghi dở và chặn publish cùng target nếu chưa rõ kết quả; file khác vẫn tiếp tục. Người phụ trách ghi bằng chứng trước khi bỏ chặn. Không coi hash trùng là đủ bằng chứng; history lỗi sau ghi không được làm upload wiki lại.
- Thêm cron, backup và hướng dẫn xử lý stale/drift.

Xong khi kiểm thử: hai proposal cùng base sửa cùng file chỉ một được publish; crash sau remote write không nhân đôi và ca chưa rõ bị chặn; remote thay đổi ngoài dự kiến không bị ghi đè. Artifact xuất bản đúng byte đã duyệt; khôi phục bằng proposal mới không mang nhãn review cũ hoặc lặp khối trạng thái.

Hai ca cần kiểm tra riêng: file đổi giữa đọc nội dung và metadata không được tạo điều kiện ghi sai; lần ghi chưa rõ kết quả phải chặn proposal khác cùng target qua cả restart, nhưng không chặn file khác.

## Bước 4 — Pilot

- Thiết lập quyền, import tài liệu với nhãn chưa review và chạy bộ tình huống thực.
- Thử token hết hạn, throttling, permission denied và backup/restore.
- Ghi tuổi queue, thời gian sửa sai và lỗi kiểm tra mẫu bằng bảng thủ công.
- Người phụ trách quyết định mở rộng dựa trên kết quả; không mở rộng nếu review đã nghẽn.

Test tập trung vào quyền, phiên bản, idempotency và crash recovery. Dùng SQLite thật, fake remote để chèn lỗi, và kiểm tra SharePoint thật trong folder test. Chưa cần API server, UI, benchmark tổng quát, dashboard hoặc test mọi helper.
