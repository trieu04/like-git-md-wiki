# Like Git SharePoint Wiki

Mục tiêu: wiki vẫn đáng tin khi kiến thức và số người/AI agent đóng góp tăng lên.

MVP chỉ cần chứng minh một luồng: **gửi thay đổi → người phụ trách review → xuất bản đúng bản đã duyệt → có thể truy lại và sửa sai**. Repo đã có layer Python/SQLite với adapter local folder Markdown và fixture test; tích hợp SharePoint và xác thực Microsoft 365 chưa được kiểm chứng.

## Làm trước

- Giữ wiki Markdown và link hiện tại trên SharePoint.
- Mỗi đề xuất sửa một file, kèm nội dung nền, hash, nội dung mới, lý do và nguồn nếu có.
- Reviewer được cấu hình (người hoặc agent) quyết định qua công cụ review; tác giả không tự duyệt. Hệ thống không tự quyết định duyệt.
- Trước xuất bản, kiểm tra file hiện tại còn đúng bản nền và payload còn đúng bản đã duyệt. Nếu khác, yêu cầu gửi/review lại; không tự merge.
- Xuất bản nguyên file cuối cùng đã duyệt, gồm khối trạng thái. Nếu không biết lần ghi đã thành công hay chưa, tạm chặn publish vào cùng file để kiểm tra; MVP chưa tự động phục hồi mọi trường hợp.
- Giữ bản cũ, người gửi, người duyệt và thời điểm để truy vết. Sửa sai bằng đề xuất mới; khôi phục cũng đi qua kiểm tra phiên bản.
- Hiển thị rõ tài liệu chưa review hoặc phiên bản đã được review, cùng người chịu trách nhiệm. Nhãn review không bảo đảm nội dung đúng tuyệt đối.

MVP chưa làm claim graph, tự phát hiện mâu thuẫn, chấm điểm cạnh, issue tracker, deadline review tự động, dependency invalidation, policy engine hay workflow engine. Chỉ thêm khi pilot gặp vấn đề cụ thể cần giải quyết.

## Cách kiểm chứng

Thử trên một nhóm tài liệu và một người phụ trách. Kiểm tra người đọc nhận biết trạng thái; hai agent sửa cùng file không ghi đè nhau; chạy worker lại không xuất bản hai lần; có thể truy nguồn và sửa một nội dung sai. Theo dõi thủ công tuổi đề xuất chờ, thời gian sửa sai và lỗi qua kiểm tra mẫu.

## Tài liệu thực hiện

- [Thiết kế MVP](docs/design.md)
- [Plan](docs/plan.md)
- [Implementation plan](docs/implementation-plan.md)
- [Wiki đột quỵ (bản local)](wiki/index.md)

Các bản `knowledge-model-horizon.md` và `sharepoint-transport-draft.md` là tham khảo lịch sử, không phải backlog hay yêu cầu triển khai.

## Runtime

Xem [hướng dẫn chạy và phục hồi](docs/runtime.md). Chạy test bằng `python -m unittest discover -s tests -v`. Hỗ trợ `--folder` cho wiki Markdown thật và `--fixture` cho test; chưa có kết nối HTTP SharePoint.

Wiki luôn là cây file Markdown. Xem [kiến trúc layer và adapter](docs/storage-layer.md) để chạy với local folder và tích hợp nguồn SharePoint.

Web UI dùng HTML, Pico CSS và AlpineJS, chạy bằng lệnh `wiki-worker ... web` trên localhost.

## Hai luồng: đóng góp và reviewer

**Đóng góp — Skill cho agent.** Agent tự khám phá/tìm kiếm file, lấy phiên bản bằng lệnh `context`, đọc nguồn và tạo một file `.contribution.md`. Agent không dùng HTTP API để gửi nội dung. Quy ước đầy đủ nằm trong [skill đóng góp](skills/wiki-knowledge-workflow/references/contribution.md).

**Reviewer — UI + Skill.** Reviewer tiếp nhận file/bundle bằng `scan`, hoặc nhập file `.contribution.md` trong UI. `GET /api/contribution/ID` gộp nội dung, nguồn, trạng thái và artifact trong một response. Công cụ review/publish dùng `/api/contribution/ID/review` và `/api/contribution/ID/publish`. Xem [skill reviewer](skills/wiki-knowledge-workflow/references/reviewer.md).

UI có form **Đóng góp** tạo file Markdown v2: bảng **Phạm vi áp dụng và tác động** lưu `file | version | tác động`, bảng **Sources** lưu `file | version`. Worker tra SHA-256 từ snapshot đã đăng ký cho version, nên các bảng không chứa hash. Dòng đầu của bảng phạm vi là file chính. Người dùng có thể nhập toàn bộ nội dung, thay một đoạn xuất hiện đúng một lần, hoặc thêm vào cuối; file vẫn chứa toàn bộ Markdown cuối cùng. Tạo file diễn ra trong trình duyệt và chưa gửi vào hàng chờ. Form **Reviewer** hiển thị hai bảng cùng nội dung và ngữ cảnh đã ghim.

Nguồn dùng phiên bản `YYYYMMDD-N` theo ngày quan sát UTC, snapshot bất biến và SHA-256. Kiểm tra độ mới khi scan/import, approve và publish. Nội dung và quyết định vẫn do agent đánh giá; hệ thống không tự duyệt. Bản cũ không có context hiển thị `unversioned`.

```sh
python -m wiki_worker.cli --state .wiki-worker --folder wiki --reviewer reviewer-agent web --port 8080
```

Kiểm tra form tạo file bằng `node tests/test_ui_file.js`, workflow bằng `python -m unittest discover -s tests -v`.
