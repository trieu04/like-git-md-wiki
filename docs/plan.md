# Plan

## 1. Kiểm chứng điều kiện tối thiểu

Chọn một folder thử nghiệm và người phụ trách. Kiểm tra kênh đọc Markdown, quyền ghi wiki/history, danh tính người gửi/người duyệt, conditional update/create trên SharePoint. Ghi bằng chứng API đã thử; thiếu điều kiện chống ghi đè hoặc xác thực thì chưa publish thật.

## 2. Xây một luồng hoàn chỉnh

Submit bundle một file, xem diff và file cuối cùng, review, publish có điều kiện và giữ lịch sử. Kiểm tra retry/crash ngay trong luồng này; ca ghi chưa rõ kết quả dừng để người phụ trách kiểm tra. Chưa tự động hóa mọi tình huống phục hồi hoặc mở rộng sang graph.

## 3. Pilot nhỏ

Thử với vài tài liệu, người và agent thực tế. Đo thủ công: đề xuất chờ bao lâu, sửa sai mất bao lâu và lỗi nào lọt qua review. Diễn tập sửa/khôi phục nội dung sai và worker restart.

## 4. Chỉ mở rộng từ vấn đề quan sát được

- Backlog review tăng: cải thiện cách review hoặc thêm reviewer trước khi thêm agent.
- Thường xuyên sửa nhiều file cùng nhau: cân nhắc bundle nhiều file.
- Hay bỏ quên review: thêm reminder/due date.
- Mâu thuẫn tại những đoạn cụ thể: thử claim/section assessment trên phạm vi đó.

Mỗi lần thêm tính năng phải nêu vấn đề thực tế, cách đơn giản nhất để xử lý và tiêu chí kiểm chứng. Tài liệu dài hạn không tự trở thành yêu cầu MVP.
