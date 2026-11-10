# FEAT-062 Mẫu số ngày theo khoa, đợt thiết bị, gói dự phòng (M13, SCR-55, SCR-52) — kế hoạch

> Plan theo `writing-plans`. Đầu vào: implementation-plan §3 E-14 FEAT-062; srs FR-M13-02 (.1, .2), FR-M13-03 (.1, .2), FR-M13-04 (.1, .2), FR-M12-07 (.1, .2), BRU-HAI-002, BRU-HAI-005, BRU-AUD-003, NFR-PRIV-01, NFR-AVAIL-05, NFR-SEC-09, EI-SW-010; UC-47, UC-44; architecture §5.3.1 (M13: Ward Daily Census, Device Episode; M12: Audit Session.device_episode), §5.3.3 (MS-, DTB-), §8 (ADR-010 mở rộng, Department permission), ADR-003/010/014/015, F-21 Import Mapping Profile; ux-foundations SCR-55, SCR-52; ảnh `docs/design-refs/v1.12/SCR-55_Khoa-MauSo.png`, `SCR-52_PDA-PhieuMuc.png`.
>
> Nhánh `feat/FEAT-062-ward-census` (từ develop 395971c), bench `~/tracecore-f043`, site test `test_f043`. Amendment **A-141**.

## Đã chốt với người dùng (10/11/2026)

| # | Chỗ tài liệu thiếu / lệch | Chốt |
| --- | --- | --- |
| Q1 | FR-M13-03.2 "Department có cờ nội trú" nhưng Department chưa có cờ; `tc_is_ward` nghĩa là khoa nhận/trả dụng cụ CSSD | **Custom Field mới `Department.tc_inpatient`** (Check). Chỉ khoa có cờ, đang dùng, không phải nhóm mới bị nhắc mẫu số |
| Q2 | FR-M13-02.2 import lại phải cập nhật bản có sẵn; `core.importer` gặp mã đã có thì bỏ qua | **Mở rộng importer**: `ImportKind.upsert`; dòng mã đã có vẫn kiểm và ghi, kết quả `Updated`; `Import Batch Row.result` thêm `Updated`, `Import Batch` thêm `updated` (Int). Bản ghi đã khóa kỳ → lỗi dòng |
| Q3 | FR-M12-07 nhắc "mỗi đợt thiết bị đang mở"; FR-M12-07.2 chỉ nêu thở máy 10:00 | **Mọi đợt đang mở** (thở máy, CVC, thông tiểu): đến giờ nhắc mà trong ngày chưa có phiếu gói ghi sổ gắn đợt → nhắc khoa |
| Q4 | SCR-52 DEPT: FEAT-060 chốt R08/R12 chấm phiếu trên Page `station` | **Portal chỉ liệt kê**: trang `/ksnk-khoa/mau-so` có bảng đợt đang mở + cột "Gói hôm nay" (Đạt / Không đạt / Chưa kiểm tra), nút "Chấm gói" mở Page `station`. Không viết form chấm thứ hai |

## Quyết định thiết kế (mặc định, ghi vào A-141)

- **D1 — Hai DocType M13, không submittable.** `Ward Daily Census` (`MS-.YYYY.-.#####`) và `Device Episode` (`DTB-.YYYY.-.#####`) là bản ghi theo dõi được sửa (cập nhật mẫu số, đóng đợt), giống `IC Network Member` / `Occupational Exposure`: không ai có quyền xóa, `on_trash` chặn, `track_changes` + Audit Log (`_AUDIT_EVENTS`). Mã BN là Password, không vào Audit Log.
- **D2 — Ward Daily Census.** Trường theo architecture §5.3.1: `census_date`, `department`, `department_name`, `patient_count`, `vent_count`, `cvc_count`, `urinary_catheter_count`, `admissions`, `source` (Manual / Import), `locked`; thêm `import_batch` (Link). Khóa DB duy nhất (`census_date`, `department`) (BRU-HAI-002). Kiểm: số ≥ 0; ba số thiết bị ≤ `patient_count`, nêu trường sai (FR-M13-02.1); ngày không ở tương lai; `locked` → chặn mọi sửa (`CENSUS_PERIOD_LOCKED`, FR-M13-11 — mở khóa kỳ là FEAT-063, hàm mở khóa đặt cờ `flags.tc_period_unlock`).
- **D3 — Nhập tay một bản/ngày–khoa.** `census_upsert` không có `census` (tên bản ghi) mà (ngày, khoa) đã có → chặn `CENSUS_DUPLICATE` kèm số đã có (UC-47 E2: màn hiện bản đã có để sửa). Có `census` → sửa đúng bản đó, giữ `source` hiện có trừ khi bản đó là Import thì chuyển Manual. Phát lại offline trùng → 4xx → `core.sync` ghi `Sync Conflict`, bản server giữ nguyên (architecture §ADR-003 dòng mẫu số).
- **D4 — Device Episode.** Trường: `patient_code` (Password) / `patient_code_masked` / `patient_code_hash` qua `core.patient_code.apply`, `birth_year`, `sex`, `department`, `department_name`, `device_type` (Ventilator / Central Line / Urinary Catheter), `inserted_on`, `removed_on` (Date), `status` (Open / Closed, tự tính), `device_days`. Không trường họ tên (BRU-HAI-005). Chặn: `removed_on` < `inserted_on` (FR-M13-04.2), ngày ở tương lai, năm sinh ngoài 1900..năm nay, một người bệnh (hash) không có hai đợt cùng loại thiết bị đang mở ở cùng khoa (`DEVICE_EPISODE_OPEN`). `device_days` = (`removed_on` hoặc hôm nay) − `inserted_on` + 1 (ảnh SCR-55: đặt 29/10, hôm nay 02/11 → 5); đợt mở tính lúc đọc, đợt đóng lưu cố định. Đóng đợt rồi không sửa ngày (sửa nhầm = R11/R01 trên Desk, Audit Log).
- **D5 — Nguồn ngày thiết bị theo khoa (FR-M13-04).** Custom Field `Department.tc_device_day_source` (Select `Daily Census` / `Device Episode`, mặc định Daily Census, hiện khi `tc_inpatient`). Hàm `hai_surveillance.census.denominators(department, from, to)` trả ngày nằm viện (tổng `patient_count`) và ngày thở máy / CVC / thông tiểu theo nguồn của khoa — FEAT-063 dùng tính tỷ suất. Khoa chọn "Mẫu số ngày" vẫn ghi được đợt (đợt cần cho gói dự phòng).
- **D6 — Giờ nhắc (FR-M13-03.1, FR-M12-07.2).** `IC Program Settings` thêm `census_reminder_time` và `bundle_reminder_time` (Time, mặc định 10:00). Scheduler cron 15 phút `hai_surveillance.reminders.run`: sau giờ nhắc, mỗi ngày một lần (khử trùng theo `Notification Delivery` như `environment.remind_missing`):
  - khoa `tc_inpatient` chưa có mẫu số ngày hôm trước → `CENSUS_MISSING` gửi R12 của khoa (User Permission Department) + R11 (FR-M13-03);
  - mỗi đợt đang mở (kể cả đợt đặt hôm nay) chưa có phiếu gói dự phòng ghi sổ trong ngày → `BUNDLE_CHECK_DUE` gửi R08 + R12 của khoa (FR-M12-07). Một thông báo/khoa/ngày liệt kê các đợt (mã che, loại), không gửi từng đợt.
- **D7 — Gói dự phòng gắn đợt (FR-M12-07, BRU-AUD-003).** `Audit Session.device_episode` (Link, có sẵn trong architecture §5.3.1). Module mới `compliance_audit/bundle.py`, gọi từ `sessions.validate`: mẫu `audit_type = Prevention Bundle` với `bundle_type` VAP / CLABSI / CAUTI bắt buộc đợt (`AUDIT_EPISODE_REQUIRED`); đợt phải cùng khoa, đang đặt tại ngày phiếu, đúng loại thiết bị (VAP ↔ Ventilator, CLABSI ↔ Central Line, CAUTI ↔ Urinary Catheter) (`AUDIT_EPISODE_INVALID`); mẫu không phải gói không nhận đợt. Đọc `Device Episode` qua `frappe.db` (Link, không import M13). Chấm tất-cả-hoặc-không đã có (`scoring.all_or_none`, FEAT-060) — FEAT-062 thêm test `@bru("BRU-AUD-003")` 6 mục 5 đạt → Không đạt (FR-M12-07.1).
- **D8 — Trạng thái gói hôm nay.** `hai_surveillance.census.bundle_status(episodes, on)` đọc `Audit Session` ghi sổ (`device_episode`, `audit_date = on`) → Pass / Fail / None (phiếu mới nhất trong ngày). Dùng cho Portal, PDA, nhắc.
- **D9 — Import "Mẫu số ngày" (F-21, EI-SW-010).** `hai_surveillance/imports.py` khai báo ImportKind `ward_census` (`upsert=True`, mã = `<khoa>|<yyyy-mm-dd>`), cột `census_date*`, `department*` (tên khoa hoặc tên đầy đủ, qua `importer.department_ref`), `patient_count*`, `vent_count*`, `cvc_count*`, `urinary_catheter_count*`, `admissions`; kiểm dòng như nhập tay; ghi `source = Import`, `import_batch`. Vai trò R11, R10, R01, System Manager; quyền = quyền tạo Ward Daily Census. Page `tc-import` (SCR-43) thêm Role `TC R11` (danh sách loại vẫn lọc theo `kind.roles`), hiện số "đã cập nhật".
- **D10 — RPC `tracecore.v1.hai.*`.**
  - Trạm/PDA (Station Function mới `CENSUS`, screen_key `census`, vùng Department; vai trò R08, R11, R12): `context` (POST, snapshot offline: khoa được phép, mẫu số ngày chọn + hôm trước để điền sẵn, 7 ngày gần nhất, đợt đang mở + gói hôm nay), `census_upsert`, `device_episode` (`action` = open / close) — `@station_session(..., offline=True)` + `@idempotent`.
  - Portal (đăng nhập; R08, R12 chỉ khoa có User Permission; R11, R01 mọi khoa): `portal_context` (GET), `census_upsert_portal`, `device_episode_portal` (POST, `@idempotent`). Dùng chung dịch vụ `hai_surveillance.census` / `episodes`.
  - Phản hồi chỉ có mã che; mã BN rõ không vào response (Idempotency Key lưu response) và không vào `Sync Conflict` (`sync._redacted` đã bỏ `patient_code`).
- **D11 — Quyền (NFR-SEC-09).** Ma trận thêm 2 dòng: `DT-WDCEN Ward Daily Census` R01 RW, R08 RW, R10 R, R11 RW, R12 RW; `DT-DEVEP Device Episode` R01 RW, R08 RW, R11 RW, R12 RW (R13 không đọc — có mã BN). Không ai xóa. `permission_query_conditions` + `has_permission` theo khoa cho R08/R12 (giống Audit Session). Số dòng ma trận 74 → 76.
- **D12 — Màn hình.** Không có màn WEB mới (SCR-55 là DEPT + PDA) nên không thêm vào `SCREENS` của `tc-ksnk`; Desk vẫn có list/form 2 DocType (cột mã che). PDA: `public/js/station_census.js` (SCR-55 PDA). Portal: `/ksnk-khoa/mau-so` (SCR-55 DEPT) + thanh menu "KSNK khoa" dùng chung (`templates/includes/ksnk_khoa_nav.html`) gắn vào cả trang báo phơi nhiễm (FEAT-071). PDA phiếu gói: `station_audit.js` cho mẫu gói chọn đợt đang mở của khoa (từ `audit.context` — thêm `episodes`) và gửi `device_episode`.
- **D13 — Thông báo** (`core.notification.EVENTS`): `CENSUS_MISSING` ("Daily census missing", Normal, R11), `BUNDLE_CHECK_DUE` ("Prevention bundle check due", Normal, không vai trò mặc định — người nhận do nơi gọi truyền).

## Acceptance criteria (EARS)

- AC-1 (FR-M13-02, BRU-HAI-002): Khi khoa nhập mẫu số (ngày, khoa) đã có, hệ thống phải chặn bản thứ hai và trả số đã có; khi import lại cùng file, hệ thống phải cập nhật bản có sẵn, không tạo trùng.
- AC-2 (FR-M13-02.1): Nếu `vent_count`, `cvc_count` hoặc `urinary_catheter_count` > `patient_count`, hệ thống phải chặn và nêu trường sai (nhập tay: alert-error; import: lỗi theo dòng).
- AC-3 (FR-M13-11/BRU-HAI-002): Nếu mẫu số `locked`, hệ thống phải chặn sửa (nhập tay và import).
- AC-4 (FR-M13-03, .1, .2): Khi qua giờ nhắc (mặc định 10:00, R10 đổi được) mà khoa nội trú chưa có mẫu số hôm trước, hệ thống phải nhắc R12 của khoa và R11 một lần/ngày; khoa không có cờ nội trú không bị nhắc.
- AC-5 (FR-M13-04, .1, .2, BRU-HAI-005): Khi ghi đợt thiết bị, hệ thống phải lưu mã BN mã hóa + hash + mã che, tính số ngày thiết bị, chặn `removed_on` < `inserted_on`; danh sách chỉ hiện mã che; DocType không có trường họ tên.
- AC-6 (FR-M13-04): R10/R01 chọn nguồn ngày thiết bị cho từng khoa; `denominators` trả ngày thiết bị theo nguồn đó.
- AC-7 (FR-M12-07, .1, BRU-AUD-003): Phiếu gói dự phòng VAP/CLABSI/CAUTI phải gắn đợt đang mở đúng loại, cùng khoa; 6 mục 5 đạt → Không đạt.
- AC-8 (FR-M12-07.2): Qua giờ nhắc gói mà đợt đang mở chưa có phiếu gói ghi sổ trong ngày → nhắc R08/R12 của khoa.
- AC-9 (NFR-SEC-09): R12 khoa A không đọc được mẫu số/đợt của khoa B; R13 không đọc Device Episode.
- AC-10 (NFR-AVAIL-05): `census_upsert`, `device_episode` là `@idempotent`, nhận phát lại offline; gửi lại cùng khóa không tạo trùng.

## Tasks (TDD — test `FrappeTestCase` trước, thấy fail rồi mới code)

- **T0 Amendment A-141 (docs, trước code):** architecture Revision History + §5.3.1 (trường thêm, Custom Field Department, IC Program Settings, Import Batch), srs Revision History (ghi chú Q1–Q4), implementation-plan dòng FEAT-062 thêm "A-141", rtm FR-M13-02/03/04, FR-M12-07 cột Design/Tests. Commit `docs: A-141 ...`.
- **T1 DocType + Custom Field + settings** (D1, D2, D4, D5, D6): JSON 2 DocType, `custom_field.json` (Department `tc_inpatient`, `tc_device_day_source`), `IC Program Settings` 2 trường Time, `Audit Session.device_episode`, `Import Batch.updated`, `Import Batch Row.result` + Updated. Test: unique (ngày, khoa) ở DB; JSON không có trường họ tên (`@bru("BRU-HAI-005")`).
- **T2 `hai_surveillance/census.py`** (D2, D3, D5, D8): `validate_census`, `upsert`, `denominators`, `bundle_status`, `recent`. Test `@bru("BRU-HAI-002")` (trùng, khóa), FR-M13-02.1, denominators theo 2 nguồn.
- **T3 `hai_surveillance/episodes.py`** (D4): `validate_episode`, `open_episode`, `close_episode`, `device_days`. Test FR-M13-04.2, mã che/hash, trùng đợt mở.
- **T4 `compliance_audit/bundle.py`** (D7): kiểm đợt cho phiếu gói. Test `@bru("BRU-AUD-003")` 6 mục 5 đạt → Fail; thiếu/sai loại/khác khoa → chặn.
- **T5 Importer upsert + kind `ward_census`** (D9): `core.importer` (`upsert`, `Updated`), `hai_surveillance/imports.py`, hook `tracecore_import_kinds`, `tc_import` roles + nhãn. Test import → tạo; import lại → Updated, không trùng; dòng sai → lỗi theo dòng; bản khóa → lỗi.
- **T6 Nhắc** (D6, D13): `hai_surveillance/reminders.py`, cron 15 phút, EVENTS. Test giờ nhắc, khoa không nội trú, một lần/ngày, gói đã chấm không nhắc.
- **T7 Quyền** (D11): `permissions.py` query/has_permission, `permission_matrix.csv`, `custom_docperm.json` sinh lại, `test_permissions*.py`. Test R12 khoa A/B, R13.
- **T8 RPC `v1/hai.py`** (D10) + Station Function `CENSUS` (seed, navigation, station_help, custom field option), `audit.context` thêm `episodes`, `audit.submit_session` thêm `device_episode`. Test RPC (station + portal), idempotent, response không chứa mã rõ.
- **T9 UI**: `station_census.js` (PDA, 4 trạng thái, ô số ≥ 16 px, nút 56 px, offline queue `TC_QUEUEABLE`), `station.js` case + offline + prefix, `station_audit.js` chọn đợt; Portal `/ksnk-khoa/mau-so` (html/py/js/css chỉ token `--tc-*`) + nav dùng chung; `vi.csv`.
- **T10 Kiểm:** test các module đụng (`--module`, lần lượt), `test_permissions`, `test_permissions_v112`, `test_name_columns`; diff-cover ≥ 70 %; pre-commit; push nhánh.

## Ngoài phạm vi (follow-up)

- Khóa/mở khóa kỳ `IC Reporting Period`, tính tỷ suất, reveal mã BN chung `hai.reveal_patient_code` (FEAT-063).
- Cổng khoa đầy đủ (chỉ số khoa, việc cần làm, FR-M9-26 — FEAT-065); menu "Cách ly" (FEAT-068).
- Mở form phiếu trên Page `station` chọn sẵn đợt từ Portal (hiện chỉ mở trạm).
