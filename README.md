# Like Git SharePoint Wiki

Mục tiêu: wiki vẫn đáng tin khi kiến thức và số người/AI agent đóng góp tăng lên.

MVP chỉ cần chứng minh một luồng: **gửi thay đổi → người phụ trách review → xuất bản đúng bản đã duyệt → có thể truy lại và sửa sai**. Hiện repo chỉ có thiết kế và kế hoạch, chưa có runtime.

## Làm trước

- Giữ wiki Markdown và link hiện tại trên SharePoint.
- Mỗi đề xuất sửa một file, kèm nội dung nền, hash, nội dung mới, lý do và nguồn nếu có.
- Một người phụ trách pilot quyết định; agent không tự duyệt.
- Trước xuất bản, kiểm tra file hiện tại còn đúng bản nền và payload còn đúng bản đã duyệt. Nếu khác, yêu cầu gửi/review lại; không tự merge.
- Xuất bản nguyên file cuối cùng đã duyệt, gồm khối trạng thái. Nếu không biết lần ghi đã thành công hay chưa, tạm chặn publish vào cùng file để kiểm tra; MVP chưa tự động phục hồi mọi trường hợp.
- Giữ bản cũ, người gửi, người duyệt và thời điểm để truy vết. Sửa sai bằng đề xuất mới; khôi phục cũng đi qua kiểm tra phiên bản.
- Hiển thị rõ tài liệu chưa review hoặc phiên bản đã được review, cùng người chịu trách nhiệm. Nhãn review không bảo đảm nội dung đúng tuyệt đối.

MVP chưa làm claim graph, tự phát hiện mâu thuẫn, chấm điểm cạnh, issue tracker, deadline review tự động, dependency invalidation, policy engine, API/UI riêng hay workflow engine. Chỉ thêm khi pilot gặp vấn đề cụ thể cần giải quyết.

## Cách kiểm chứng

Thử trên một nhóm tài liệu và một người phụ trách. Kiểm tra người đọc nhận biết trạng thái; hai agent sửa cùng file không ghi đè nhau; chạy worker lại không xuất bản hai lần; có thể truy nguồn và sửa một nội dung sai. Theo dõi thủ công tuổi đề xuất chờ, thời gian sửa sai và lỗi qua kiểm tra mẫu.

## Tài liệu thực hiện

- [Thiết kế MVP](docs/design.md)
- [Plan](docs/plan.md)
- [Implementation plan](docs/implementation-plan.md)

Các bản `knowledge-model-horizon.md` và `sharepoint-transport-draft.md` là tham khảo lịch sử, không phải backlog hay yêu cầu triển khai.
