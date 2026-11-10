# FEAT-064 — Giám sát nhiễm khuẩn vết mổ theo QĐ 1526 (NNIS, cửa sổ theo dõi, KSDP, xuất báo cáo)

> Kế hoạch theo `docs/implementation-plan.md` E-14 dòng FEAT-064 (M13 `hai_surveillance`, S7, cỡ M). Không brainstorm:
> thiết kế đã duyệt theo A-113. Chỗ tài liệu lệch/thiếu ghi ở **Amendment A-147** (người dùng chọn phương án đề xuất
> Q1–Q4 trong chat ngày 10/11/2026).

**Nhánh:** `feat/FEAT-064-ssi-surveillance` (bench `~/tracecore-f043`, site test `test_f043`), cắt từ `origin/develop`
2436b7e.

**Đầu vào:** FR-M13-07, 07.1, 07.2, 08, 08.1, 09, 09.1, 09.2, 12, 12.1; BRU-HAI-003, BRU-HAI-004, BRU-HAI-005,
BRU-RPT-002, BRU-RPT-003; NFR-PRIV-01, NFR-MAINT-04; UC-49 (A1–A3, E1–E4); SCR-57 (WEB + PDA), SCR-58 (phần xuất);
architecture §5.3.1 (Surgical Procedure Group, Surgical Surveillance, HAI Case), ADR-010 mở rộng, ADR-014, F-21; ảnh
`docs/design-refs/v1.12/SCR-57_NKVM.png`, `SCR-58_BaoCaoNKBV.png`. Dùng lại FEAT-062/063: `HAI Case`,
`HAI Case Definition` (mã SSI-SUP/SSI-DEEP/SSI-ORGAN), `IC Reporting Period`, `core.importer`, `core.patient_code`.

## Quyết định (A-147)

| # | Chốt | Lý do |
| :- | :- | :- |
| Q1 | DocType mới `Report Export Profile` + child `Report Export Profile Column` (module `TraceCore`, tên = `profile_name` do R01/R10/R11 đặt): `export_kind`, `file_format` Excel/CSV, `encoding`, `delimiter`, `date_format`; cột = `source_field` → `header` (tiêu đề theo mẫu cơ quan). Dịch vụ `core.exporter` + hook `tracecore_export_kinds` (giống `core.importer`). Hồ sơ chứa trường bị cấm (mã BN rõ, họ tên) → chặn lưu và chặn xuất `EXPORT_COLUMN_FORBIDDEN` (UC-49 E3) | implementation-plan ghi "Export Mapping" nhưng §5.3 không có DocType; Import Mapping Profile chỉ để nhập |
| Q2 | Child `Surgical Procedure Group Follow-up` trên nhóm: `day_offset` (ngày thứ N tính từ ngày mổ, 1..cửa sổ), `method` (Phone / Revisit / Record). Khi có ngày ra viện: sinh các lần có hạn **sau** ngày ra viện và **trước** ngày kết thúc cửa sổ, cộng **luôn một lần cuối đúng `window_end`** (cách lấy từ dòng có `day_offset` = cửa sổ, không có thì Phone). Nhóm chưa khai báo → chỉ lần cuối. Ra viện sau `window_end` → không sinh (theo dõi nội trú, A2) | FR-M13-08 "theo cấu hình nhóm"; §5.3 chỉ có `followup_days` |
| Q3 | `IC Program Settings.prophylaxis_max_minutes` (Int, mặc định trống — OQ-V12-09). Mỗi ca lưu bản chụp `prophylaxis_max_applied` + `prophylaxis_timing`: Not given (không dùng) / On time (0 ≤ phút trước rạch da ≤ ngưỡng) / Late (sau rạch da, phút < 0) / Too early (> ngưỡng) / Not assessed (thiếu phút hoặc ngưỡng trống). Đổi ngưỡng → tính lại chỉ các ca thuộc kỳ **chưa khóa**; kỳ đã khóa giữ bản chụp (FR-M13-09.2) | FR-M13-09.1 không code cứng; BRU-RPT-003 |
| Q4 | Custom Field `Department.tc_icu` (Check "Khoa hồi sức"). Xuất "NK hồi sức": mỗi dòng 1 `HAI Case` Xác định (đã ghi sổ) ở khoa `tc_icu` trong kỳ (mã BN che, loại NK, thiết bị, tác nhân, nhãn đa kháng); kèm loại xuất tổng hợp theo khoa hồi sức (ngày nằm viện, ngày thiết bị, số ca, tỷ suất ‰) | FR-M13-12 không nêu khoa hồi sức là gì |
| a | `Surgical Procedure Group` (tên = `group_code`, không submittable, danh mục cấu hình): `group_code`, `group_name`, `t_time_minutes` (T của NNIS, trống = chưa cấu hình), `has_implant` ("nhóm có cấy ghép"), `followup_days` (30/90; nhóm có cấy ghép buộc 90), `is_monitored`, `followups`. Seed 6 nhóm mẫu QĐ 1526 với `is_monitored = 0` (Nháp chờ R01 rà soát), chỉ chèn mã còn thiếu (NFR-MAINT-04) | D10: nội dung chuyên môn là cấu hình |
| b | `Surgical Surveillance` (`PT-.YYYY.-.#####`, **không submittable** — hồ sơ sống suốt cửa sổ theo dõi như `Device Episode`; không xóa): trường §5.3.1 + `department_name`, `group_name`, `t_time_applied`, `nnis_note`, `window_days`, `prophylaxis_timing`, `prophylaxis_max_applied`, `reporting_period` (tháng ngày mổ), `source` (Manual/Import), `import_batch`, `data_complete`, `deidentified`; child `SSI Follow-up` (`due_date`, `method`, `is_final`, `done_on`, `result` Negative / SSI suspected / Unreachable, `note`, `done_by`). `outcome` Under Surveillance / No SSI / SSI / Lost to Follow-up. `nnis_index` là Select 0–3 (trống = chưa tính) và `prophylaxis_minutes_before_incision` là Data số nguyên, vì Int của Frappe lưu trống thành 0 | §5.3.1 |
| c | NNIS (BRU-HAI-003) = (ASA ≥ 3) + (vết mổ Contaminated/Dirty) + (`duration_min` > T); chụp `t_time_applied`. Nhóm thiếu T → `nnis_index` trống, `nnis_note`, thông báo `SSI_GROUP_T_MISSING` cho R01 một lần mỗi nhóm (E4). Nhập tay: ASA, vết mổ, thời gian bắt buộc; ASA ngoài 1–5 hoặc thời gian ≤ 0 → chặn `SSI_VALUE_INVALID` (E2). Nhập file (A1) cho phép thiếu → `data_complete = 0`, R11 bổ sung | UC-49 bước 3, A1, E2, E4 |
| d | Cửa sổ (BRU-HAI-004): `window_days` = 90 nếu nhóm có cấy ghép **hoặc** ca có `has_implant`, ngược lại `followup_days` của nhóm (30); `window_end` = ngày mổ + `window_days` | FR-M13-07.2 + UC-49 bước 3 |
| e | Kết cục: có `HAI Case` Xác định (ghi sổ) gắn qua `HAI Case.surgical_surveillance` → SSI. Hết cửa sổ (hôm nay > `window_end`) mà lần cuối chưa làm hoặc "Unreachable" → Lost to Follow-up (E1, FR-M13-08.1); mọi lần đã làm đều Negative → No SSI; còn lại Under Surveillance. Scheduler hằng ngày cập nhật ca vừa hết cửa sổ. Ra viện sau cửa sổ (A2) → R11 đóng ca tay (No SSI / Lost to Follow-up) | FR-M13-08 |
| f | "SSI suspected" ở một lần theo dõi → nút "Tạo ca NKBV" trên SCR-57 tạo `HAI Case` Nghi ngờ (mã BN, năm sinh, giới, khoa, ngày nhập viện = ngày mổ, mã định nghĩa SSI-*) có `surgical_surveillance`; ca bị Loại trừ → tính lại kết cục. `HAI Case` thêm trường `surgical_surveillance` (Link, cùng người bệnh theo hash) | UC-49 bước 5; §5.3.1 "thêm ở FEAT-064" |
| g | Kỳ đã khóa (`periods.ensure_open(surgery_date)`) chặn sửa trường đăng ký (người bệnh, nhóm, ngày mổ, ASA, vết mổ, thời gian, cấy ghép, KSDP); vẫn ghi được ra viện, lần theo dõi, kết cục (theo dõi kéo dài 30/90 ngày sau kỳ). Giá trị chỉ số của kỳ đã khóa nằm ở `IC Indicator Value` nên không đổi | FR-M13-11, BRU-RPT-003 |
| h | Chỉ số (hook `tracecore_ic_indicators`): `SSI_RATE` (% ca SSI / ca phẫu thuật giám sát có ngày mổ trong tháng), `SSI_PROPHYLAXIS_RATE` (% ca có KSDP), `SSI_PROPHYLAXIS_ON_TIME` (% On time / ca có KSDP đã đánh giá). Mẫu số 0 → "Không tính". Danh mục `IC Indicator` vẫn do R01/R10 tạo | FR-M13-09 |
| i | Import "Danh sách phẫu thuật" (`surgical_list`, F-21): một dòng một ca; khóa = nhóm + ngày mổ + hash mã BN (dòng trùng → "đã có", không ghi đè, R11 bổ sung tay); cột họ tên bị bỏ; `purge_file`; vai trò R11, R01 | UC-49 A1; D3 |
| j | Xuất (`core.exporter`, RPC `tracecore.v1.exports.*`; Audit Log chưa có hành động `Export` nên không ghi — file chỉ có mã che): loại `ssi_cases` (từng ca, mã che), `ssi_summary` (nhóm × NNIS: số ca, SSI, %), `icu_hai_cases`, `icu_hai_summary`. Không hồ sơ → cột mặc định, tiêu đề tiếng Việt. Chỉ R01, R11 xuất (BRU-RPT-002, FR-M13-12.1) | FR-M13-12 |
| k | Màn: `nkvm` (SCR-57, R01/R11, nhóm `hai`) trong Page `tc-ksnk` — 4 KPI, form đăng ký, lịch theo dõi, ca gần đây, nút Nhập file (mở SCR-43 loại `surgical_list`) / Xuất NKVM; SCR-58 thêm khối "NKVM theo nhóm & NNIS" + nút xuất 4 loại (R01/R11). Script Report `SSI by Procedure Group` (R01, R10, R11, R13 — chỉ tổng hợp). PDA: chức năng trạm `SSI_FOLLOWUP` (màn `ssi`, vùng Department, R11/R01, chỉ online — không lưu dữ liệu người bệnh trên máy): lần theo dõi đến hạn hôm nay/quá hạn, ghi kết quả. Patch `a147_ssi_station_function` | SCR-57 WEB + PDA |
| l | Nhắc (ADR-014): cron 15 phút sau `census_reminder_time` → `SSI_FOLLOWUP_DUE` cho R11 (một thông báo mỗi ngày liệt kê mã ca, mã BN che). Badge `nkvm` = số lần theo dõi đến hạn/quá hạn | FR-M13-08 |
| m | Ma trận quyền +3 dòng (86 → **89**): DT-SSIGRP (R01 RW, R10 R, R11 R), DT-SSI (R01 RW, R11 RW — R08/R10/R12/R13 không đọc), DT-REXP (R01 RW, R10 RW, R11 RW) | NFR-SEC-09, ADR-010 |

## Tasks (TDD: test `FrappeTestCase` trước, thấy đỏ, rồi code)

### T1 Amendment A-147 (docs) — DoD v1.12
- architecture Revision History + §5.3.1 (Surgical Procedure Group, Surgical Surveillance, HAI Case, Ext Department,
  Report Export Profile) + §5.3.3; srs Revision History; implementation-plan dòng FEAT-064; ux SCR-57/58; rtm
  FR-M13-07/08/09/12.

### T2 Nhóm phẫu thuật — FR-M13-07.2; BRU-HAI-004; NFR-MAINT-04
- Test `test_ssi.py::TestGroups`: nhóm có cấy ghép buộc 90; `day_offset` ngoài 1..cửa sổ → chặn; seed chèn thiếu,
  không ghi đè bản đã sửa, `is_monitored = 0`.
- Code: DocType + child, `hai_surveillance/ssi_seed.py` (after_migrate).

### T3 Đăng ký ca, NNIS, cửa sổ — FR-M13-07, 07.1, 07.2; BRU-HAI-003, 004, 005; E2, E4
- Test: ASA 3 + Sạch + 150′ với T 120 → NNIS 2 (@bru BRU-HAI-003); cấy ghép → `window_end` +90, không → +30
  (@bru BRU-HAI-004); ASA 6 / thời gian 0 → chặn; nhóm thiếu T → NNIS trống + thông báo R01 một lần; nhóm chưa giám sát
  → chặn; chỉ mã che lưu ở danh sách, không trường họ tên (@bru BRU-HAI-005); kỳ khóa chặn sửa trường đăng ký.
- Code: DocType + child, `hai_surveillance/ssi.py`, controller.

### T4 Lịch theo dõi, kết cục — FR-M13-08, 08.1; E1, A2
- Test: ra viện → sinh lần sau ra viện + lần cuối = `window_end`; ghi kết quả; hết cửa sổ mọi lần âm tính → No SSI;
  bỏ lỡ lần cuối → Lost to Follow-up (@bru BRU-HAI-004); ca NKBV Xác định gắn → SSI; Loại trừ → tính lại; nhắc
  `SSI_FOLLOWUP_DUE` một lần mỗi ngày.
- Code: `ssi.py` (schedule, record_followup, refresh_outcome, run_daily, remind), `HAI Case.surgical_surveillance`,
  hook on_submit/on_cancel HAI Case.

### T5 Kháng sinh dự phòng — FR-M13-09, 09.1, 09.2
- Test: 45′ với ngưỡng 60 → On time; −10 → Late; 90 → Too early; ngưỡng trống → Not assessed; đổi ngưỡng tính lại kỳ
  mở, giữ kỳ khóa (@bru BRU-RPT-003); chỉ số `SSI_PROPHYLAXIS_*`, `SSI_RATE`, mẫu số 0 → Không tính.
- Code: settings field, `ssi.py`, `ssi_indicators.py`, hook IC Program Settings on_update.

### T6 Nhập danh sách phẫu thuật — UC-49 A1; F-21
- Test `test_ssi_import.py`: file 2 dòng → 2 ca `source = Import`, thiếu ASA → `data_complete = 0`; dòng trùng →
  "đã có"; nhóm không có → lỗi dòng; cột họ tên bị bỏ.
- Code: `hai_surveillance/ssi_imports.py`, hook `tracecore_import_kinds`.

### T7 Xuất theo ánh xạ cột — FR-M13-12, 12.1; BRU-RPT-002; E3
- Test `core/tests/test_exporter.py` + `test_ssi_export.py`: hồ sơ đổi tiêu đề và thứ tự cột; CSV `;` Windows-1258;
  hồ sơ chứa `patient_code` → chặn (@bru BRU-RPT-002); file không chứa mã rõ; NK hồi sức chỉ khoa `tc_icu`; R13 bị từ chối.
- Code: DocType `Report Export Profile` + child, `core/exporter.py`, `hai_surveillance/exports.py`, `v1/exports.py`.

### T8 Màn & quyền — SCR-57, SCR-58, PDA
- Test `tests/test_ksnk_scr57.py` (JS harness: KPI, NNIS, badge trạng thái có chữ, không hex/px), `v1/tests/test_ssi_api.py`,
  `hai_surveillance/tests/test_ssi_pda.py`; ma trận (`test_permissions` 89, `test_permissions_v112`), `test_name_columns`,
  `test_ksnk_nav`, `test_zones`.
- Code: `v1/ssi.py`, `public/js/ksnk/scr_57_nkvm.js`, khối xuất SCR-58, Script Report, `station_ssi.js`, seed/patch
  chức năng trạm, ma trận + `custom_docperm.json`, vi.csv.

### T9 Kiểm chứng
- Chạy lần lượt từng module có `--module` (không full suite), đọc `Ran`/`OK`; `diff-cover` ≥ 70 %;
  `pre-commit run --all-files`; `bench build --app tracecore`.
