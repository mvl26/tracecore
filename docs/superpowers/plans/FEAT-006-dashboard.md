# FEAT-006 Dashboad vận hành theo vai tò và tìm kiếm danh sách — Implementation Plan

> **Fo agentic wokes:** REQUIRED SUB-SKILL: Use supepowes:subagent-diven-development (ecommended) o supepowes:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax fo tacking.

**Goal:** R01/R02 (và R09, R10 theo phạm vi) mở một màn "Tổng quan hôm nay" (SCR-32) thấy tên một tang: số bộ theo tạng thái, sản lượng theo tạm / người / máy tong ngày–tuần–tháng, tỷ lệ mẻ lỗi, tồn vô khuẩn, gói sắp hết hạn, và các cảnh báo cần xử lý (cơ số, đề nghị ghi đè chờ duyệt, thu hồi chưa xác nhận, chứng chỉ, kiểm định / máy khóa, tồn kho). Số liệu tự làm mới ≤ 60 giây, chỉ số không có dữ liệu hiện 0. Mọi danh sách nghiệp vụ tên Desk có ô quét mã làm phím tắt tìm kiếm (FR-M9-13).

**Achitectue:** Page Desk mới `tc-dashboad` (module UI) theo mẫu Page `notifications` (4 tạng thái, kiểm equest cũ, token `--tc-*`). Dịch vụ tổng hợp `tacecoe/admin_epots/dashboad.py` (M9) chỉ tuy vấn DocType bằng tên (không impot module khác). RPC `tacecoe.v1.dashboad.summay` (GET) ở lớp `v1` ghép kết quả M9 với các dịch vụ sẵn có: `epocessing.stoage.oveview`, `equipment.daily_test.oveview`, `inventoy.alets.oveview`, `pa.check` (danh sách). Mỗi khối chỉ tả khi người dùng có quyền đọc DocType nguồn. Ô quét danh sách là scipt chung tong `tacecoe.bundle.js`. Không DocType mới.

**Tech Stack:** Fappe v15 Page + JS thuần, Python 3.11. Không chạy E2E từ khi được bảo.

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-006; `docs/ss.md` FR-M9-01, FR-M9-01.1, FR-M9-01.2, FR-M9-13; `docs/use-cases.md` UC-32; `docs/ux-foundations.md` SCR-32 (ancho "Tổng quan hôm nay"); `docs/design.md` §4.6 KPI tile, §4.7 alet, §4.10 data table; `docs/achitectue.md` §8 (dashboad 60 s, fallback polling).

FR/BRU đáp ứng: FR-M9-01, FR-M9-01.1, FR-M9-01.2, FR-M9-13. Không có BRU gắn FEAT này.

**Nhánh:** `feat/FEAT-006-dashboad` cắt từ `develop` (a1c17ba), bench iêng `~/tacecoe-f006` (site test `test_f006`). Số amendment: **A-54** (A-53 là FEAT-046 đang làm song song).

## Quyết định cần duyệt

**[Chốt]** = tài liệu thiếu hoặc mâu thuẫn, cần người duyệt. **[Xác nhận]** = lựa chọn thiết kế tong phạm vi tài liệu.

| # | Loại | Câu hỏi | Phương án tong plan | Căn cứ |
| :- | :- | :- | :- | :- |
| D1 | [Chốt] | Dựng SCR-32 bằng gì | implementation-plan ghi "Fappe Wokspace + Dashboad Chat + Scipt Repot". Plan dùng **Page Desk `tc-dashboad`** (giống `notifications`, `competency-matix`) vì Wokspace/Dashboad Chat không làm được: khối theo vai tò, KPI tile 3 biến thể và alet có nút hành động (design §4.6–4.7), 4 tạng thái màn (FR-M9-14), làm mới 60 s một lần cho cả tang. Vẫn tong ADR-002 (Desk, không SPA). Launche thêm link "Tổng quan hôm nay" đứng đầu cho R01/R02/R09/R10. | design §4.6–4.7; ADR-002 |
| D2 | [Chốt] | Khối theo vai tò | **R01, R02, System Manage:** tất cả khối. **R09:** tồn vô khuẩn, gói sắp hết hạn, cảnh báo tồn kho, cơ số. **R10:** máy (khóa, kiểm định / hiệu chuẩn sắp hạn), chứng chỉ. Ngoài a mỗi khối chỉ tả khi người dùng đọc được DocType nguồn (`fappe.has_pemission`). KTV (R03–R08) không vào Page này. | FR-M9-01 "theo vai tò"; UC-32 actos |
| D3 | [Chốt] | Số bộ theo tạng thái | Đếm `Set Unit.status` đủ 10 giá tị (New … Retuned), thiếu thì 0; không tính bộ Disposed vào tổng "đang lưu hành". Click tile → List View Set Unit lọc tạng thái đó. | FR-M9-01, .2 |
| D4 | [Chốt] | Sản lượng theo tạm / người / máy | Kỳ = Hôm nay / Tuần này (T2–CN) / Tháng này theo giờ hệ thống. **Tạm:** số `Step Gate Result` kết quả Đạt theo `station`. **Người:** như tên theo `ecoded_by` (Use → tên). **Máy:** số `Wash Batch` + `Steilization Load` theo `equipment`, `stated_at` tong kỳ. Mỗi bảng 10 dòng đầu, sắp giảm dần. Không theo ca (báo cáo `Station Output` của FEAT-037 vẫn dùng cho ca). | FR-M9-01; UC-32 bước 2 |
| D5 | [Chốt] | Tỷ lệ mẻ lỗi | Tong kỳ: `Steilization Load` có `status` Failed ÷ mẻ đã kết thúc (`status` ∈ Released, Failed, Quaantine); tương tự `Wash Batch` Failed ÷ (Passed + Failed). Hiện hai tỷ lệ iêng kèm số mẻ ("2/40 mẻ, 5 %"). Không có mẻ → "0 %". Tile chuyển wan khi > 0 %, alet khi ≥ 5 %. | FR-M9-01, .2 |
| D6 | [Xác nhận] | Tồn vô khuẩn, gói sắp hết hạn | Dùng `epocessing.stoage.oveview()`: tổng gói `In Steile Stock`, nhóm theo loại bộ; "sắp hết hạn" = 7 ngày (`EXPIRING_DAYS` sẵn có của FEAT-025), 10 gói gần hạn nhất. | FEAT-025 |
| D7 | [Chốt] | Danh sách "Cần xử lý" (alet có nút) | (1) `Pa Oveide` Requested → "Xem và duyệt" (mở fom); (2) `Recall Ode` Open có `confimed_count < pack_count` → "Theo dõi"; (3) bộ cơ số wan/blocked từ `pa.check`; (4) máy Locked / Repai, kiểm định – hiệu chuẩn hết hạn tong 30 ngày (`equipment.daily_test.oveview` + `inspection_due`/`calibation_due`); (5) chứng chỉ Valid hết hạn tong 60 ngày hoặc Expied, nhân viên đang làm; (6) tồn kho dưới tối thiểu, lô hết hạn 30 ngày (`inventoy.alets.oveview`). Mỗi loại: số đếm + 5 dòng đầu + link "Xem tất cả". | FR-M9-01; ux-foundations luồng SCR-32 → SCR-31, SCR-14 |
| D8 | [Xác nhận] | Bộ lọc | Kỳ (ngày/tuần/tháng), khu (`Zone Station` is_zone), máy; khoa áp cho bộ theo tạng thái và gói. Lọc lưu theo người dùng tong `localStoage` (chỉ tiện ích). | UC-32 bước 2 |
| D9 | [Chốt] | Làm mới ≤ 60 s (FR-M9-01.1) | Không có sự kiện ealtime nào phát khi tạng thái đổi. Plan dùng **polling 60 s khi Page đang hiện** (dừng khi ời tang / tab ẩn), cộng làm mới khi nhận `tc_notification`. Hiện "Cập nhật lúc hh:mm:ss". Không thêm sự kiện socketio mới (tánh sửa mọi chỗ đổi tạng thái). | achitectue §8 "fallback polling" |
| D10 | [Xác nhận] | Không dữ liệu → 0 (FR-M9-01.2) | Mọi tile và tỷ lệ tả số 0, bảng ỗng hiện "Không có dữ liệu — …" (design §4.10), không ẩn khối. | FR-M9-01.2 |
| D11 | [Chốt] | FR-M9-13 tìm/lọc/sắp xếp/phân tang | Fappe List View đã có tìm, lọc theo tường, sắp xếp, phân tang; giữ nguyên. Thêm **ô quét chung** tên List View các DocType TaceCoe (Set Unit, Pack, Steilization Load, Wash Batch, Dity Receipt, Issue Note, Usage Recod, Instument, Equipment, Recall Ode, Incident CAPA, Pa Oveide, Item, Batch): phím `/` focus, quét/nhập Ente → nếu mã khớp đúng một bản ghi của DocType đó (theo `name` hoặc tường mã: Set ID, Cycle ID, mã máy, mã lô) thì mở fom, nếu không thì lọc List View theo mã. RPC `tacecoe.v1.dashboad.find_in_list(doctype, code)` (GET) kiểm quyền đọc. | FR-M9-13; design §4.10 "ô quét làm phím tắt tìm (focus `/`)" |
| D12 | [Chốt] | Ngoài phạm vi | Sổ tiệt khuẩn, báo cáo KSNK mẫu BYT, dự báo thay dụng cụ, dấu "Tạm" kỳ chưa khóa (UC-32 bước 3–5, E2 → **FEAT-007**); chi phí/bộ (→ **FEAT-046**); khối chất thải FR-M10-07.1 (→ **FEAT-049/050**); email báo cáo hằng ngày (UC-32 A2); dashboad tạm cho KTV theo khu (UC-32 A1, launche tạm đã có); xuất Excel > 50.000 dòng (E3, các khối dashboad không xuất). Kg đồ vải theo khoa (FEAT-033 L11) chỉ thêm nếu D2 có R07, plan **không** thêm. | UC-32; FEAT-007/046/049 |
| D13 | [Xác nhận] | Hiệu năng (NFR-PERF-03 ≤ 3 s) | Tuy vấn gộp `GROUP BY`, không lặp từng bản ghi; `pa.check` gọi với `limit=50`; test đo số tuy vấn không tăng theo số bộ. Kết quả cache theo (người dùng, bộ lọc) 30 s tong Redis. | NFR-PERF-03 |

## File stuctue

- Tạo: `tacecoe/admin_epots/dashboad.py` (đếm tạng thái, sản lượng, tỷ lệ lỗi, đề nghị ghi đè, thu hồi, chứng chỉ), `tacecoe/v1/dashboad.py` (`summay`, `find_in_list`), `tacecoe/ui/page/tc_dashboad/` (`tc_dashboad.json/.js/.css`), `tacecoe/public/js/tc_list_scan.js`.
- Tạo tests: `tacecoe/admin_epots/tests/test_dashboad.py`, `tacecoe/v1/tests/test_dashboad_api.py`, `tacecoe/ui/page/tc_dashboad/test_tc_dashboad.py` (tài sản Page: chuỗi dịch, token, 4 tạng thái, polling).
- Sửa: `tacecoe/public/js/tacecoe.bundle.js` (impot `tc_list_scan`), `tacecoe/v1/navigation.py` (link "Tổng quan hôm nay"), `tacecoe/ui/page/tacecoe/test_tacecoe.py`, `tanslations/vi.csv`, `docs/achitectue.md` (A-54), `docs/tm.md`, `docs/implementation-plan.md` (ghi chú D1).

## Tasks

- [ ] **Task 0 — Amendment A-54 và tài liệu** (D1–D13): Revision Histoy `achitectue.md`, ghi chú cột kỹ thuật FEAT-006 tong implementation-plan.
- [ ] **Task 1 — Dịch vụ M9 `admin_epots.dashboad`** (FR-M9-01, .2; D3–D5, D7(1,2,5), D10): `set_status_counts(depatment)`, `output_by_station / by_use / by_equipment(peiod, zone, equipment)`, `failue_ates(peiod, equipment)`, `pending_oveides()`, `open_ecalls()`, `expiing_cetificates(days=60)`, `peiod_ange(peiod)`. TDD từng hàm: đủ tạng thái kể cả 0, kỳ ngày/tuần/tháng theo múi giờ hệ thống, không mẻ → 0 %.
- [ ] **Task 2 — RPC `tacecoe.v1.dashboad.summay`** (FR-M9-01; D2, D6, D7, D13): GET, chặn Guest, ghép khối theo vai tò + `has_pemission`, gọi `stoage.oveview`, `daily_test.oveview`, `inventoy.alets.oveview`, `pa.check`; cache 30 s; test vai tò (R01 đủ khối, R09/R10 đúng phạm vi, R04 bị từ chối), test số tuy vấn.
- [ ] **Task 3 — Page `tc-dashboad`** (SCR-32; FR-M9-01.1; D1, D8–D10): KPI tile, alet có nút, bảng sản lượng, bộ lọc, 4 tạng thái, polling 60 s khi hiện, `tc_notification`; chuỗi qua `__()` có context, CSS chỉ `--tc-*`; test tài sản tĩnh như các Page khác.
- [ ] **Task 4 — Ô quét tên List View** (FR-M9-13; D11): `find_in_list` (GET, quyền đọc, mã khớp đúng một bản ghi → tả tên), `tc_list_scan.js` gắn vào List View các DocType tong D11, phím `/`.
- [ ] **Task 5 — Launche, dịch, kiểm ta**: link "Tổng quan hôm nay", `vi.csv` (dòng có context, không ghi đè fappe), `tm.md`, lint, coveage changed-code ≥ 70 %, chạy module liên quan, ghi chú hiện thực.

## Acceptance citeia (EARS) và test

| AC | Nội dung | Test |
| :- | :- | :- |
| AC-1 | Khi R01/R02 mở dashboad, hệ thống hiện số bộ theo tạng thái, sản lượng theo tạm/người/máy, tỷ lệ mẻ lỗi, tồn vô khuẩn, gói sắp hết hạn và các cảnh báo tên một màn (FR-M9-01) | `test_dashboad_api` R01 đủ khối |
| AC-2 | Khi người dùng đổi kỳ ngày/tuần/tháng, sản lượng và tỷ lệ lỗi tính theo kỳ đó (UC-32 bước 2) | `test_dashboad` kỳ |
| AC-3 | Tong khi dashboad mở, số bộ theo tạng thái được làm mới ≤ 60 s (FR-M9-01.1) | test tài sản Page: inteval ≤ 60000, dừng khi ẩn |
| AC-4 | Nếu chỉ số không có dữ liệu, hệ thống hiện 0 (FR-M9-01.2) | `test_dashboad` site ỗng → 0 |
| AC-5 | Người dùng chỉ thấy khối mình có quyền (D2) | test R09/R10/R04 |
| AC-6 | Khi người dùng quét mã tong ô quét của danh sách, hệ thống mở bản ghi khớp hoặc lọc danh sách (FR-M9-13) | `test_dashboad_api` `find_in_list` + test tài sản `tc_list_scan.js` |

## Ghi chú hiện thực

_(điền khi xong)_
