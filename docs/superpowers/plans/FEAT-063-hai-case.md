# FEAT-063 — Định nghĩa ca NKBV có phiên bản, ca NKBV, kỳ báo cáo, tỷ suất, che mã BN

> Kế hoạch theo `docs/implementation-plan.md` E-14 dòng FEAT-063 (M13 `hai_surveillance`, S7, cỡ L). Không brainstorm:
> thiết kế đã duyệt theo A-113. Chỗ tài liệu lệch/thiếu ghi ở **Amendment A-144** (người dùng chọn phương án đề xuất
> Q1–Q3 trong chat ngày 10/11/2026).

**Nhánh:** `feat/FEAT-063-hai-case` (bench `~/tracecore-f043`, site test `test_f043`), cắt từ `origin/develop` 203bf1a.

**Đầu vào:** FR-M13-01, 01.1, 05, 05.1, 05.2, 06, 06.1, 10, 10.1, 10.2, 11, 11.1, 15, 15.1..15.3; BRU-HAI-001, 002,
005, 006, BRU-RPT-003; NFR-PRIV-01, NFR-PRIV-02, NFR-MAINT-04, NFR-SEC-09; UC-48; SCR-56, SCR-58 (phần tỷ suất);
architecture §5.3.1 (M13), §5.3.3, ADR-010 mở rộng, ADR-015; ảnh `docs/design-refs/v1.12/SCR-56_CaNKBV.png`,
`SCR-58_BaoCaoNKBV.png`.

## Quyết định (A-144)

| # | Chốt | Lý do |
| :- | :- | :- |
| Q1 | `IC Reporting Period` đặt tên `KY-<YYYY>-<MM>` theo trường `month` (YYYY-MM, duy nhất), thay `KY-.YYYY.-.##` | Ảnh SCR-56 ghi KY-2026-11 cho tháng 11; một kỳ mỗi tháng |
| Q2 | Ca không đạt ngưỡng thời gian (FR-M13-06): cảnh báo; Xác định phải có `exception_reason`; R11 hoặc R01 xác định được; lý do lưu trên ca + Audit Log | FR-M13-06 ("cảnh báo và yêu cầu ghi lý do") thắng chữ trên ảnh |
| Q3 | NFR-PRIV-02 ở FEAT-063: job hằng ngày xóa định danh `HAI Case` đã ghi sổ và `Device Episode` đã đóng quá `IC Program Settings.patient_data_retention_months` (trống = không xóa) | Chủng vi sinh (M14) để FEAT khác |
| a | `HAI Case Definition`: `def_code`, `title`, `infection_site` (7 giá trị §5.3.1), `device_type` (trống / Ventilator / Central Line / Urinary Catheter), `min_hours_after_admission`, `min_device_days_before_onset`, `version_no`, `effective_from`, `legal_ref`, `superseded_by`; child `HAI Case Definition Criterion` (`criterion`). Tên `DN-<def_code>-V<n>` (`core.versioning`); ghi sổ = R01 duyệt, khóa; sửa = nhân bản thành Nháp V(n+1) | Cùng mẫu `MDRO Rule` (FEAT-067) |
| b | `HAI Case` (`CA-.YYYY.-.#####`, submittable): Nháp = Nghi ngờ; R11/R01 "Xác định" hoặc "Loại trừ" = đặt `status` rồi ghi sổ. `admission_at` là Datetime (ngưỡng giờ). `def_code` chọn mã định nghĩa; hệ thống gắn `case_definition` = phiên bản đã duyệt mới nhất có `effective_from` ≤ `onset_date` (bản chụp; phiên bản đã duyệt bất biến). `surgical_surveillance` để FEAT-064 thêm (DocType chưa có). `outcome` (Under Treatment / Recovered / Transferred / Died / Unknown, sửa được sau ghi sổ). `isolates` child `HAI Case Isolate` (Link Microbiology Isolate, cùng người bệnh theo hash), `mdro_flags` | §5.3.1 + ảnh SCR-56 |
| c | Ngưỡng thời gian: số giờ từ `admission_at` tới 00:00 của `onset_date` ≥ `min_hours_after_admission` (bảo thủ: không tính phần giờ trong ngày khởi phát); ngày thiết bị trước khởi phát = `onset_date − inserted_on` (ngày đặt là ngày 1, không tính ngày khởi phát) ≥ `min_device_days_before_onset`. Kết quả `time_check` Met / Not met / Not applicable + `time_check_note` | Không mã hóa ngưỡng; ngưỡng lấy từ phiên bản (FR-M13-06.1) |
| d | Khóa kỳ: `hai_surveillance.periods.lock(month)` (R01) đặt `locked` cho kỳ và mọi `Ward Daily Census` của tháng, Audit Log; RPC `tracecore.v1.hai_case.lock_period` gọi tiếp `admin_reports.indicator.lock_period` (M9 tính `IC Indicator Value`). Mở khóa: R01 + lý do → census `locked=0`, Audit Log, `indicator.unlock_period`. Lớp `v1` điều phối nên M13 không import M9 | architecture §5.2 không import chéo |
| e | Kỳ đã khóa chặn: tạo/sửa/ghi sổ/hủy `HAI Case` có `onset_date` thuộc kỳ; tạo `Ward Daily Census` mới thuộc kỳ (FEAT-062 đã chặn sửa bản `locked`) | FR-M13-11, 11.1 |
| f | Tỷ suất (hook `tracecore_ic_indicators`, khóa `HAI_RATE`, `VAP_RATE`, `CLABSI_RATE`, `CAUTI_RATE`, `VENT_UTILIZATION`, `CVC_UTILIZATION`, `URINARY_UTILIZATION`): tử số = ca **Xác định** đã ghi sổ có `onset_date` trong tháng; VAP/CLABSI/CAUTI chọn theo `device_type` của phiên bản định nghĩa (không theo chuỗi mã); mẫu số từ `census.denominators` (FEAT-062). Mẫu số 0 → "Không tính" (`admin_reports.indicator.measure`, BRU-HAI-006). Danh mục `IC Indicator` vẫn do R01/R10 tạo (như FEAT-058..071) | FR-M13-10 |
| g | Màn trong Page `tc-ksnk`: `ca-nkbv` (SCR-56: danh sách ca che mã, hồ sơ ca, kiểm tra thời gian, Xem mã BN, Xác định/Loại trừ/Gắn chủng, kỳ báo cáo + khóa/mở khóa) và `bao-cao-nkbv` (SCR-58 phần FEAT-063: chọn kỳ, xu hướng 12 tháng, bảng theo khoa). Tạo ca Nghi ngờ trên Desk form `HAI Case` (R08/R12 khoa mình). Cụm ca, cắt ngang, xuất NKVM thuộc FEAT-064/069/072 | implementation-plan "Desk form submittable" |
| h | Hook `tracecore_mdro_detected` (FEAT-067): chủng đa kháng mới → cộng nhãn vào `mdro_flags` của mọi ca chưa hủy cùng người bệnh (hash) | §5.3.1 HAI Case |
| i | `microbiology.resistance.hai_with_pathogen_rate` đọc `HAI Case` qua `frappe.db` (không import M13): % ca Xác định trong quý có ≥ 1 chủng gắn | A-136 Q8 |
| j | Ma trận quyền +3 dòng (78 → **81**): DT-HAIDEF (R01 RWS, R08 R, R10 R, R11 R, R12 R), DT-HAICASE (R01 RWSA, R08 RW, R11 RWS, R12 RW), DT-ICPER (R01 RW, R10 R, R11 R, R13 R). R13 không đọc ca (FR-M13-15.3). `HAI Case` tham gia `permission_query_conditions` theo khoa (R08/R12) | NFR-SEC-09 |

## Tasks (TDD: test `FrappeTestCase` trước, thấy đỏ, rồi code)

### T1 Amendment A-144 (docs) — DoD v1.12
- architecture Revision History + §5.3.1 (3 dòng M13 + 2 child) + §5.3.3 (KY-YYYY-MM); srs Revision History ghi chú;
  implementation-plan dòng FEAT-063; ux-foundations SCR-56/58; rtm FR-M13-01/05/06/10/11/15.

### T2 HAI Case Definition — FR-M13-01, 01.1, 06.1; BRU-HAI-001; NFR-MAINT-04
- Test `test_definitions.py`: tên `DN-VAP-V1`; một Nháp mỗi mã; phiên bản đã duyệt bất biến; nhân bản → V2;
  `effective_for(code, onset)` chọn V1 khi khởi phát trước `effective_from` của V2 (@bru BRU-HAI-001); seed Nháp
  không ghi đè bản đã sửa, chạy hai lần không trùng (NFR-MAINT-04).
- Code: DocType + child, `hai_surveillance/definitions.py`, `hai_surveillance/seed.py` (after_migrate).

### T3 HAI Case — FR-M13-05, 05.1, 05.2, 06; BRU-HAI-005; FR-M13-15, 15.1
- Test `test_cases.py`: gắn phiên bản tại ngày khởi phát; thiếu phiên bản đã duyệt → chặn; Loại trừ không lý do →
  chặn (FR-M13-05.2); R12/R08 không xác định được (FR-M13-05.1); R11 xác định → `confirmed_by`; không đạt ngưỡng →
  `time_check = Not met`, xác định cần `exception_reason` (@bru BRU-HAI-001); mã BN chỉ dạng che trong danh sách,
  JSON DocType không có trường họ tên (@bru BRU-HAI-005); gắn chủng khác người bệnh → chặn; hook đa kháng gắn nhãn.
- Code: DocType + child + controller, `hai_surveillance/cases.py`, `permissions.py` (case_query).

### T4 Kỳ báo cáo — FR-M13-11, 11.1; BRU-HAI-002, BRU-RPT-003
- Test `test_periods.py`: chỉ R01 khóa; khóa → census của tháng `locked`, sửa bị chặn (11.1), tạo census mới
  bị chặn, ca thuộc kỳ không sửa/ghi sổ được; mở khóa cần lý do, Audit Log; RPC khóa ghi `IC Indicator Value` locked.
- Code: DocType `IC Reporting Period`, `hai_surveillance/periods.py`, sửa `census.validate`.

### T5 Tỷ suất — FR-M13-10, 10.1, 10.2; BRU-HAI-006
- Test `test_indicators.py`: 2 ca VAP / 410 ngày thở máy → 4,878… (‰, hiển thị 4,9); mẫu số 0 → "Not calculated"
  (@bru BRU-HAI-006); ca Nghi ngờ / Loại trừ không tính; toàn viện = tổng các khoa.
- Code: `hai_surveillance/indicators.py`, hook.

### T6 RPC + màn SCR-56/58 — UC-48; FR-M13-15.2, 15.3; NFR-PRIV-01
- Test `v1/tests/test_hai_case_api.py`, `tests/test_ksnk_scr56.py`: RPC list chỉ mã che; reveal ghi Audit "View
  Patient Code"; R13 bị từ chối danh sách ca nhưng xem được tỷ suất; export Desk của HAI Case không chứa mã rõ
  (NFR-PRIV-01); JS render đủ trạng thái loading/empty/error, badge có chữ, không hex/px.
- Code: `v1/hai_case.py`, `public/js/ksnk/scr_56_ca_nkbv.js`, `scr_58_bao_cao_nkbv.js`, `ui/ksnk.py` SCREENS,
  `hai_case.js` (Desk form), CSS dùng lớp `tc-ksnk-*` sẵn có.

### T7 Xóa định danh — NFR-PRIV-02
- Test `test_retention.py`: trống → không xóa; quá hạn → xóa mã/hash/năm sinh, giữ số liệu, Audit Log mỗi bản.
- Code: `hai_surveillance/retention.py`, scheduler daily.

### T8 Dùng chung
- permission_matrix (+3), test_permissions (81), test_permissions_v112, custom_docperm (migrate → write_fixture →
  migrate), hooks (doc_events, permission query, ic_indicators, mdro_detected, after_migrate, scheduler),
  core/errors + error_codes + test_errors, name_columns nếu cần, vi.csv, `microbiology.resistance`.

## Kiểm (người dùng chốt: không full suite)
Lần lượt `bench --site test_f043 run-tests --app tracecore --module …` cho mọi module test bị đụng, cộng
`tracecore.tests.test_permissions`, `test_permissions_v112`, `test_name_columns`, `tracecore.ui.tests.test_ksnk_nav`;
`diff-cover coverage.xml --compare-branch=origin/develop --fail-under=70`; `pre-commit run --all-files`. Không E2E.
