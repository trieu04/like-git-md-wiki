# Mô hình tri thức dài hạn — tài liệu tham khảo

Đây là bản thiết kế trước khi thu gọn phạm vi. Không phải đặc tả Phase 1. [README](../README.md), [thiết kế](design.md) và [implementation plan](implementation-plan.md) có ưu tiên. Các mục mang tên “phase nền tảng” bên dưới chỉ ghi lại đề xuất cũ; claim graph, event sourcing, policy engine và truy vấn hai trục thời gian chưa được cam kết triển khai.

## Mục tiêu

Nhiều người và nhiều AI agent cùng đóng góp vào một knowledge base dạng graph, được biểu đạt bằng tài liệu Markdown liên kết nhau trên Microsoft 365 SharePoint. Giai đoạn này chuẩn bị cấu trúc, ngữ cảnh và trách nhiệm để sau này phát hiện mâu thuẫn, đánh giá nguồn, phân xử theo domain, đánh giá quan hệ và làm sạch tri thức.

Đây là thiết kế nền tảng để thảo luận, chưa phải hệ thống được triển khai. Git gợi ý cách giữ snapshot và đề xuất thay đổi; nó không cung cấp mô hình về sự thật, thẩm quyền hay hiệu lực của kiến thức. SharePoint cung cấp môi trường cộng tác và lưu trữ.

**Đơn vị quản lý là phát biểu và quan hệ có provenance, được đề xuất và quyết định trong ngữ cảnh cụ thể.** File là đơn vị trình bày và vận chuyển. Một file có nhiều claim; một claim có thể xuất hiện trong nhiều file.

## Các bất biến

1. Danh tính ổn định khác phiên bản nội dung. Đổi tên tài liệu không đổi ID; sửa nghĩa claim tạo revision hoặc claim mới với lineage rõ ràng.
2. Tiếp nhận contribution không đồng nghĩa chấp nhận claim. Đánh giá của agent không tự trở thành quyết định có thẩm quyền.
3. Claim, nguồn, quan hệ, assessment và decision là những đối tượng riêng.
4. Giữ lịch sử bất biến theo mặc định; trạng thái hiện tại được dựng từ sự kiện và quyết định. Xóa bắt buộc theo chính sách dữ liệu là ngoại lệ có audit; không hứa tái lập nội dung đã xóa.
5. Cho phép unknown. Không tự suy ra thời gian hiệu lực, tác giả gốc, domain owner hoặc độ tin cậy.
6. Mỗi assessment gắn với phiên bản đầu vào, phương pháp và phạm vi cụ thể. Không tự mang đánh giá cũ sang revision mới.
7. Các claim mâu thuẫn có thể cùng tồn tại trong kho. View theo chính sách quyết định điều gì được trình bày là kiến thức đang áp dụng.

## Mô hình khái niệm

| Đối tượng | Vai trò và dữ liệu cốt lõi |
| --- | --- |
| Document / Revision | ID ổn định, blob hash, path hiện tại, anchors và ánh xạ claim |
| Claim / Revision | Phát biểu nguyên văn, ngôn ngữ, scope, điều kiện áp dụng, domain và valid time được khai báo; cấu trúc subject/predicate/object tùy chọn |
| Source / Revision | Nguồn gốc, người/tổ chức phát hành nếu biết, URI, thời điểm truy xuất, bản lưu hoặc fingerprint, giới hạn truy cập |
| EvidenceBinding | Claim revision → source revision, đoạn trích/locator và vai trò được khai báo: hỗ trợ, phản bác hoặc bối cảnh |
| Relation / Revision | ID riêng, loại, chiều, endpoints, scope, provenance; endpoints là claim phải chỉ rõ revision |
| Contribution / Revision | Ý định, delta, base snapshot, read/write sets, người gửi, agent run và lý do |
| Assessment | Target revisions, evaluator, method/version, inputs, findings, evidence, thời gian và giới hạn |
| Decision | Target revisions, hành động, người quyết định, domain/scope, lý do, policy revision và hiệu lực |
| AuthorityPolicy | Domain, vai trò, quyền quyết định, ủy quyền, escalation, thời gian hiệu lực |
| Event / Snapshot | Lịch sử ghi nhận; snapshot cố định nội dung, graph, quyết định và policy tại một mốc |

Không cần graph database ngay. Record có ID và quan hệ rõ ràng có thể nằm trong JSON; index là projection dựng lại được. ID ổn định định danh đối tượng; hash định danh nội dung revision. Hai claim giống văn bản vẫn có thể khác scope và nguồn gốc, không được tự đồng nhất bằng text hash.

## Markdown và graph

Markdown tiếp tục là cách con người đọc và viết; sidecar metadata giữ ID, mapping và quan hệ có cấu trúc.

- Link Markdown ban đầu chỉ là `links_to`, không tự có nghĩa `supports`, `causes` hoặc `contradicts`.
- Mapping claim tham chiếu document revision và anchor/đoạn trích có hash. Line number chỉ phục vụ hiển thị; anchor không resolve đúng thì mapping cần kiểm tra.
- Document revision mới không tự cập nhật claim cũ. Agent hoặc người đóng góp đề xuất mapping mới; phần chưa được phân tích mang trạng thái `unmapped`.
- Claim extraction là một đề xuất có provenance. Import wiki cũ không tự biến mọi câu thành claim được chấp nhận.
- Thay Markdown và sidecar trong cùng contribution; validator phát hiện mapping trỏ sai revision.

Không ép tri thức thành bộ ba ngay lập tức. Giữ nguyên văn, qualifier và đoạn nguồn để không mất nghĩa; cấu trúc hóa có thể được bổ sung sau.

## Provenance và thời gian

Phân biệt người gửi đã xác thực, người yêu cầu/ủy quyền nếu có, agent thực thi, người phát biểu gốc trong nguồn và người quyết định. Không gộp thành một trường `author`; người yêu cầu agent không mặc nhiên endorse đầu ra.

AgentRun lưu agent identity, phiên bản cấu hình/công cụ/model nếu có, input revisions, nguồn truy xuất và output hashes. Lưu chỉ dẫn phù hợp chính sách dữ liệu, không cần suy luận nội bộ. Metadata hỗ trợ truy vết, không bảo đảm tái tạo nguyên xi đầu ra mô hình.

Hai trục thời gian độc lập:

- **Valid time:** phát biểu/quyết định áp dụng cho giai đoạn nào trong domain.
- **Recorded time:** hệ thống ghi nhận thông tin khi nào, dùng thời gian phía dịch vụ.

Ngày công bố và ngày truy xuất nguồn là metadata riêng. Khoảng hiệu lực chưa biết khác khoảng mở vô hạn. Sửa sai hồi tố phải giữ lịch sử hệ thống từng biết gì. Truy vấn cần phân biệt “theo những gì biết tại ngày X” với “áp dụng cho ngày Y”.

Nếu không thể lưu nguồn vì quyền hoặc bản quyền, ghi locator/fingerprint và giới hạn tái lập. Nguồn được agent dẫn lại phải giữ chuỗi derivation nếu biết; nhiều agent lặp lại một nguồn không trở thành nhiều bằng chứng độc lập.

## Đóng góp, đánh giá và quyết định

```text
Người / agent -> Contribution + context snapshot
                         |
                Kiểm tra cấu trúc và quyền
                         |
                Ghi nhận đối tượng ứng viên
                         |
                Assessment có bằng chứng
                         |
                Decision theo authority policy
                         |
                View theo domain và thời gian -> Wiki Markdown
```

Vòng đời contribution (`submitted`, `validated`, `integrated`, `rejected`) độc lập với assessment (`pending`, `completed`, `outdated`) và disposition của claim. Claim đã được ghi nhận có thể chưa được đánh giá hoặc quyết định.

Disposition được tính theo domain/scope/time/policy: chưa có quyết định, được chấp nhận, bị tranh chấp hoặc bị rút lại. Không dùng boolean `approved` toàn cục. `archived` là trạng thái hiển thị/lưu trữ, không có nghĩa claim sai.

AuthorityPolicy có revision. Mỗi decision tham chiếu policy có hiệu lực lúc quyết định, quyền đã xác thực và phạm vi được phép. Policy đổi không viết lại lịch sử, nhưng có thể yêu cầu review lại. Domain chồng lấn hoặc chưa có owner chuyển sang chờ phân xử; không tự chọn người quyết định cuối cùng. Agent mặc định đề xuất/đánh giá, chỉ được quyết định khi policy ủy quyền rõ ràng.

## Chuẩn bị cho các khả năng tương lai

| Khả năng | Nền tảng giữ từ bây giờ | Chưa tự động hóa |
| --- | --- | --- |
| Semantic conflict detection | Claim revisions, scope/qualifier, valid time, nguồn, snapshot; issue tham chiếu nhiều claim | Phán định và giải quyết mâu thuẫn |
| Provenance & temporal validity | Đoạn nguồn có phiên bản, actor chain, hai trục thời gian, mức đầy đủ provenance | Suy luận nguồn đáng tin hoặc claim còn đúng |
| Authority & accountability | Domain/policy có revision; decision có người chịu trách nhiệm, rationale và phạm vi | Tự chọn owner hoặc trao quyền |
| Graph quality / edge evaluation | Quan hệ có kiểu/chiều/revision; assessment theo tiêu chí và evaluator | Điểm truth chung hoặc tự sửa hướng cạnh |
| Denoising lifecycle | Lineage, dependency index, hành động merge/supersede/archive/retract có lý do | Tự xóa/hợp nhất vì giống văn bản |

Điểm relation phải nói rõ đo gì: độ hỗ trợ của evidence, tính liên quan, độ mới hay confidence của detector. Lưu thang đo và method version; không cộng các điểm khác nhau khi chưa calibration. Registry loại quan hệ có phiên bản phải định nghĩa chiều và tính đối xứng; chiều cạnh không phải một điểm confidence.

Detector tạo assessment/issue với claim revisions, scope giao nhau, bằng chứng và giải thích. Một issue có thể bị bác bỏ bằng decision có lý do; nó không trực tiếp xóa claim hoặc biến quan hệ mâu thuẫn thành sự thật đã xác nhận.

## Denoising và tác động lan truyền

`merge` tạo đối tượng đích và giữ mapping từ ID cũ; `supersede` chỉ rõ thay thế trong scope/thời gian nào; `archive` đưa khỏi view mặc định; `retract` ghi nhận rút lại. Supersede không mặc nhiên có nghĩa claim trước chưa từng đúng.

Mỗi hành động đi qua proposal và decision có quyền tương ứng. Không âm thầm chuyển evidence, edge hoặc approval sang đối tượng mới. Dependency index trả lời “claim này đổi thì assessment, relation, decision và document nào bị ảnh hưởng?”. Đối tượng phụ thuộc được đánh dấu `needs_review`, không tự kết luận là sai.

Ví dụ: “giữ log 30 ngày” áp dụng trước 01/07 và “giữ log 90 ngày” áp dụng từ 01/07 khác nội dung nhưng không mâu thuẫn nếu thời gian không giao nhau. Nếu cùng áp dụng tháng 8, vẫn cần kiểm tra domain/điều kiện trước khi kết luận. Quyết định của domain owner phải giữ bằng chứng và lịch sử cả hai claim.

## Snapshot và cộng tác đồng thời

Snapshot cố định document tree, graph records, evidence references, policy revisions và mốc event ledger. Manifest có thể trỏ tới các cây bằng hash; chưa cần triển khai Merkle DAG đầy đủ. Phải lưu blob để truy xuất lại nội dung.

Contribution khai báo `base_snapshot`, `read_set` với revision chính xác, `write_set` với expected revisions và nguồn ngoài. Read set là ngữ cảnh được khai báo đã dùng, không chứng minh agent đã hiểu đầy đủ.

Hai đề xuất độc lập có thể cùng được ghi nhận. Khi áp dụng delta, kiểm tra revision đối tượng bị sửa; khi ra decision, kiểm tra thêm policy, evidence và dependencies được khai báo. Đầu vào đổi tạo `needs_revalidation`, không gọi là semantic conflict. Không bắt mọi contribution stale chỉ vì một tài liệu không liên quan đổi.

Read set không phát hiện claim mới xuất hiện hoặc quan hệ ngữ nghĩa chưa biết. Không có xung đột ghi không bảo đảm không có mâu thuẫn kiến thức. Assessment phải giữ snapshot graph/domain để biết phạm vi lần đánh giá.

Triển khai đầu tiên có thể dùng một coordinator tuần tự hóa ghi nhận và quyết định; các agent vẫn đọc, đề xuất, đánh giá đồng thời. Event có idempotency key và thứ tự do coordinator cấp; projection có checkpoint, dựng lại được. Không dùng thứ tự file sync hoặc timestamp máy cá nhân làm thứ tự quyết định.

## SharePoint và ranh giới lưu trữ

```text
wiki/                 Markdown cho người đọc
contributions/        Bundle đề xuất, suffix báo sẵn sàng tiếp nhận
knowledge/
  objects/            Nội dung/revision bất biến, graph records, evidence
  snapshots/          Manifest cố định revision và mốc lịch sử
  events/             Contribution, assessment, decision, lifecycle events
  policies/           Authority policy revisions
  views/              Projection/index dựng lại được, checkpoint
```

Đây là cấu trúc logic, chưa chốt schema vật lý. Cron chỉ tiếp nhận, kiểm tra và điều phối; `.ready` không có nghĩa claim đã duyệt. Một publisher xuất bản view Markdown; nhiều evaluator có thể bổ sung assessment.

Record authoritative phải tách khỏi projection. Quyền ghi bảo vệ lịch sử; hash không ngăn người có quyền sửa cả nội dung và hash. Graph/index/view không được làm lộ dữ liệu vượt quyền nguồn; snapshot tuân thủ chính sách giữ/xóa dữ liệu và thu hồi quyền của công ty.

Chi tiết vận chuyển và giới hạn xuất bản nhiều file được giữ trong [phác thảo SharePoint](sharepoint-transport-draft.md). Hành vi Microsoft Graph phải được xác minh trước triển khai. Snapshot logic không đồng nghĩa cập nhật nhiều file hiển thị trên SharePoint là nguyên tử.

## Phạm vi phase nền tảng

1. ID/revision, schema version, canonical hashing và snapshot truy xuất được.
2. Document, claim, relation, source/evidence và mapping; chấp nhận phần chưa cấu trúc hóa.
3. Contribution, actor/agent provenance, read/write sets và kiểm tra concurrency.
4. Assessment/Decision riêng biệt; authority policy tối thiểu và kiểm tra quyền phía dịch vụ.
5. Event ledger, projection, truy vấn thời gian và dependency invalidation.
6. Lifecycle events thủ công; chưa có thuật toán tự phân xử hoặc denoising.

Hợp đồng evaluator tương lai: nhận snapshot và target revisions; trả assessment có inputs, method/version, findings, evidence, limitations. Evaluator không sửa trực tiếp claim hoặc view chính thức. Có thể bổ sung semantic detector và edge scorer mà không thay mô hình trách nhiệm/lịch sử.

Chưa chọn graph database, framework agent, thuật toán so sánh ngữ nghĩa, điểm chất lượng chung hoặc ontology domain hoàn chỉnh. Các lựa chọn này cần dữ liệu thực tế.

## Tình huống kiểm chứng thiết kế

- Rename giữ ID, mapping và lịch sử nguồn.
- Hai agent dẫn cùng nguồn không được tính thành hai bằng chứng độc lập.
- Claim giống chữ nhưng khác scope/time không bị tự hợp nhất.
- Tiếp nhận contribution không tự chấp nhận claim; confidence cao không vượt authority.
- Nguồn hoặc revision đổi làm assessment liên quan cần review; kết quả cũ vẫn truy xuất được.
- Quyết định hồi tố trả đúng cả “khi đó biết gì” và “hiện nay cho rằng khi đó áp dụng gì”.
- Merge/supersede giữ lineage, không tự chuyển approval/evidence.
- Retry không nhân đôi event; dựng lại projection cho cùng snapshot/policy/query time cho cùng kết quả.
- Người không có quyền domain không thể quyết định bằng cách sửa manifest.
- Nguồn hạn chế hoặc buộc xóa không bị lộ qua index; giới hạn tái lập được thể hiện rõ.

Bước tiếp theo là kiểm nghiệm mô hình với tình huống tri thức thực của công ty trước khi chốt schema v1, đặc biệt ranh giới claim, domain chồng lấn, thời gian hiệu lực và quyền quyết định từng loại hành động.
