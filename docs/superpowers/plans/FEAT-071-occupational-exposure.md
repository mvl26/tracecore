# FEAT-071 — Báo phơi nhiễm nghề nghiệp, theo dõi sau phơi nhiễm, tiêm chủng nhân viên (M16)

> Plan theo `writing-plans`. Đầu vào: implementation-plan §3 E-17 FEAT-071; srs §3.1.16 FR-M16-01..09 (+ .k là tiêu chí nghiệm thu), FR-M10-06.1, BRU-OCC-001..004, NFR-PRIV-01/02, NFR-AVAIL-05, NFR-MAINT-04; UC-55; architecture §5.3.1 (M16), §5.3.3, §8, ADR-003/009/010/014/015; ux-foundations SCR-63, SCR-64, A-131; ảnh `docs/design-refs/v1.12/SCR-63_PDA-PhoiNhiem.png`, `SCR-64_PhoiNhiem.png`.
>
> Nhánh `feat/FEAT-071-occupational-exposure` (từ develop 9a27e60), bench `~/tracecore-f032`, site test `test_f032`. Amendment **A-137**.

## 0. Quyết định đã chốt với người dùng (09/11/2026)

| # | Mâu thuẫn trong tài liệu | Chốt |
| --- | --- | --- |
| Q1 | Loại phơi nhiễm: architecture/UC-55 có 5 loại, ảnh SCR-63 có 4 | **5 loại theo architecture**: Needlestick or Sharps / Mucous Membrane Splash / Non-intact Skin / Respiratory / Other (nhãn vi theo cách nói dễ hiểu của ảnh) |
| Q2 | Nội dung 3 bước SCR-63; ux §568 "M16 không có mã BN" ngược ADR-010 | **Theo UC-55**: (1) loại + thời điểm, (2) hoạt động / thiết bị / nguồn đã biết? + mã BN nguồn tùy chọn (Password + hash + bản che), (3) xác nhận và gửi. Amendment sửa câu ux §568 |
| Q3 | Exposure Follow-up Template "có phiên bản" nhưng §5.3.3 đặt tên = `exposure_type` | **Tên `{exposure_type}-V{n}`**, trạng thái Draft → Approved → Superseded; duyệt bản mới tự đưa bản cũ về Superseded. Hồ sơ lưu phiên bản đã dùng và chép các bước. Immunization Requirement có trạng thái Draft/Approved |
| Q4 | SCR-63 cần DEPT nhưng develop chưa có Portal Cổng khoa | **Trang Portal độc lập** `/ksnk-khoa/bao-phoi-nhiem` dùng chung service; FEAT-062 sau gắn vào menu "KSNK khoa" |

### Quyết định mặc định (không mâu thuẫn, ghi vào A-137 — người dùng duyệt cùng plan)

- **D-a Ngưỡng giờ (FR-M16-03, OQ-V12-09):** thêm `IC Program Settings.exposure_report_hours`, `exposure_prophylaxis_hours` (Float, để trống = không gắn cờ). Không code cứng (FR-M16-03.1). Màn hiện ngưỡng đang áp dụng cạnh cờ.
- **D-b Trạng thái hồ sơ:** `New` (Mới — chờ xử trí) → `Following Up` (Đang theo dõi) → `Completed` (Kết thúc theo dõi); `Cancelled` (báo nhầm, R11/R01 có lý do). "Báo muộn" là **cờ** (`report_late`, `prophylaxis_late`), hiện badge chữ cạnh trạng thái. Không submittable (giống hồ sơ theo dõi, như IC Network Member); không ai có quyền xóa; `track_changes` + Audit Log.
- **D-c Nguồn báo** `report_channel`: PDA / Department Portal / Waste Incident / Desk (cột "Nguồn" trên SCR-64).
- **D-d Hạn bước theo dõi** = ngày phơi nhiễm (`occurred_at`) + `days_after`. Sinh lịch khi R11 ghi sơ cứu và chỉ định dự phòng (mọi giá trị Có / Không chỉ định / Từ chối). Không có template Approved cho loại → không sinh lịch, báo R01 (E4).
- **D-e Thông báo** (`core.notification.EVENTS`, mã chữ hoa như hiện có): `EXPOSURE_REPORTED` (Urgent, R01 + R11), `EXPOSURE_FOLLOWUP_DUE` (Normal, nhân viên + R11; trước 3 ngày một lần, quá hạn hằng ngày tối đa 7 lần — đếm `reminder_count`), `EXPOSURE_TEMPLATE_MISSING` (Normal, R01), `IMMUNIZATION_DUE` (Normal, nhân viên + R02), `PEP_STOCK_ALERT` (Normal, R01).
- **D-f Tiêm chủng:** `Staff Immunization.vaccine` là Link tới `Immunization Requirement` (danh mục vaccine là cấu hình, BRU-OCC-004, thay Select code cứng của §5.3.1). `Immunization Requirement`: `doses_required`, `dose_interval_days`, `booster_interval_days` (0 = không nhắc lại), bảng con khoa và chức danh có nguy cơ (Table MultiSelect). `next_due` = `given_on` + `dose_interval_days` nếu còn mũi, ngược lại + `booster_interval_days` nếu có, ngược lại trống. Mức nhắc giống FR-M4-01.4 (60/30/7 ngày/quá hạn, mỗi mức một lần) — chép logic nhỏ vì M16 không import `tracecore.hr` (lint R1). Trường cũ `Employee.tc_vaccination_expiry` giữ nguyên (gỡ là việc khác, ghi follow-up).
- **D-g Tỷ lệ bao phủ** (FR-M16-07, 07.1): mẫu số = Employee `status = Active` thuộc khoa **hoặc** chức danh có nguy cơ của requirement Approved; tử số = người có mũi `dose_no ≥ doses_required` và (nếu có nhắc lại) `next_due` chưa quá hạn.
- **D-h Thuốc dự phòng (FR-M16-08, Should):** Custom Field `Item.tc_is_pep_drug` (Check). Job hằng ngày đọc ERPNext: `Bin.actual_qty` so `Item Reorder.warehouse_reorder_level`; lô (`Batch.expiry_date` ≤ hôm nay + 30, còn tồn qua `erpnext.stock.doctype.batch.batch.get_batch_qty`) → `PEP_STOCK_ALERT` cho R01. Không nhập lại tồn (08.1). Truy vấn trực tiếp, không import `tracecore.inventory`.
- **D-i Quy trình xử trí ban đầu (FR-M16-01):** sau gửi hiển thị `IC Procedure Document` (FEAT-058, A-133) có `measure_group = Occupational Exposure` và `status = Effective` (đọc qua `frappe.get_all`, có kiểm `DocType` tồn tại vì FEAT-058 chưa vào develop). Không có → câu nhắc chung "báo ngay khoa KSNK".
- **D-j Quyền (FR-M16-05/05.1/05.2, BRU-OCC-003):** DocPerm Occupational Exposure chỉ R01 RW, R11 RW. Nhân viên tạo hồ sơ của mình và xem hồ sơ của mình qua RPC (PDA/Portal), không qua DocPerm. R08/R12 báo **thay mặt** nhân viên cùng khoa trên Portal (UC-55 bước 1), nhưng không đọc lại hồ sơ. R02, R13 chỉ thấy số liệu tổng hợp (Script Report, KPI). `has_permission` + `permission_query_conditions` chặn thêm: chỉ R01/R11/System Manager. Template: R01 RW, R11 R. Immunization Requirement: R01 RW, R02 R, R11 R. Staff Immunization: R01 RW, R02 RW, R11 R.
- **D-k Xem mã BN nguồn đầy đủ:** chỉ R01/R11, bắt buộc lý do, Audit Log `View Patient Code` (không ghi mã). Chưa có `core.patient_code` (FEAT-063/067 chưa làm) → helper riêng trong `occupational_safety/patient_code.py` dùng `core.crypto` (hash, chuẩn hóa) và cùng cách che như Usage Record; khi `core.patient_code` có thì chuyển (ghi follow-up). Không ghi mã ra log.
- **D-l Lưu trữ (NFR-PRIV-02):** `exposure_retention_months` đã có. Job hằng ngày: hồ sơ quá hạn lưu → xóa định danh (`employee`, `employee_name`, `reported_by`, mã BN nguồn 3 trường → trống, `deidentified = 1`), giữ khoa, loại, ngày, cờ, bước; Audit Log mỗi lần. Để trống → không làm gì.
- **D-m Không trong FEAT-071:** UC-55 bước 6/E5 (R11 mở `Incident CAPA` loại Occupational Exposure với quy tắc chặn nội dung sức khỏe) — cần quyết cách NC không mang danh tính khi `Incident CAPA` bắt buộc liên kết đối tượng; đề xuất follow-up/amendment riêng. Chỉ số M16 vẫn đẩy sang M9 qua `tracecore_ic_indicators`.

## 1. Kiến trúc tóm tắt

```
M10/M2 Incident CAPA (Sharps Exposure) --after_insert--> extension.run("tracecore_exposure_incident", doc)
                                                       └─> occupational_safety.exposure.from_incident (không trùng)
PDA station (screen_key "exposure") --POST tracecore.v1.exposure.report (@station_session offline, @idempotent)
Portal /ksnk-khoa/bao-phoi-nhiem    --POST tracecore.v1.exposure.report_portal (@idempotent)
                        └─> occupational_safety.exposure.create_report() → Occupational Exposure + EXPOSURE_REPORTED
tc-ksnk "phoi-nhiem" (SCR-64) --GET exposure.dashboard; POST exposure.record_handling / followup_done / reveal_source_code
Scheduler daily: followup reminders, immunization reminders, PEP stock, retention de-identification
Script Report "Occupational Exposure by Period" (không tên, không mã BN)
tracecore_ic_indicators: exposure_report_on_time, exposure_followup_completion, immunization_coverage
```

Không import chéo: `occupational_safety` chỉ dùng `tracecore.core.*`, `frappe`, `erpnext`. `reprocessing/incidents.py` chỉ gọi `core.extension.run`.

## 2. Tasks (TDD — test `FrappeTestCase` trước, thấy fail, rồi code)

### T0 — Amendment A-137 (docs, trước code)
- architecture §5.3.1 M16: thêm trường (`report_channel`, `reported_by`, `employee_name`, `minutes_to_report`, `minutes_to_prophylaxis`, `report_late`, `prophylaxis_late`, `first_aid_at`, `followup_template`, `template_version`, `deidentified`, `cancel_reason`; child `reminder_count`, `last_reminded_on`; mã BN 3 trường `source_patient_code`/`_masked`/`_hash`); Template `{exposure_type}-V{n}` + `status`/`version_no`/`approved_by`/`approved_on`; Immunization Requirement trạng thái, khoảng mũi, bảng con khoa/chức danh; Staff Immunization.vaccine Link; Item `tc_is_pep_drug`; IC Program Settings 2 ngưỡng; 5 sự kiện.
- §5.3.3 naming Template; ux-foundations §568 sửa "M16 có mã BN nguồn, luôn che", SCR-63 nhãn bước "1 Loại & thời điểm / 2 Hoàn cảnh / 3 Xác nhận", SCR-63 DEPT = Portal độc lập.
- rtm: cột Design/Tests cho FR-M16-01..09; Revision History A-137 (kiểm lại số trên origin/develop ngay trước commit).
- Commit `docs(arch): A-137 ...`.

### T1 — DocType & fixtures cấu hình (FR-M16-04, 07; BRU-OCC-004; NFR-MAINT-04)
- Tạo `Exposure Follow-up Template` (+ child `Exposure Follow-up Template Step`: `step`, `days_after`), `Immunization Requirement` (+ child `Immunization Requirement Department`, `Immunization Requirement Designation`).
- Service `occupational_safety/config.py`: `approve_template(name)` (R01; ≥ 1 bước, `days_after ≥ 0`; supersede bản Approved cũ cùng loại), `active_template(exposure_type)`, `approve_requirement(name)`.
- `ensure_default_config()` (after_migrate, `insert_if_missing`): template Draft cho 5 loại **không có bước** (nội dung chờ R01, OQ-V12-08/D10), requirement Draft "Hepatitis B", "Influenza" với `doses_required` trống.
- Test: duyệt, supersede, chặn duyệt template rỗng, `@bru("BRU-OCC-004")` migrate hai lần giữ bản R01 đã sửa.

### T2 — Occupational Exposure + child Exposure Follow-up (FR-M16-01, 03, 04, 06; BRU-OCC-001)
- DocType `PN-.YYYY.-.#####`, mã BN nguồn Password; controller mỏng → `occupational_safety/exposure.py`.
- `create_report(values, channel)`: kiểm loại, thời điểm (chỉ chặn thời điểm ở tương lai quá 5 phút), nhân viên có Employee; `reported_at` = giờ server nhận (A2); tính `minutes_to_report`, cờ theo ngưỡng; emit `EXPOSURE_REPORTED` (R01, R11); trả quy trình xử trí (D-i).
- `record_handling(name, first_aid_done, first_aid_at, prophylaxis, prophylaxis_started_at)`: tính `minutes_to_prophylaxis`, cờ; sinh follow-up từ template Approved (chép bước + `template_version`), status `Following Up`; thiếu template → `EXPOSURE_TEMPLATE_MISSING`.
- `mark_followup_done(name, row, done_on)`; đủ bước → `Completed`. Không có ô kết quả.
- Test: thời gian & cờ (có/không ngưỡng), sinh lịch, E4, hoàn thành, `@bru("BRU-OCC-001")` quét JSON mọi DocType M16 không có trường kiểu kết quả/chẩn đoán (fieldname/label khớp `result|diagnos|test|lab|serolog|hiv|hbsag|hcv|antibod|titer`) — FR-M16-06.1.

### T3 — Hook M10 → M16 (FR-M16-02, 02.1; BRU-OCC-002)
- `hooks.py`: `tracecore_exposure_incident = ["tracecore.occupational_safety.exposure.from_incident"]`.
- `reprocessing/incidents.after_insert`: nếu `incident_type == SHARPS` → `extension.run("tracecore_exposure_incident", doc)`.
- `from_incident(incident)`: đã có hồ sơ với `incident_capa` (unique) → trả tên; ngược lại tạo (`report_channel = Waste Incident`, loại Needlestick or Sharps, employee/department/occurred_at từ sự cố, `reported_at` = lúc tạo sự cố). Không chép `exposure_source` (text tự do, có thể chứa thông tin BN).
- Test `@bru("BRU-OCC-002")`: tạo sự cố sắc nhọn → 1 hồ sơ; gọi lại hook cùng sự cố → vẫn 1; hook đăng ký.

### T4 — Quyền & riêng tư (FR-M16-05, 05.1, 05.2; BRU-OCC-003; NFR-PRIV-01; F-22)
- `permission_matrix.csv` nối 4 dòng: DT-OCCEXP, DT-EXPTPL, DT-IMMREQ, DT-STFIMM (+ V112_ROWS, đếm dòng `test_permissions.py`), sinh lại `custom_docperm.json`.
- `permission_query_conditions` / `has_permission` cho Occupational Exposure.
- `patient_code.py` (D-k): `set_source_code`, `mask`, `reveal(name, reason)` → Audit Log.
- Test `@bru("BRU-OCC-003")`: R02/R13/R08/R12 không đọc/list được; nhân viên chỉ thấy hồ sơ của mình qua `my_records`; reveal R11 có lý do ghi Audit, thiếu lý do bị chặn, R02 bị 403; `assert_permission_matrix` cho 4 DocType.

### T5 — RPC `tracecore.v1.exposure` (FR-M16-01, 01.1; NFR-AVAIL-05; ADR-003)
- `report` (POST, `@station_session(*ALL_TC_ROLES, offline=True)`, `@idempotent`): nhân viên = phiên trạm; mã BN có thể mã hóa phía PDA (`core.crypto.decrypt_patient_code`, như Usage Record).
- `report_portal` (POST, `@idempotent`, đăng nhập Desk/Portal): R08/R12 được chọn nhân viên cùng khoa; người khác chỉ báo cho mình.
- `portal_context` (GET), `my_records` (GET), `dashboard` (GET, R01/R11; R13 chỉ KPI), `record_handling`, `followup_done`, `reveal_source_code` (POST, `@idempotent`).
- Mã lỗi `EXPOSURE_*` vào `core.errors.HTTP_STATUS` + `test_errors.py` + `error_codes`.
- Test: idempotent (cùng key → 1 hồ sơ), replay offline, thông báo R11 có Notification Delivery ngay khi ghi (01.1), 403 vai trò.

### T6 — PDA SCR-63 trong Page `station`
- `setup/seed.py` Station Function `EXPOSURE` (screen_key `exposure`), `FUNCTION_ROLES`/`STATION_ROLE_BY_FUNCTION`, `station_help` khóa `EXPOSURE` + Custom Field option, `station.js` case + `protectedCall` + `offlineCapable` + `TC_QUEUEABLE`.
- `public/js/station_exposure.js`: 3 bước, nút ≥ 56 px, chữ ≥ 16 px, ≤ 3 chạm sau mở, 4 trạng thái loading/empty/error/offline, lỗi chặn `alert-error` inline; sau gửi hiện quy trình xử trí. Không ô kết quả.
- Test asset (marker 4 trạng thái, không `frappe.call(`, không hex/px, không chuỗi tiếng Việt ngoài `__()`).

### T7 — DEPT Portal `/ksnk-khoa/bao-phoi-nhiem`
- `www/ksnk-khoa/bao-phoi-nhiem.html` + `.py` (yêu cầu đăng nhập, có Employee hoặc R08/R12; zonebar khoa navy), JS dùng chung bộ bước với PDA (module dùng chung) + outbox IndexedDB đơn giản với `X-Idempotency-Key` giữ nguyên khi gửi lại; danh sách "Hồ sơ của tôi" (A4).
- Test `get_context` (khách → chuyển đăng nhập; người không có Employee → thông báo), asset test.

### T8 — WEB SCR-64 trong `tc-ksnk`
- `ui/ksnk.py` `SCREENS += [{"slug": "phoi-nhiem", "scr": "SCR-64", "uc": "UC-55", "label": "Exposure and Immunization", "group": "environment", "roles": (R01, R11, R13, System Manager), "script": "/assets/tracecore/js/ksnk/scr_64_phoi_nhiem.js"}]`; badge hook (số hồ sơ `New`).
- `scr_64_phoi_nhiem.js`: 4 KPI, bảng hồ sơ (mã Courier New, badge chữ), panel lịch theo dõi (chỉ "đã thực hiện"), panel tiêm chủng, cảnh báo thuốc dự phòng, nút "Ghi sơ cứu & chỉ định" (dialog Frappe), "Báo cáo phơi nhiễm theo kỳ", "Xem màn báo phơi nhiễm (PDA)"; R13 chỉ KPI.
- CSS nối vào `tc_ksnk.css` (`.tc-ksnk` prefix, token).
- Test registry, JS harness, RPC GET/POST.

### T9 — Tiêm chủng (FR-M16-07, 07.1)
- `Staff Immunization` `TCH-.YYYY.-.#####`; `immunization.py`: `next_due`, mức nhắc, `coverage()`.
- Test: next_due theo khoảng mũi/nhắc lại, nhắc 1 lần mỗi mức cho nhân viên + R02, nhân viên nghỉ việc không vào mẫu số.

### T10 — Scheduler & thuốc dự phòng (FR-M16-04.1, 08, 08.1; NFR-PRIV-02)
- `occupational_safety/jobs.py run_daily`: follow-up reminders, immunization reminders, PEP stock, retention. `hooks.scheduler_events` daily.
- Test: nhắc trước 3 ngày một lần; quá hạn hằng ngày dừng sau 7; PEP dưới mức tối thiểu và lô ≤ 30 ngày → R01; xóa định danh có Audit, để trống ngưỡng → không đổi.

### T11 — Script Report "Occupational Exposure by Period" + chỉ số M9 (FR-M16-09, 09.1)
- Lọc từ ngày/đến ngày, nhóm theo loại / khoa / nghề nghiệp / thiết bị; cột số ca, % báo đúng hạn, % hoàn thành theo dõi. Không tên, không mã BN. Roles R01, R11, R13.
- `tracecore_ic_indicators` đăng ký 3 hàm.
- Test: không chứa tên nhân viên/mã BN (NFR-PRIV-01), số đúng.

### T12 — Bản dịch & hoàn tất
- `vi.csv` nối cuối (context cho nhãn chung), không mã nội bộ trong chuỗi.
- `bench migrate`, `bench build --app tracecore`, test module M16 + các module bị chạm, full suite (khi không có lượt khác), `diff-cover ≥ 70 %`, `pre-commit run --all-files`; review diff độc lập bằng subagent; push `github feat/FEAT-071-occupational-exposure`. Không PR, không merge.

## 3. Ma trận nghiệm thu

| AC | Task | Test chính |
| --- | --- | --- |
| FR-M16-01 / 01.1 | T2, T5, T6, T7 | test_exposure_api: báo 3 bước, Delivery R11 ngay |
| FR-M16-02 / 02.1 | T3 | test_exposure_hook (BRU-OCC-002) |
| FR-M16-03 / 03.1 | T2, T0 D-a | test_exposure: cờ theo ngưỡng cấu hình |
| FR-M16-04 / 04.1 | T1, T2, T10 | test_followup, test_jobs |
| FR-M16-05 / 05.1 / 05.2 | T4 | test_exposure_permissions (BRU-OCC-003) |
| FR-M16-06 / 06.1 | T2 | test_privacy_json (BRU-OCC-001) |
| FR-M16-07 / 07.1 | T9 | test_immunization |
| FR-M16-08 / 08.1 | T10 | test_pep_stock |
| FR-M16-09 / 09.1 | T11 | test_exposure_report |
| NFR-AVAIL-05 | T5–T7 | replay idempotent (E2E offline không chạy) |
| NFR-MAINT-04 | T1 | migrate hai lần giữ bản sửa (BRU-OCC-004) |
| NFR-PRIV-02 | T10 | retention job |

## 4. File dùng chung (chỉ nối thêm / sửa tối thiểu)
`permission_matrix.csv` (+ `custom_docperm.json` sinh lại), `tests/test_permissions.py`, `tests/test_permissions_v112.py`, `hooks.py`, `ui/ksnk.py`, `tc_ksnk.css`, `vi.csv`, `core/notification` EVENTS, `core/errors` + `test_errors.py` + error codes, `fixtures/custom_field.json` (Item `tc_is_pep_drug`, khóa `EXPOSURE` của Help Article), `ic_program_settings.json` (2 ngưỡng), `incident_capa`/`incidents.py` (1 dòng gọi hook), `station.js`, `tc_outbox.js`, `setup/seed.py`, `v1/navigation.py`, `setup/provision.py`, `ui/station_help.py`.

## 5. Rủi ro
- Nhiều nhánh v1.12 cùng nối vào các file trên → xung đột khi merge (chỉ nối thêm, giảm thiểu).
- FEAT-058 (IC Procedure Document) chưa vào develop → D-i có nhánh dự phòng.
- Nội dung chuyên môn (bước theo dõi, vaccine, ngưỡng giờ) chờ OQ-V12-08/09: fixtures Nháp rỗng, R01 nhập.
- RAM WSL 3,7 GB: chỉ chạy full suite khi không có lượt `run-tests` khác.
