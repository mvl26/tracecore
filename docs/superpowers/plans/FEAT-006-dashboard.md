# FEAT-006 Dashboard vận hành theo vai trò và tìm kiếm danh sách — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** R01/R02 (và R09, R10 theo phạm vi) mở một màn "Tổng quan hôm nay" (SCR-32) thấy trên một trang: số bộ theo trạng thái, sản lượng theo trạm / người / máy trong ngày–tuần–tháng, tỷ lệ mẻ lỗi, tồn vô khuẩn, gói sắp hết hạn, và các cảnh báo cần xử lý (cơ số, đề nghị ghi đè chờ duyệt, thu hồi chưa xác nhận, chứng chỉ, kiểm định / máy khóa, tồn kho). Số liệu tự làm mới ≤ 60 giây, chỉ số không có dữ liệu hiện 0. Mọi danh sách nghiệp vụ trên Desk có ô quét mã làm phím tắt tìm kiếm (FR-M9-13).

**Architecture:** Page Desk mới `tc-dashboard` (module UI) theo mẫu Page `notifications` (4 trạng thái, kiểm request cũ, token `--tc-*`). Dịch vụ tổng hợp `tracecore/admin_reports/dashboard.py` (M9) chỉ truy vấn DocType bằng tên (không import module khác). RPC `tracecore.v1.dashboard.summary` (GET) ở lớp `v1` ghép kết quả M9 với các dịch vụ sẵn có: `reprocessing.storage.overview`, `equipment.daily_test.overview`, `inventory.alerts.overview`, `par.check` (danh sách). Mỗi khối chỉ trả khi người dùng có quyền đọc DocType nguồn. Ô quét danh sách là script chung trong `tracecore.bundle.js`. Không DocType mới.

**Tech Stack:** Frappe v15 Page + JS thuần, Python 3.11. Không chạy E2E trừ khi được bảo.

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-006; `docs/srs.md` FR-M9-01, FR-M9-01.1, FR-M9-01.2, FR-M9-13; `docs/use-cases.md` UC-32; `docs/ux-foundations.md` SCR-32 (anchor "Tổng quan hôm nay"); `docs/design.md` §4.6 KPI tile, §4.7 alert, §4.10 data table; `docs/architecture.md` §8 (dashboard 60 s, fallback polling).

FR/BRU đáp ứng: FR-M9-01, FR-M9-01.1, FR-M9-01.2, FR-M9-13. Không có BRU gắn FEAT này.

**Nhánh:** `feat/FEAT-006-dashboard` cắt từ `develop` (a1c17ba), bench riêng `~/tracecore-f006` (site test `test_f006`). Số amendment: **A-54** (A-53 là FEAT-046 đang làm song song).

## Quyết định cần duyệt

**[Chốt]** = tài liệu thiếu hoặc mâu thuẫn, cần người duyệt. **[Xác nhận]** = lựa chọn thiết kế trong phạm vi tài liệu.

| # | Loại | Câu hỏi | Phương án trong plan | Căn cứ |
| :- | :- | :- | :- | :- |
| D1 | [Chốt] | Dựng SCR-32 bằng gì | implementation-plan ghi "Frappe Workspace + Dashboard Chart + Script Report". Plan dùng **Page Desk `tc-dashboard`** (giống `notifications`, `competency-matrix`) vì Workspace/Dashboard Chart không làm được: khối theo vai trò, KPI tile 3 biến thể và alert có nút hành động (design §4.6–4.7), 4 trạng thái màn (FR-M9-14), làm mới 60 s một lần cho cả trang. Vẫn trong ADR-002 (Desk, không SPA). Launcher thêm link "Tổng quan hôm nay" đứng đầu cho R01/R02/R09/R10. | design §4.6–4.7; ADR-002 |
| D2 | [Chốt] | Khối theo vai trò | **R01, R02, System Manager:** tất cả khối. **R09:** tồn vô khuẩn, gói sắp hết hạn, cảnh báo tồn kho, cơ số. **R10:** máy (khóa, kiểm định / hiệu chuẩn sắp hạn), chứng chỉ. Ngoài ra mỗi khối chỉ trả khi người dùng đọc được DocType nguồn (`frappe.has_permission`). KTV (R03–R08) không vào Page này. | FR-M9-01 "theo vai trò"; UC-32 actors |
| D3 | [Chốt] | Số bộ theo trạng thái | Đếm `Set Unit.status` đủ 10 giá trị (New … Returned), thiếu thì 0; không tính bộ Disposed vào tổng "đang lưu hành". Click tile → List View Set Unit lọc trạng thái đó. | FR-M9-01, .2 |
| D4 | [Chốt] | Sản lượng theo trạm / người / máy | Kỳ = Hôm nay / Tuần này (T2–CN) / Tháng này theo giờ hệ thống. **Trạm:** số `Step Gate Result` kết quả Đạt theo `station`. **Người:** như trên theo `recorded_by` (User → tên). **Máy:** số `Wash Batch` + `Sterilization Load` theo `equipment`, `started_at` trong kỳ. Mỗi bảng 10 dòng đầu, sắp giảm dần. Không theo ca (báo cáo `Station Output` của FEAT-037 vẫn dùng cho ca). | FR-M9-01; UC-32 bước 2 |
| D5 | [Chốt] | Tỷ lệ mẻ lỗi | Trong kỳ: `Sterilization Load` có `status` Failed ÷ mẻ đã kết thúc (`status` ∈ Released, Failed, Quarantine); tương tự `Wash Batch` Failed ÷ (Passed + Failed). Hiện hai tỷ lệ riêng kèm số mẻ ("2/40 mẻ, 5 %"). Không có mẻ → "0 %". Tile chuyển warn khi > 0 %, alert khi ≥ 5 %. | FR-M9-01, .2 |
| D6 | [Xác nhận] | Tồn vô khuẩn, gói sắp hết hạn | Dùng `reprocessing.storage.overview()`: tổng gói `In Sterile Stock`, nhóm theo loại bộ; "sắp hết hạn" = 7 ngày (`EXPIRING_DAYS` sẵn có của FEAT-025), 10 gói gần hạn nhất. | FEAT-025 |
| D7 | [Chốt] | Danh sách "Cần xử lý" (alert có nút) | (1) `Par Override` Requested → "Xem và duyệt" (mở form); (2) `Recall Order` Open có `confirmed_count < pack_count` → "Theo dõi"; (3) bộ cơ số warn/blocked từ `par.check`; (4) máy Locked / Repair, kiểm định – hiệu chuẩn hết hạn trong 30 ngày (`equipment.daily_test.overview` + `inspection_due`/`calibration_due`); (5) chứng chỉ Valid hết hạn trong 60 ngày hoặc Expired, nhân viên đang làm; (6) tồn kho dưới tối thiểu, lô hết hạn 30 ngày (`inventory.alerts.overview`). Mỗi loại: số đếm + 5 dòng đầu + link "Xem tất cả". | FR-M9-01; ux-foundations luồng SCR-32 → SCR-31, SCR-14 |
| D8 | [Xác nhận] | Bộ lọc | Kỳ (ngày/tuần/tháng), khu (`Zone Station` is_zone), máy; khoa áp cho bộ theo trạng thái và gói. Lọc lưu theo người dùng trong `localStorage` (chỉ tiện ích). | UC-32 bước 2 |
| D9 | [Chốt] | Làm mới ≤ 60 s (FR-M9-01.1) | Không có sự kiện realtime nào phát khi trạng thái đổi. Plan dùng **polling 60 s khi Page đang hiện** (dừng khi rời trang / tab ẩn), cộng làm mới khi nhận `tc_notification`. Hiện "Cập nhật lúc hh:mm:ss". Không thêm sự kiện socketio mới (tránh sửa mọi chỗ đổi trạng thái). | architecture §8 "fallback polling" |
| D10 | [Xác nhận] | Không dữ liệu → 0 (FR-M9-01.2) | Mọi tile và tỷ lệ trả số 0, bảng rỗng hiện "Không có dữ liệu — …" (design §4.10), không ẩn khối. | FR-M9-01.2 |
| D11 | [Chốt] | FR-M9-13 tìm/lọc/sắp xếp/phân trang | Frappe List View đã có tìm, lọc theo trường, sắp xếp, phân trang; giữ nguyên. Thêm **ô quét chung** trên List View các DocType TraceCore (Set Unit, Pack, Sterilization Load, Wash Batch, Dirty Receipt, Issue Note, Usage Record, Instrument, Equipment, Recall Order, Incident CAPA, Par Override, Item, Batch): phím `/` focus, quét/nhập Enter → nếu mã khớp đúng một bản ghi của DocType đó (theo `name` hoặc trường mã: Set ID, Cycle ID, mã máy, mã lô) thì mở form, nếu không thì lọc List View theo mã. RPC `tracecore.v1.dashboard.find_in_list(doctype, code)` (GET) kiểm quyền đọc. | FR-M9-13; design §4.10 "ô quét làm phím tắt tìm (focus `/`)" |
| D12 | [Chốt] | Ngoài phạm vi | Sổ tiệt khuẩn, báo cáo KSNK mẫu BYT, dự báo thay dụng cụ, dấu "Tạm" kỳ chưa khóa (UC-32 bước 3–5, E2 → **FEAT-007**); chi phí/bộ (→ **FEAT-046**); khối chất thải FR-M10-07.1 (→ **FEAT-049/050**); email báo cáo hằng ngày (UC-32 A2); dashboard trạm cho KTV theo khu (UC-32 A1, launcher trạm đã có); xuất Excel > 50.000 dòng (E3, các khối dashboard không xuất). Kg đồ vải theo khoa (FEAT-033 L11) chỉ thêm nếu D2 có R07, plan **không** thêm. | UC-32; FEAT-007/046/049 |
| D13 | [Xác nhận] | Hiệu năng (NFR-PERF-03 ≤ 3 s) | Truy vấn gộp `GROUP BY`, không lặp từng bản ghi; `par.check` gọi với `limit=50`; test đo số truy vấn không tăng theo số bộ. Kết quả cache theo (người dùng, bộ lọc) 30 s trong Redis. | NFR-PERF-03 |

## File structure

- Tạo: `tracecore/admin_reports/dashboard.py` (đếm trạng thái, sản lượng, tỷ lệ lỗi, đề nghị ghi đè, thu hồi, chứng chỉ), `tracecore/v1/dashboard.py` (`summary`, `find_in_list`), `tracecore/ui/page/tc_dashboard/` (`tc_dashboard.json/.js/.css`), `tracecore/public/js/tc_list_scan.js`.
- Tạo tests: `tracecore/admin_reports/tests/test_dashboard.py`, `tracecore/v1/tests/test_dashboard_api.py`, `tracecore/ui/page/tc_dashboard/test_tc_dashboard.py` (tài sản Page: chuỗi dịch, token, 4 trạng thái, polling).
- Sửa: `tracecore/public/js/tracecore.bundle.js` (import `tc_list_scan`), `tracecore/v1/navigation.py` (link "Tổng quan hôm nay"), `tracecore/ui/page/tracecore/test_tracecore.py`, `translations/vi.csv`, `docs/architecture.md` (A-54), `docs/rtm.md`, `docs/implementation-plan.md` (ghi chú D1).

## Tasks

- [ ] **Task 0 — Amendment A-54 và tài liệu** (D1–D13): Revision History `architecture.md`, ghi chú cột kỹ thuật FEAT-006 trong implementation-plan.
- [ ] **Task 1 — Dịch vụ M9 `admin_reports.dashboard`** (FR-M9-01, .2; D3–D5, D7(1,2,5), D10): `set_status_counts(department)`, `output_by_station / by_user / by_equipment(period, zone, equipment)`, `failure_rates(period, equipment)`, `pending_overrides()`, `open_recalls()`, `expiring_certificates(days=60)`, `period_range(period)`. TDD từng hàm: đủ trạng thái kể cả 0, kỳ ngày/tuần/tháng theo múi giờ hệ thống, không mẻ → 0 %.
- [ ] **Task 2 — RPC `tracecore.v1.dashboard.summary`** (FR-M9-01; D2, D6, D7, D13): GET, chặn Guest, ghép khối theo vai trò + `has_permission`, gọi `storage.overview`, `daily_test.overview`, `inventory.alerts.overview`, `par.check`; cache 30 s; test vai trò (R01 đủ khối, R09/R10 đúng phạm vi, R04 bị từ chối), test số truy vấn.
- [ ] **Task 3 — Page `tc-dashboard`** (SCR-32; FR-M9-01.1; D1, D8–D10): KPI tile, alert có nút, bảng sản lượng, bộ lọc, 4 trạng thái, polling 60 s khi hiện, `tc_notification`; chuỗi qua `__()` có context, CSS chỉ `--tc-*`; test tài sản tĩnh như các Page khác.
- [ ] **Task 4 — Ô quét trên List View** (FR-M9-13; D11): `find_in_list` (GET, quyền đọc, mã khớp đúng một bản ghi → trả tên), `tc_list_scan.js` gắn vào List View các DocType trong D11, phím `/`.
- [ ] **Task 5 — Launcher, dịch, kiểm tra**: link "Tổng quan hôm nay", `vi.csv` (dòng có context, không ghi đè frappe), `rtm.md`, lint, coverage changed-code ≥ 70 %, chạy module liên quan, ghi chú hiện thực.

## Acceptance criteria (EARS) và test

| AC | Nội dung | Test |
| :- | :- | :- |
| AC-1 | Khi R01/R02 mở dashboard, hệ thống hiện số bộ theo trạng thái, sản lượng theo trạm/người/máy, tỷ lệ mẻ lỗi, tồn vô khuẩn, gói sắp hết hạn và các cảnh báo trên một màn (FR-M9-01) | `test_dashboard_api` R01 đủ khối |
| AC-2 | Khi người dùng đổi kỳ ngày/tuần/tháng, sản lượng và tỷ lệ lỗi tính theo kỳ đó (UC-32 bước 2) | `test_dashboard` kỳ |
| AC-3 | Trong khi dashboard mở, số bộ theo trạng thái được làm mới ≤ 60 s (FR-M9-01.1) | test tài sản Page: interval ≤ 60000, dừng khi ẩn |
| AC-4 | Nếu chỉ số không có dữ liệu, hệ thống hiện 0 (FR-M9-01.2) | `test_dashboard` site rỗng → 0 |
| AC-5 | Người dùng chỉ thấy khối mình có quyền (D2) | test R09/R10/R04 |
| AC-6 | Khi người dùng quét mã trong ô quét của danh sách, hệ thống mở bản ghi khớp hoặc lọc danh sách (FR-M9-13) | `test_dashboard_api` `find_in_list` + test tài sản `tc_list_scan.js` |

## Ghi chú hiện thực

_(điền khi xong)_
