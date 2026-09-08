# SharePoint transport — bản phác thảo ban đầu

Tài liệu này giữ lại đề xuất cũ về vận chuyển file và xuất bản, không phải đặc tả hiện tại. [README](../README.md) và [thiết kế Phase 1](design.md) có ưu tiên. Merge file không đồng nghĩa chấp nhận claim; Phase 1 hiện dùng revision theo document, không dùng HEAD toàn wiki hoặc quy tắc stale mọi PR như bản cũ bên dưới.

Đề xuất Phase 1: wiki Markdown trên Microsoft 365 SharePoint, mọi nhân viên có thể đóng góp qua agent; mỗi đóng góp là một PR gắn với snapshot bất biến. Đây là thiết kế để thảo luận, chưa phải hệ thống đã triển khai hay API SharePoint đã được kiểm chứng trên tenant thực tế.

## Quan điểm thiết kế

Ý tưởng PR bằng file và phiên bản bằng hash/tree phù hợp. Tuy nhiên, suffix chỉ nên giúp nhận diện file; danh tính PR, trạng thái và phiên bản nền phải nằm trong manifest có schema. Một PR có thể sửa nhiều tài liệu nên cần một thư mục/bundle riêng, không chỉ một file có suffix.

Ba khái niệm cần tách rõ:

- SharePoint lưu và chia sẻ tài liệu, xác thực người dùng, giữ lịch sử phiên bản của từng file.
- Snapshot của hệ thống cố định toàn bộ cây tài liệu và nội dung mà agent đã đọc. Lịch sử phiên bản từng file của SharePoint không thay thế snapshot của cả wiki.
- PR mô tả tập thay đổi đề xuất trên một snapshot cụ thể. Worker kiểm tra, reviewer phê duyệt và một publisher duy nhất cập nhật phiên bản wiki chính thức.

Không giải quyết knowledge merge conflict trong Phase 1. Vẫn phải phát hiện thay đổi nền để không ghi đè dữ liệu: PR cũ bị đánh dấu `stale`, cần tạo revision dựa trên HEAD mới. Không tự merge, kể cả khi hai PR sửa hai file khác nhau; có thể nới lỏng sau.

## Bố cục đề xuất

```text
SharePoint document library/
  wiki/                         # Bản Markdown để mọi người đọc, link tương đối
  contributions/
    <pr-id>/
      revisions/
        <revision-id>/
          payload/docs/topic.md # Nội dung thay thế đầy đủ, giữ đường dẫn logic
          pr.ready.json         # Manifest upload cuối cùng, không sửa sau submit
  .wiki-system/
    objects/sha256/<hash>        # Blob bất biến, giữ byte nội dung cũ
    trees/<tree-hash>.json       # Đường dẫn -> blob hash
    commits/<commit-hash>.json   # Tree, parent, thông tin xuất bản
    refs/main.json              # HEAD; cập nhật có điều kiện
    pr-status/<pr-id>.json       # Trạng thái do worker quản lý
    publish-journal/<job-id>.json
```

Đây là bố cục logic; `.wiki-system` không mặc nhiên được SharePoint bảo vệ vì có dấu chấm. Cần quyền riêng cho vùng hệ thống và kiểm tra giới hạn tên/path của tenant. Nếu số lượng object lớn, đánh giá một kho object riêng ở phase sau; Phase 1 ưu tiên toàn bộ dữ liệu chia sẻ nằm trong Microsoft 365.

Suffix nên nhỏ và có ý nghĩa rõ: `.ready.json` là tín hiệu submit. Loại đóng góp (`add`, `modify`, `delete`, `rename`) nằm trong manifest. Không đổi tên file để biểu diễn toàn bộ vòng đời PR: thao tác đổi tên gây thêm sự kiện đồng bộ và không phải giao dịch trạng thái đáng tin cậy.

## Manifest PR

Ví dụ rút gọn, các giá trị hash bên dưới là placeholder:

```json
{
  "schema_version": 1,
  "pr_id": "pr-<uuid>",
  "revision_id": "rev-<uuid>",
  "title": "Bổ sung hướng dẫn onboarding",
  "base_commit": "sha256:<commit-hash>",
  "context": {
    "tree": "sha256:<tree-hash>",
    "read_paths": ["docs/onboarding.md", "docs/security.md"]
  },
  "changes": [
    {
      "op": "modify",
      "path": "docs/onboarding.md",
      "expected_blob": "sha256:<old-blob-hash>",
      "payload": "payload/docs/onboarding.md",
      "new_blob": "sha256:<new-blob-hash>"
    }
  ]
}
```

`add` yêu cầu path chưa tồn tại; `modify`/`delete` yêu cầu hash cũ đúng; `rename` khai báo path nguồn, path đích và hash nguồn. Phase 1 dùng full replacement thay vì patch để việc áp dụng và kiểm chứng đơn giản. Rename không tự sửa backlink: agent phải đưa các sửa link liên quan vào cùng PR.

Danh tính tác giả không được tin từ trường tự khai trong JSON. Dùng danh tính Microsoft 365 đã xác thực tại điểm submit hoặc metadata đáng tin từ nền tảng. Nếu tất cả upload dùng chung một service principal thì cần kênh submit xác thực riêng để giữ attribution từng nhân viên.

## Snapshot và ngữ cảnh agent

1. Blob hash = SHA-256 của byte gốc, không âm thầm chuẩn hóa nội dung trước khi hash.
2. Tree = danh sách đường dẫn logic và blob hash, sắp xếp xác định; quy định UTF-8, dấu `/`, Unicode NFC, cấm đường dẫn thoát root và tên trùng sau chuẩn hóa/case-fold theo chính sách kho.
3. Hash tree/commit từ JSON canonical với schema version cố định; ghi rõ thuật toán canonicalization khi triển khai. Commit chứa tree hash, parent commit và metadata xuất bản; tree hash chỉ phụ thuộc cây nội dung.
4. Lưu blob/tree/commit bất biến trước khi cho phép ref trỏ tới. Có hash mà không giữ nội dung tương ứng thì không thể tái tạo ngữ cảnh.
5. Agent nhận `base_commit`, đọc nội dung qua snapshot đó, không đọc xen kẽ file sống trong `wiki/`. `read_paths` giúp audit; các nguồn ngoài wiki cần snapshot/provenance riêng nếu muốn tái lập đầy đủ ngữ cảnh.

Hash đảm bảo định danh và kiểm tra toàn vẹn; không thay thế phân quyền, chữ ký hay nhật ký người thực hiện.

## Luồng PR và xuất bản

```text
draft -> submitted -> validating -> ready -> approved -> publishing -> merged
                         |           |         |
                         v           v         v
                       invalid    rejected    stale
```

- Agent upload payload trước, manifest `.ready.json` cuối cùng. Worker chưa coi upload là hoàn tất chỉ vì thấy suffix: phải tải đủ file và xác minh hash; lỗi chưa đồng bộ đủ được retry trước khi kết luận invalid.
- Cron quét inbox theo chu kỳ cấu hình được. Nhận diện idempotent bằng `(pr_id, revision_id, manifest_hash)`; cùng ID nhưng khác nội dung bị từ chối. Mỗi revision đã submit là bất biến.
- Worker kiểm tra schema, đường dẫn, quyền, payload hash, base commit, precondition từng file và link nội bộ. Link được resolve trên cây kết quả dự kiến; link ngoài không bắt buộc crawl. Chính sách link hỏng là cảnh báo hay chặn phải cấu hình rõ.
- Reviewer phê duyệt đúng revision và manifest hash; sửa payload hay đổi base làm mất hiệu lực phê duyệt cũ. Agent không tự cấp quyền phê duyệt bằng cách sửa status file.
- Một publisher có durable lease thực hiện xuất bản. Trước khi publish, kiểm tra lại `base_commit == HEAD`; nếu khác, chuyển `stale` và không áp dụng PR.
- Publisher tạo đầy đủ object/tree/commit mới, sau đó cập nhật `refs/main.json` theo compare-and-swap bằng ETag/điều kiện ghi được API hỗ trợ. Nếu cập nhật thất bại do HEAD thay đổi, không coi PR đã merge.
- Việc chuyển HEAD là điểm commit logic. Sau đó materialize cây mới vào `wiki/`; chỉ báo `merged` khi projection hoàn tất. Journal ghi lại tiến độ để tiếp tục sau crash, kể cả crash ngay sau khi chuyển HEAD.

SharePoint không cung cấp một giao dịch nguyên tử mặc định cho việc thay hàng loạt file Markdown. Người đọc trực tiếp `wiki/` có thể thấy trạng thái chuyển tiếp khi publisher đang cập nhật nhiều file. Agent luôn đọc snapshot qua HEAD. Nếu cả người đọc cũng cần thấy một phiên bản nguyên tử, cần reader giải quyết nội dung theo commit hoặc thư mục release bất biến; đây là lựa chọn sản phẩm cần chốt trước triển khai.

## Đồng bộ và quyền

- Cron là cơ chế recovery nền; có thể bổ sung Graph delta/webhook để giảm độ trễ. Không giả định thông báo chỉ đến một lần hoặc theo thứ tự.
- Mỗi lần chạy xử lý có giới hạn, retry với backoff và hướng dẫn throttling của API; lưu cursor/checkpoint bền vững. Kiểm tra lại các PR còn dở sau restart.
- Worker lưu trạng thái, lease và journal trong kho bền vững; MVP một tiến trình có thể dùng SQLite trên volume riêng, không đặt file SQLite đang mở trong folder SharePoint sync.
- Nhân viên đọc wiki và tạo contribution; vùng snapshot/ref/status và quyền xuất bản thuộc worker. Quyền sửa bản wiki chính thức nên giới hạn để mọi thay đổi đi qua PR.
- Nếu bắt buộc hỗ trợ sửa trực tiếp `wiki/`, cần luồng import thay đổi thành commit riêng và phát hiện drift trước publish. Chưa bao gồm trong MVP; không được âm thầm ghi đè sửa tay.
- Phân quyền contributions phải tránh người khác sửa proposal đã submit. Worker đóng băng revision vào object store khi tiếp nhận; approval luôn gắn với hash của bản đóng băng.

## MVP đề xuất

1. Công cụ/API agent: `get_head`, `read_snapshot`, `submit_pr`, `get_pr_status`.
2. Snapshot store và lệnh import wiki hiện có thành commit gốc. Tạo snapshot ban đầu trong cửa sổ không sửa tài liệu hoặc kiểm tra lại metadata/version để loại lần đọc bị thay đổi giữa chừng.
3. Manifest PR, validator, cron worker và trạng thái bền vững.
4. Thao tác review/approve/reject qua CLI hoặc HTTP đã xác thực; publisher duy nhất, conditional HEAD update và crash recovery.
5. Kiểm tra liên kết Markdown và báo cáo thay đổi; không tự xử lý bất đồng về kiến thức.

Chưa làm: Git protocol, branch tùy ý, merge ba chiều, giải quyết knowledge conflict, giao diện review phong phú, tìm kiếm ngữ nghĩa, tự duyệt bằng LLM và thu gom object cũ. Giữ toàn bộ snapshot trong MVP để PR cũ luôn tái lập được.

## Tiêu chí kiểm chứng

- Agent đọc lại một commit cũ vẫn nhận đúng nội dung dù HEAD đã đổi.
- Hai PR cùng base: PR thứ hai trở thành stale sau khi PR thứ nhất publish.
- Worker chạy lặp hoặc nhận sự kiện trùng không xuất bản hai lần.
- Crash trước/sau cập nhật HEAD và giữa materialization đều khôi phục đúng từ journal.
- Payload thiếu, thay sau submit, path traversal và approval sai revision đều bị chặn.
- PR nhiều file được kiểm tra link trên toàn bộ cây kết quả; rename không bỏ sót link trong phạm vi checker hỗ trợ.
- Thay đổi trực tiếp ngoài luồng được phát hiện và dừng publish thay vì ghi đè.

## Cần chốt khi bắt đầu triển khai

- Wiki hiện được đọc bằng SharePoint, file sync hay một Markdown viewer? Cách render và resolve link khác nhau giữa các kênh.
- Có thể giới hạn quyền sửa wiki chính thức và yêu cầu mọi thay đổi đi qua agent/PR không?
- Worker chạy ở đâu, dùng danh tính app hay delegated access, ai được review và phạm vi site/library nào được cấp quyền?
- Quy mô wiki, loại attachment và mức chấp nhận trạng thái chuyển tiếp của bản `wiki/`.

Các hành vi Microsoft Graph cụ thể như conditional write, upload, metadata danh tính, delta và quyền theo site/library cần được xác minh với tài liệu API chính thức và tenant đích trước khi chọn endpoint/SDK. Thiết kế này chưa khẳng định endpoint nào có sẵn đầy đủ các đặc tính đó.
