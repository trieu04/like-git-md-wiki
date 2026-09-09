# Thiết kế MVP

## Phạm vi

Chứng minh một luồng: **gửi thay đổi → người phụ trách review → xuất bản đúng bản đã duyệt → truy lại và sửa sai**. Runtime fixture đã có; xem [hướng dẫn](runtime.md). SharePoint thật chưa được kiểm chứng.

Một folder Markdown trên SharePoint, một reviewer cấu hình (người hoặc agent), một worker trên một host. Mỗi proposal sửa hoặc thêm một file. Chưa rename/delete, attachment, nhiều file hoặc phân quyền theo nhiều domain. Nhân viên/agent gửi proposal; chỉ worker ghi wiki chính thức. Quyền ghi và xác thực phải kiểm chứng trước pilot.

Ưu tiên luồng nhỏ chạy được. Trường hợp hiếm hoặc kết quả không rõ có thể dừng để người phụ trách xử lý; chưa xây hệ thống phục hồi tự động tổng quát.

## Dữ liệu

```text
wiki/                       Các tài liệu đang được chia sẻ
proposals/<id>/
  base.md                   Toàn bộ bản nền, bỏ qua nếu tạo mới
  proposed.md               Nội dung mới, không kèm khối trạng thái hệ thống
  proposal.ready.json       Manifest gửi cuối cùng
history/<id>/               Bundle đóng băng, quyết định và kết quả xuất bản
```

Manifest gồm schema version, proposal ID, target path, base hash (null khi thêm), proposed hash, lý do và nguồn/ngữ cảnh nếu có. SHA-256 tính trên byte gốc; giữ bản nền để truy lại nội dung. Hash bundle dùng hash nguyên byte manifest chứa các hash file; giữ nguyên manifest, không serialize lại khi kiểm chứng. Path phải nằm trong wiki; từ chối đường dẫn thoát root, tên nhập nhằng và JSON có key trùng.

Worker lấy người gửi từ metadata SharePoint đã xác thực gắn với bản manifest tiếp nhận, không tin trường tác giả tự khai. Quyền inbox phải ngăn người khác sửa proposal rồi mang danh người gửi cũ. Nếu agent dùng ứng dụng chung không xác định được người gửi, chỉ thử nội bộ cho đến khi có cách submit xác thực phù hợp.

Proposal bất biến sau tiếp nhận; sửa tạo ID mới. Cùng ID và bundle là retry, khác bundle là lỗi. Suffix chỉ là tín hiệu: worker phải tải đủ, kiểm tra hash và lưu bản đóng băng bền vững trước khi cho review.

## Runtime

Một chương trình Python với các lệnh `scan`, `review`, `publish`, `status`; scan/publish chạy định kỳ bằng cron. SQLite và bundle đóng băng nằm trên durable volume riêng, không trong SharePoint sync. SQLite giữ trạng thái/tiến độ; history giữ bản lưu để truy vết. Lưu nội dung bền vững trước khi DB tham chiếu đến nó.

Một process lock dùng chung cho các lệnh thay đổi trạng thái. Không giữ lock trong lúc chờ người review; khi xác nhận phải kiểm tra lại trạng thái. CLI review chạy trong môi trường tin cậy; contributor không được sửa DB/bundle hoặc chạy tùy ý với quyền worker.

Web UI/API localhost hỗ trợ nhận file, đọc contribution cùng artifact, review và publish; chưa có xác thực cho truy cập mạng. Agent đóng góp bằng file/bundle. Không có queue service hay workflow framework.

## Review và xuất bản

1. Scan kiểm tra payload/path/hash, xác định người gửi và đóng băng bundle.
2. Người phụ trách xem diff, lý do và nguồn qua CLI. Xác thực Microsoft 365 và kiểm tra reviewer thuộc cấu hình pilot bằng ID tài khoản, không bằng tên tự khai. Người gửi không tự duyệt; nếu chỉ có một reviewer và người đó là người gửi thì giữ chờ.
3. Worker dựng file cuối cùng gồm nội dung và khối trạng thái, cho reviewer xem trước khi xác nhận. Lưu file này cùng bundle hash, artifact hash, reviewer, thời điểm và lý do. Publish dùng nguyên byte đã duyệt, không tạo lại metadata theo thời gian/cấu hình mới.
4. Trước publish, kiểm tra toàn file remote khớp base hash; byte nội dung, item ID và version/ETag phải thuộc cùng một phiên bản đã được xác minh. Không ghép nội dung cũ với ETag mới từ lần đọc metadata riêng. Ghi có điều kiện theo item/ETag đó; tạo mới phải thất bại nếu path đã tồn tại. Chỉ dùng thao tác được spike chứng minh đáp ứng điều kiện; lỗi quyền/mạng không được hiểu là file không tồn tại.
5. Lưu bundle, quyết định và bước chuẩn bị publish bền vững trước ghi remote, gồm target, artifact hash và điều kiện ghi (item/ETag hoặc tạo khi chưa tồn tại). Sau ghi, lưu kết quả remote và xác minh artifact, hoàn tất history rồi mới báo `published`. Nếu chỉ còn thiếu history thì hoàn tất ghi nhận, không upload wiki lại.

Khi request timeout hoặc crash khiến không biết đã ghi hay chưa, tạm chặn mọi publish vào cùng target để kiểm tra remote/lịch sử; file khác vẫn có thể tiếp tục. Sau restart, xử lý các lần ghi dở trước khi nhận việc publish mới cho target đó. Hash trùng chỉ chứng minh nội dung, chưa đủ chứng minh lần ghi. Người phụ trách ghi bằng chứng và kết luận đã ghi hoặc chưa ghi trước khi cho tiếp tục; chưa rõ thì giữ chặn. Chưa cần tự động reconcile mọi trường hợp. Không retry ghi mù, lấy ETag mới để vượt điều kiện cũ hoặc blind rollback.

Trạng thái tối thiểu: `pending`, `approved`, `published`, `rejected`, `stale`; bước publish, lỗi tạm thời và cờ cần kiểm tra lưu riêng. Cờ cần kiểm tra chặn publish đến khi có kết luận được ghi nhận. Nền đã đổi trước ghi thì `stale`, cần proposal mới. Kết quả ghi chưa rõ không được coi là stale hoặc published. `published` ghi nhận lần xuất bản trong lịch sử, không có nghĩa file remote mãi còn ở phiên bản đó.

## Trạng thái người đọc và sửa sai

Worker thêm một khối trạng thái Markdown ở đầu file với owner, proposal ID và người/ngày review. Dùng marker dành riêng để tách khỏi nội dung; từ chối marker này trong `proposed.md`, tránh lặp khối hoặc mang nhãn review cũ sang bản mới. Base hash vẫn tính trên toàn file remote. Nhãn “phiên bản đã được review” không bảo đảm nội dung đúng tuyệt đối.

Import được làm trong lần thiết lập có kiểm soát: lưu bản gốc, thêm nhãn `chưa review` có kiểm tra phiên bản và ghi nhận file đã làm để không chồng nhãn khi chạy lại. Pilot phải kiểm tra kênh đọc thực tế; folder sync/offline có thể hiển thị bản cũ.

Phát hiện sai thì gửi proposal sửa hoặc thay bằng thông báo tạm rút nội dung; owner ưu tiên review. Khôi phục lấy phần nội dung bản cũ làm proposal mới trên bản hiện tại, dùng approval và khối trạng thái mới. Không ghi đè trực tiếp.

MVP chưa tự theo dõi nguồn đổi, cảnh báo quá hạn hoặc issue. Người phụ trách dùng công cụ hiện có.

## Vận hành tối thiểu

- Chỉ worker ghi wiki/history; tên thư mục không tự tạo phân quyền. Pilot dùng tài liệu cùng phạm vi truy cập, không sao chép nguồn hạn chế sang wiki rộng quyền.
- Backup SQLite nhất quán bằng backup API, kèm bundle/artifact được tham chiếu; tạm dừng ghi khi lấy bộ backup. Thử restore trước pilot, kiểm tra remote và các lần publish dở trước bật lại cron; không ghi đè remote mới bằng trạng thái backup cũ.
- Giới hạn kích thước proposal, retry lỗi tạm thời có backoff, không ghi token vào log. Nội dung proposal là dữ liệu, không được thực thi.
- Hash chống nhầm phiên bản, không thay thế xác thực và quyền ghi.

Chưa có atomic update nhiều file, graph snapshot hoặc temporal query. Ngữ cảnh ngoài bản/nguồn đã ghi nhận không được bảo đảm tái lập. Chỉ mở rộng khi pilot cho thấy vấn đề cụ thể cần giải quyết.

## Đóng góp từ nội dung

Agent tìm kiếm/đọc file trực tiếp, lấy phiên bản qua CLI và soạn bundle. UI tạo file `wiki-contribution-v3` cho reviewer tiếp nhận: phạm vi/tác động là `file | version | impact`, sources là `file | version`. Proposed content hiển thị trước, Base content sau, đều là Markdown thuần; các break có Boundary riêng không xuất hiện trong nội dung để phân biệt với dấu phân cách thông thường. Bộ đọc chỉ nhận file Markdown v3. Worker tra hash từ snapshot đã đăng ký theo cặp file/version rồi ghim ngữ cảnh nội bộ; hash payload vẫn được kiểm tra trong metadata. UI có thể dựng nội dung cuối bằng thay thế duy nhất hoặc thêm cuối file. Manifest có thể chứa `knowledge_change` gồm `before`, `after`, `scope`; kiểm tra phép thay thế duy nhất tái tạo đúng toàn bộ proposed (sau khi loại khối review cũ). Metadata này thuộc bundle hash, giữ nguyên qua review và lịch sử.

Knowledge diff này do tác giả khai báo, không phải suy luận ngữ nghĩa tự động. Chưa có mô hình AI, phát hiện mâu thuẫn, kiểm chứng nguồn hay tự sửa các file liên quan. Text diff và artifact đầy đủ vẫn dùng để kiểm tra chính xác nội dung xuất bản.

## Công cụ cho agent và ngữ cảnh bất biến

Xem [skill theo hai vai trò](agent-workflow.md). Worker cấp phiên bản qua CLI context, tiếp nhận file/bundle qua scan hoặc form reviewer. Đọc và artifact được gộp trong `/api/contribution/ID`. Reviewer agent có thể gọi công cụ review khi được giao xử lý pending; worker chỉ thực thi quyết định hợp lệ, không suy luận thay agent hoặc tự duyệt.

Manifest có thể chứa `context` gồm tham chiếu phiên bản đích và các nguồn. SQLite lưu bản chụp theo đường dẫn, mã `YYYYMMDD-N` (ngày quan sát UTC, thứ tự trong ngày của từng tài liệu), SHA-256, nội dung và thời điểm. Luồng agent bắt buộc context; các luồng cũ vẫn tương thích không context. Nguồn đổi chặn đề xuất mới và approve; đổi sau approve khiến publish chuyển stale. Reviewer vẫn có thể reject đề xuất có nguồn stale. Snapshot không bị ghi đè; history và backup giữ tham chiếu/ngữ cảnh.

Kiểm tra độ mới không đánh giá độ đúng của kiến thức, không phát hiện nguồn thiếu và không bảo đảm giao dịch nguyên tử giữa nhiều nguồn với writer ngoài worker. Không có scheduler hoặc model tự động trong worker.
