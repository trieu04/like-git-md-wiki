# Lớp xử lý trung gian cho wiki Markdown

Wiki là cây file Markdown và link tương đối. Local folder hoặc SharePoint là nơi
lưu cây file đó. SQLite của worker chỉ giữ trạng thái xử lý, bundle đóng băng và
lịch sử; không thay thế định dạng wiki.

```text
Local folder ─── adapter ───┐
                           ├── WikiStorage ── Worker: submit → review → publish
SharePoint ──── adapter ────┘                         │
                                            SQLite trạng thái/lịch sử
```

## Đã chạy được

- `LocalFolderStorage`: đọc wiki hiện có và xuất bản trực tiếp file `.md`, giữ
  đường dẫn tương đối. Thư mục `.wiki-system/` chứa lock và receipt của adapter.
- `FixtureRemote`: adapter SQLite chỉ dành cho test, tách khỏi workflow.
- `WikiStorage`: giao diện chung cho list/read/conditional write/verify/receipt.
  Version là token opaque: workflow không giả định số phiên bản tăng dần hay
  truy cập database của adapter.
- `Worker.submit(manifest, base, proposed, submitter)`: nhận byte đã tải từ một
  nguồn bất kỳ; không bắt buộc proposal phải nằm trong local folder.
- `Worker.propose(...)`: lấy bản nền từ storage đang cấu hình rồi tạo proposal.
  Quá trình này chỉ ghi trạng thái; wiki chỉ đổi sau approval và publish.

Ví dụ chạy từ repo, thay các đường dẫn mẫu bằng đường dẫn của bạn:

```sh
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer list
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer show index.md
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer context index.md --source source.md
# Agent creates the bundle using the skill before scan:
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer scan /path/to/contribution-bundle --submitter author
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer review change-1 --actor reviewer --reason 'Đã kiểm tra nguồn'
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer publish change-1
```

## Web UI

Khởi động UI trên máy local bằng cùng cấu hình storage/state/reviewer:

```sh
python -m wiki_worker.cli --folder /path/to/wiki --state /path/to/worker-state --reviewer reviewer web --port 8080
```

Mở `http://127.0.0.1:8080`. UI dùng HTML, Pico CSS và AlpineJS; Pico/Alpine
được tải từ CDN nên trình duyệt cần mạng để có style và tương tác. Backend HTTP
dùng Python standard library và gọi đúng `Worker` đang phục vụ CLI. UI hỗ trợ
tạo file đóng góp từ context đã lưu, tiếp nhận file để review, đọc contribution
cùng diff/artifact, ghi quyết định và publish. Agent tự tìm kiếm tài liệu qua filesystem.

Web server hiện chỉ cho bind localhost vì chưa có đăng nhập, session hoặc CSRF.
Reviewer và submitter vẫn là identity của môi trường pilot tin cậy. Không reverse
proxy hoặc expose port này ra mạng. Adapter SharePoint sau này phải cung cấp danh
tính Microsoft đã xác thực cho API thay vì nhận identity từ form.

Dùng một state directory cố định cho mỗi wiki. Không đổi storage của state đang
có proposal. `--actor`/`--submitter` là danh tính do môi trường CLI tin cậy cung
cấp, không phải đăng nhập Microsoft. Cần giới hạn quyền chạy bằng tài khoản worker.

Local adapter dùng lock chung theo wiki root, file tạm, fsync và atomic rename.
Tạo mới dùng thao tác không thay file đã tồn tại. Mọi writer phải tuân theo lock
của adapter; quyền ghi wiki nên chỉ thuộc worker. Editor hoặc chương trình sync
bỏ qua lock có thể ghi đúng lúc kiểm tra/rename, nên local folder đang sync
SharePoint không tương đương adapter SharePoint có ETag. Thay đổi ngoài luồng
trước publish được phát hiện qua base hash/version, nhưng không có cam kết CAS
với writer không hợp tác.

## Điểm nối SharePoint

Chưa có HTTP adapter SharePoint trong bản này. Adapter đó triển khai `WikiStorage`
và được truyền vào `Worker(root, storage, reviewer)`, không sửa luật review/publish:

1. `list_markdown`: liệt kê đường dẫn logic trong wiki root đã cấu hình.
2. `read`: trả `content` (bytes), `item`, `version` (ETag) của cùng một phiên bản;
   chỉ trả `None` khi xác nhận không tồn tại.
3. `write`: nhận điều kiện `[item, version]` hoặc `None` để tạo mới. Chỉ báo
   `Conflict` nếu chắc chắn không ghi; timeout phải đi vào luồng chưa rõ kết quả.
4. `verify` và `receipt`: xác minh bằng chứng thao tác cụ thể, gồm target, artifact
   hash và điều kiện ghi gốc; không chỉ so hash nội dung hiện tại.
5. Tiếp nhận proposal: tải manifest/base/proposed, gắn danh tính xác thực với bản
   manifest đã tải, rồi gọi `Worker.submit`. Lớp xử lý kiểm tra schema/hash và đóng
   băng byte như với local folder.

Cần thêm HTTP/auth và kiểm chứng conditional write/ETag trên tenant trước khi
có thể dùng SharePoint thật. Không dùng fixture hoặc folder sync để suy ra rằng
các điều kiện đó đã được đáp ứng. Xem các ca cần kiểm chứng trong `runtime.md`.
