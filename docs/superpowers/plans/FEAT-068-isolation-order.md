# FEAT-068 — Lệnh cách ly tại khoa và phòng cách ly (kế hoạch)

> Đầu vào: implementation-plan §3 E-15 dòng FEAT-068; SRS FR-M14-06, FR-M14-06.1, FR-M14-07, FR-M14-07.1; BRU-MDR-003,
> BRU-HAI-005; UC-52; SCR-60 (WEB + DEPT) + `docs/design-refs/v1.12/SCR-60_CachLy.png`; architecture §5.3 Isolation
> Order / Isolation Room, §5.3.3 naming (`PCL-.####`, `CL-.YYYY.-.#####`), ADR-010 mở rộng, ADR-015. Nhánh
> `feat/FEAT-068-isolation-order` từ develop 203bf1a, bench `~/tracecore-f026`, site test `test_f026`. Amendment **A-146**.

## Quyết định A-146 (người dùng chọn phương án đề xuất trong chat ngày 10/11/2026)

| # | Lệch / thiếu trong tài liệu | Quyết định |
| --- | --- | --- |
| Q1 | FR-M14-07.1 cần "cờ lâm sàng trên Department" nhưng chưa có | Custom Field mới `Department.tc_clinical` (Check "Khoa lâm sàng"); patch `a146_department_clinical` điền sẵn từ `tc_inpatient` cho site đang chạy (R10 sửa lại sau) |
| Q2 | Isolation Room: architecture có `room_type`, `beds`, `meets_standard`, `checked_on`; ảnh SCR-60 thêm Áp lực âm, Bồn rửa tay riêng, Khu đệm, trạng thái phòng, lý do Không đạt; tiêu chí "đạt" cấu hình theo bệnh viện (OQ-V12-08) | Giữ trường architecture + 3 Check ghi nhận `negative_pressure`, `has_hand_sink`, `has_anteroom`; `meets_standard` do R01 tự đánh (không tự tính, không cứng tiêu chí); đã kiểm tra mà Không đạt thì bắt buộc `standard_note`; Đạt thì bắt buộc `checked_on`. Trạng thái Đang dùng/Trống tính từ số lệnh đang mở so với `beds` |
| Q3 | `reason` là Select (architecture) hay chữ tự do (ảnh) | `reason` Select bắt buộc (Vi khuẩn đa kháng / Bệnh truyền nhiễm / Nghi nhiễm) + `reason_detail` chữ tự do không bắt buộc. Lệnh "do đa kháng" (`is_mdro`) = `reason` Vi khuẩn đa kháng hoặc gắn chủng `is_mdro` |
| Q4 | Nút "Tạo lệnh cách ly" điền sẵn (A-136 Q5); link `MDRO_DETECTED` về Page tc-ksnk mà R08/R12 không mở được | Link thông báo đổi thành `/ksnk-khoa/cach-ly?isolate=<chủng>`; R01/R11/System Manager mở link Portal này được chuyển sang `/app/tc-ksnk/cach-ly?isolate=…`; SCR-59 thêm nút trên dòng chủng đa kháng. Server chép mã BN (đã mã hóa) từ chủng, không qua trình duyệt; tạo lệnh từ chủng → `notification.resolve(MDRO_DETECTED, chủng)` |
| Q5 | Vòng đời, quyền | Isolation Order submittable: tạo = ghi sổ ngay (`Open` "Đang cách ly"); đóng = RPC điền `end_at`, `end_reason`, `closed_by` (allow_on_submit) → `Closed`; Hủy chỉ R01/R11 (nhập nhầm). Ma trận 78 → **80**: `DT-ISOORD` R01 RWSA, R08 RWS, R11 RWSA, R12 RWS (R08/R12 chỉ khoa mình), R13 không đọc; `DT-ISOROOM` R01 RW, R08 R, R11 R, R12 R (khoa mình), R13 R |
| Q6 | Thông báo | Sự kiện mới `ISOLATION_ORDER_OPENED`, `ISOLATION_ORDER_CLOSED` (Normal, vai trò mặc định R11) qua `core.notification.emit`. Không chọn phòng hoặc phòng đã đủ giường → `bedside_isolation` = 1 ("Cách ly tại giường"), cảnh báo, không chặn lưu |

Ngoài phạm vi: phiếu M12 giám sát tuân thủ cách ly (UC-52 bước 3, đã có engine FEAT-060), kiểm tra phòng theo phiếu hạ
tầng M15 (A3, FEAT sau), việc cần làm Cổng khoa SCR-66 (FEAT-065 đọc `Isolation Order` qua `frappe.get_all`). Chuyển
khoa (A1) = đóng với lý do + khoa nhận tạo lệnh mới.

## AC (EARS, suy từ FR)

- AC-1 (FR-M14-06, UC-52 E1): Khi khoa tạo lệnh cách ly thiếu loại phòng ngừa hoặc lý do, hệ thống phải chặn lưu (alert inline, kết quả → lý do → hành động).
- AC-2 (FR-M14-06): Khi lệnh được tạo, hệ thống phải ghi sổ trạng thái Đang cách ly, mã BN chỉ hiện dạng che, và hiện lệnh trong danh sách đang mở của khoa (Portal) và toàn viện (SCR-60 WEB).
- AC-3 (BRU-MDR-003, UC-52 E3): Nếu đóng lệnh không có lý do kết thúc, hệ thống phải chặn.
- AC-4 (FR-M14-06.1, UC-52 E2): Nếu R08/R12 đóng lệnh do đa kháng, hệ thống phải chặn; R11/R01 đóng được.
- AC-5 (NFR-SEC-09, UC-52 E4): R08/R12 khoa A không thấy và không ghi lệnh/phòng khoa B.
- AC-6 (FR-M14-07, .1): Hệ thống phải tính tỷ lệ khoa lâm sàng (`tc_clinical`) có ≥ 1 phòng cách ly đạt và liệt kê khoa chưa có; hàm chỉ số `isolation_room_coverage` đăng ký qua `tracecore_ic_indicators`.
- AC-7 (A-136 Q5): Từ chủng đa kháng (SCR-59 hoặc thông báo) mở form tạo lệnh điền sẵn khoa, mã BN che, chủng, lý do Vi khuẩn đa kháng, loại phòng ngừa của quy tắc; tạo xong thông báo đa kháng của chủng chuyển Đã đọc.
- AC-8 (Q6): Tạo/đóng lệnh gửi `ISOLATION_ORDER_OPENED` / `ISOLATION_ORDER_CLOSED` qua `core.notification.emit`.
- AC-9 (BRU-HAI-005, NFR-PRIV-01): Isolation Order không có trường họ tên; `patient_code` là Password; list/RPC chỉ trả `patient_code_masked`.

## Tasks (TDD — test `FrappeTestCase` trước, thấy fail, rồi code)

1. **Docs A-146** — Revision History architecture/srs/ux/implementation-plan; §5.3 Isolation Room thêm 3 Check + `standard_note` + `disabled`, Isolation Order thêm `reason_detail`, `bedside_isolation`, `is_mdro`, `closed_by`; Ext Department `tc_clinical`; SCR-60 dòng ux; rtm. (Q1–Q6)
2. **Custom Field + patch** — `Department-tc_clinical` (fixtures/custom_field.json), patch `a146_department_clinical`. Test: patch điền từ `tc_inpatient`, chạy lại không ghi đè. (FR-M14-07.1)
3. **DocType Isolation Room** (`microbiology/doctype/isolation_room`, `PCL-.####`, title `room_code`) + `microbiology/isolation.py` `validate_room`. Test: Đạt cần `checked_on`; Không đạt đã kiểm cần `standard_note`; `beds` ≥ 1; mã phòng không trùng. (FR-M14-07, Q2)
4. **DocType Isolation Order** (`CL-.YYYY.-.#####`, submittable) + dịch vụ `isolation.create_order / close_order / cancel` — bộ ba mã BN qua `core.patient_code`; `@bru("BRU-MDR-003")` cho chặn đóng thiếu lý do và R08/R12 đóng lệnh đa kháng; `@bru("BRU-HAI-005")` quét JSON không có trường họ tên; chặn thiếu loại phòng ngừa/lý do; phòng khác khoa/đã tắt → chặn; phòng đầy/không phòng → tại giường + cảnh báo; `end_at` ≥ `start_at`, không ở tương lai. (AC-1..4, AC-9)
5. **Phạm vi khoa** `microbiology/permissions.py` (permission_query_conditions + has_permission cho 2 DocType) + ma trận quyền (DT-ISOORD, DT-ISOROOM; 78 → 80; test_permissions, test_permissions_v112; migrate → write_fixture → migrate). (AC-5, Q5)
6. **Thông báo** — EVENTS `ISOLATION_ORDER_OPENED/CLOSED`; emit ở submit/đóng; resolve `MDRO_DETECTED` khi tạo từ chủng; đổi link `MDRO_DETECTED` sang Portal. (AC-7, AC-8)
7. **Chỉ số** — `microbiology/indicators.py` `isolation_room_coverage(period, department)` + `coverage(day)` (khoa đạt/chưa có); hook `tracecore_ic_indicators`. (AC-6)
8. **RPC `tracecore.v1.isolation.*`** — `overview` (GET, SCR-60 WEB), `portal_context` (GET), `create_order`, `close_order`, `cancel_order` (POST `@idempotent`, lỗi trả `{ok:false,error}`); prefill từ `isolate`. Mã lỗi mới vào `UNMAPPED_BLOCK_CODES`. (AC-1..8)
9. **SCR-60 WEB** — `ui/ksnk.py` SCREENS slug `cach-ly` (R01, R11, R13, System Manager; R13 chỉ thấy tỷ lệ), `public/js/ksnk/scr_60_cach_ly.js` theo bố cục ảnh (form tạo, Đang cách ly, Phòng cách ly theo khoa + KPI); nút SCR-59 → `/app/tc-ksnk/cach-ly?isolate=`. Test RPC + test_ksnk_nav.
10. **SCR-60 DEPT** — `www/ksnk_khoa/cach_ly.{py,html,js,css}`, route `/ksnk-khoa/cach-ly`, menu `ksnk_khoa_nav.html`; R01/R11 chuyển sang Desk. Test get_context.
11. **vi.csv**, lint, test module lần lượt, diff-cover ≥ 70 %, pre-commit, push `github`.

## File dùng chung (chỉ thêm khối `# FEAT-068`)

hooks.py (route, permission_query_conditions, has_permission, doc_events, tracecore_ic_indicators, fixtures nếu cần),
patches.txt, core/notification EVENTS, core/error_codes UNMAPPED, fixtures/custom_field.json, permission_matrix.csv,
custom_docperm.json, tests/test_permissions.py (80), test_permissions_v112.py, ui/ksnk.py, ksnk_khoa_nav.html,
translations/vi.csv, microbiology/isolates.py (link), scr_59_vi_sinh.js.

## Test module chạy lần lượt (`--app tracecore --module …`)

microbiology: test_isolation_room, test_isolation_order, test_isolation_indicators, test_isolation_patch (+ test của
FEAT-067 bị đụng: test_isolates/test_alerts nếu có); v1 test_isolation_api, test_micro_api; tests test_ksnk_scr60,
test_ksnk_scr59, test_ksnk_page, test_permissions, test_permissions_v112, test_name_columns, test_no_internal_codes;
ui.tests.test_ksnk_nav; core test_notification, test_errors.
