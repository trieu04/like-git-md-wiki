 1. Skill (của reviewer hệ thống) cần tường minh các logic và việc xử lý
  - Chia bố cục skill hợp lý
      - Cách dùng worker
      - Cách merge file
      - Luật approve
      - Luật reslove conflic
      - Sử dụng các metadata để reslove: người dùng, chức vụ, expert (expert là chuyên môn của author), ...
 
  2. Track change
  - Nên lưu lại các change
  - Cần thêm api để agent nhìn thấy các version
 
  3. Định nghĩa logic và skill cho từng logic cụ thể
  - logic slate/conflic: cả 2 user đều sửa cùng 1 file, khi merge thì file version tăng 1, user 2 có target là
  version cũ, slate/conflic xảy ra.
 