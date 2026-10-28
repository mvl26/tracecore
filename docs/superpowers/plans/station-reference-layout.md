# Khung giao diện trạm T1–T8

**Goal:** Khớp bố cục ảnh người dùng cung cấp ngày 28/10/2026 trong Page station hiện có.

**Architecture:** Giữ nguyên controller và RPC của mỗi trạm. Bổ sung rail, breadcrumb, dải bước và trạng thái kết nối vào shell dùng chung; actions bar chừa chiều rộng rail. Không tạo DocType, không đổi quyền, không giả lập dữ liệu mẫu của ảnh.

**Constraints:** Frappe v15; tokens `--tc-*`; STN control >=48, primary >=56; tiếng Việt qua translations; không E2E, commit, merge hoặc PR. Giữ thay đổi tiêu đề Khoa gửi dụng cụ đã có. Không ghi đè checkout WSL đang có công việc khác.

## Task 1 — Khung shell (FR-M9-14, NFR-USAB-01, NFR-ACC-01)
- [x] Test FrappeTestCase cho rail, breadcrumb, progress và nội dung phiên không trùng ID.
- [x] Chạy test thấy fail trước khi sửa template (5 subtest thiếu landmark).
- [x] Đưa thông tin phiên sang rail; giữ nguyên selector và hành vi đăng nhập/đăng xuất.
- [x] CSS rail desktop, responsive dưới breakpoint stack, actions bar chừa chiều rộng rail; cần kiểm tra trực quan runtime.

## Task 2 — Navigation và thông tin thật (FR-M9-03, FR-M9-14, NFR-SEC-07)
- [x] Người dùng đổi quyết định ngày 28/10/2026: menu đủ T1–T8 và T5b như ảnh; mục không có quyền hiển thị khóa. Ghi Amendment STN-NAV-02 trong ux-foundations.md và design.md.
- [x] Lấy cấu hình trạm thật qua navigation.context(station, all_stations=1); không hard-code mã TR hay thẻ nhân viên mẫu. Metadata menu cho TC role không cấp quyền đọc/sửa cấu hình Zone Station; controller tại đích vẫn kiểm quyền/năng lực.
- [x] Dải bước chỉ đánh dấu bước hiện tại, không suy diễn cổng đã Đạt.
- [x] Trạng thái mạng và số chờ đồng bộ từ outbox; không khẳng định năng lực còn hạn nếu server không cung cấp.

## Task 3 — Verification
- [ ] Chạy FrappeTestCase shell, JS regression phiên trạm và lint/architecture.
- [ ] Kiểm tra layout qua trình duyệt nếu runtime có thể phục vụ đúng checkout; không chạy Playwright.
- [ ] Báo kết quả thật và phần còn thiếu; giữ chưa commit cho người dùng kiểm tra.

## Bằng chứng ngày 28/10/2026

- FrappeTestCase mới: 2/2 pass; regression test_station_page: 24/24 pass.
- JS station_auth: 22/22 pass.
- Diff coverage Python navigation.py: 8/9 dòng, 88,9%; không đo coverage JS/CSS bằng số này.
- Architecture và BRU marker checks pass; không chạy E2E.
- Site đang chạy chưa cập nhật: checkout bench khác nhánh và có thay đổi admin UI chưa commit. Chưa kiểm tra trực quan bản này trên trình duyệt.
