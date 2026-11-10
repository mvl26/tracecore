# FEAT-065 Bảng chỉ số KSNK toàn viện, báo cáo Hội đồng, Cổng khoa, tự đánh giá QĐ 38 — kế hoạch

> Nguồn: `docs/implementation-plan.md` §3 E-19 (FEAT-065), DoD v1.12 §6.1; `docs/srs.md` FR-M9-24 (.1, .2), FR-M9-25 (.1, .2), FR-M9-26 (.1), FR-M9-29 (.1), BRU-RPT-001..003, NFR-PERF-05, NFR-PRIV-01, NFR-SEC-09; `docs/use-cases.md` UC-57 (bước 3, 4, 5, 7; A1; E1, E3, E5, E6); `docs/architecture.md` ADR-014, ADR-015, §5.3 (IC Indicator, IC Indicator Value, IC Annual Plan), §8.5 (bảng chỉ số materialized); `docs/ux-foundations.md` SCR-66, A6, A-131; ảnh `docs/design-refs/v1.12/SCR-66_BangChiSoKSNK.png`.
> Phụ thuộc: FEAT-056 (engine chỉ số, khung `tc-ksnk`), FEAT-058 (IC Annual Plan), FEAT-060/061/066 (M12), FEAT-062 (mẫu số, Portal `/ksnk-khoa`), FEAT-067 (M14), FEAT-071 (M16). Sprint S7. Cỡ M.
> Nhánh: `feat/FEAT-065-ic-dashboard` (bench phụ `~/tracecore-f032`, site test `test_f032`), cắt từ `develop` 203bf1a.
> Song song FEAT-063 (A-144), FEAT-068 (A-146): file dùng chung chỉ **nối thêm** khối có comment `# FEAT-065`.

## Ngoài phạm vi

- FR-M9-27 (khóa kỳ, tính giá trị) và FR-M9-28 (nhập file, hồ sơ ánh xạ cột): FEAT-056 đã làm. Màn này chỉ có nút mở SCR-43 (`/app/tc-import`).
- FR-M9-30 gói hồ sơ KSNK cho đoàn kiểm tra: FEAT-074.
- Việc cần làm "cách ly đang mở" (M14 cách ly, FEAT-068) và "cảnh báo cụm ca" (M13, FEAT-063): các FEAT đó tự đăng ký vào hook `tracecore_ksnk_todos`. Chỉ tiêu QĐ 38 "phòng cách ly" để FEAT-068 đăng ký `isolation_rooms` vào `tracecore_ic_self_checks`. Đến lúc đó dòng này là Thủ công.
- Dashboard CSSD (FR-M9-01, SCR-32) giữ nguyên (UC-57 A3).

## Đã chốt với người dùng (10/11/2026) — Amendment A-145

- **Q1 — Tự đánh giá QĐ 38.** Tạo 3 DocType mới ở module `Admin Reports`:
  - `IC QD38 Criterion`: danh mục chỉ tiêu, `name` = `criterion_code`. Seed chỉ chèn mã còn thiếu, không ghi đè bản bệnh viện đã sửa (NFR-MAINT-04). R01 sửa được; ngưng dùng thì bỏ `is_active`, không xóa.
  - `IC Self Assessment`: mỗi năm một bản, `TDG-{year}`, submittable, R01 ghi sổ.
  - Child `IC Self Assessment Item`: chỉ tiêu, nguồn Tự động/Thủ công, trạng thái, tham chiếu nguồn, minh chứng, ghi chú.
  - Phần tự động lấy từ hook mới `tracecore_ic_self_checks`, hoặc từ `IC Indicator Value` cả năm khi chỉ tiêu có Link `indicator`.
- **Q2 — Báo cáo Hội đồng.** DocType mới `IC Council Report` (`BCHD-{period}`, mỗi kỳ một bản) gồm: kỳ, `report_status` Tạm/Chính thức, file PDF private, thời điểm sinh.
  - Báo cáo cho kỳ tháng trước.
  - Ngày làm việc tính T2–T6, trừ ngày nghỉ trong Holiday List mặc định của Company.
  - R10 cấu hình `council_report_workday` (mặc định 5) trong `IC Program Settings`.
  - Cron 07:00 kiểm ngày, sinh PDF, rồi `notification.emit("IC_COUNCIL_REPORT")` cho R01 và R13.
  - Khóa kỳ khi kỳ đã có bản Tạm thì sinh lại bản Chính thức (UC-57 A1).
- **Q3 — Việc cần xử lý.** Hook mới `tracecore_ksnk_todos(user, department)`. FEAT-065 viết hàm trong **file mới** của từng module:
  - M13: mẫu số ngày thiếu.
  - M11: hoạt động kế hoạch quá hạn.
  - M12: phiếu theo lịch chưa đủ chỉ tiêu kỳ hiện tại.
  - M16: bước theo dõi phơi nhiễm đến hạn hoặc quá hạn, chỉ đếm số, không tên.
  - M9: báo cáo Hội đồng mới nhất.
- **Q4 — Danh sách chỉ số và KPI.** Bảng lấy các dòng `IC Plan Indicator` của kế hoạch năm đã ghi sổ.
  - Mục tiêu dùng `target` của kế hoạch; thiếu thì dùng `national_target`. Hướng so sánh lấy `IC Indicator.target_direction`.
  - 8 ô KPI là 8 dòng đầu theo thứ tự kế hoạch.
  - Năm chưa có kế hoạch duyệt: hiện mọi `IC Indicator` đang dùng, kèm cảnh báo.
  - Cổng khoa: "trung bình toàn viện" là dòng toàn viện (khoa trống) của `IC Indicator Value`.

## Quyết định thiết kế (mặc định, ghi vào A-145)

- **D1 — Đọc, không tính lại (NFR-PERF-05).** `tracecore.v1.indicator.board` chỉ đọc `IC Indicator Value`, cả kỳ đã khóa lẫn dòng tạm chưa khóa. Dòng chưa khóa mang nhãn "Tạm". Không gọi `core.indicators.registry` khi mở bảng (có test chặn). Mỗi lần mở chạy 4 truy vấn gộp:
  - giá trị 12 tháng × chỉ số × phạm vi đang lọc;
  - giá trị theo khoa của chỉ số biểu đồ, kỳ mới nhất;
  - kế hoạch năm;
  - báo cáo Hội đồng và tự đánh giá.
- **D2 — Trạng thái bằng chữ.** Dùng lại `indicator.status` với mục tiêu của kế hoạch: Met (Đạt), Not met (Chưa đạt), Not calculated (Không tính, mẫu số 0 — BRU-RPT-001), Insufficient sample (Chưa đủ mẫu), "Không có dữ liệu" khi kỳ không có giá trị. Badge luôn có chữ. Ô KPI có viền màu kèm chữ trạng thái; thanh biểu đồ dưới mục tiêu có ký hiệu "↓".
- **D3 — Xu hướng 12 tháng.** Bảng hiện 3 cột tháng gần nhất như ảnh, kèm cột "Xu hướng 12 tháng": sparkline SVG inline dùng token màu, có `aria-label` liệt kê giá trị. Bộ lọc khoa đổi phạm vi cho cả bảng và KPI.
- **D4 — Biểu đồ theo khoa.** Chỉ số đầu tiên của kế hoạch thuộc nhóm `Hand Hygiene` có giá trị theo khoa, không có thì dùng chỉ số đầu tiên có giá trị khoa. Có select đổi chỉ số. Chỉ hiện khi lọc "Toàn viện".
- **D5 — Báo cáo Hội đồng (BRU-RPT-002, FR-M9-25.2).**
  - Nội dung chỉ gồm số liệu tổng hợp: chỉ số (mã, tên, mục tiêu, giá trị 3 kỳ, trạng thái) và việc nổi bật (`title` + `count` của todo toàn viện, không dùng `detail`).
  - Print Format Jinja "TC IC Council Report" (doc_type `IC Council Report`, A4 dọc, một trang), ngữ cảnh lấy qua `tc_ic_council_context(name)` trong `jinja.methods`. Dấu "TẠM" khi kỳ chưa khóa.
  - Kỳ chưa khóa: scheduler gọi `indicator.compute_period` để có giá trị tạm (đây là việc của scheduler, không phải lúc mở bảng).
  - R01 có thêm nút "Sinh lại" trên màn; RPC `council_generate` chỉ R01.
- **D6 — Lịch.** Cron mới `"0 7 * * *": tracecore.admin_reports.council_report.run_daily` (khóa cron mới, không đổi dòng cũ).
  - Hàm `nth_working_day(year, month, n)` bỏ T7, CN và ngày trong Holiday List của Company mặc định (nếu có).
  - Đúng ngày thì sinh báo cáo kỳ tháng trước, idempotent: đã có bản Chính thức thì bỏ qua; có bản Tạm mà kỳ vẫn chưa khóa thì bỏ qua.
  - `indicator.lock_period` gọi `council_report.on_period_locked(period)`: kỳ có bản Tạm thì sinh lại thành Chính thức và thông báo lại. Cùng module M9 nên không vi phạm import chéo.
- **D7 — Cổng khoa (FR-M9-26).**
  - Portal `/ksnk-khoa/chi-so` (`www/ksnk_khoa/chi_so.{py,html,css}`) và thêm mục vào `templates/includes/ksnk_khoa_nav.html`.
  - Quyền như `/ksnk-khoa/mau-so`: R08, R12 chỉ khoa có User Permission Department; R11, R01 mọi khoa. Khoa không thuộc quyền thì từ chối (FR-M9-26.1, UC-57 E3).
  - Bảng: chỉ số, giá trị khoa, giá trị toàn viện, mục tiêu, trạng thái chữ, kỳ gần nhất. Danh sách việc cần làm của khoa lấy từ hook.
  - Shell `tc-ksnk` cho R12 (trạng thái `dept`) thêm liên kết tới `/ksnk-khoa/chi-so`.
- **D8 — Tự đánh giá (FR-M9-29, .1).**
  - RPC `self_assessment(year)` (đọc), `self_assessment_prepare(year)` (R01: tạo Nháp nếu chưa có, điền/làm mới các dòng Tự động; không động vào dòng Thủ công), `self_assessment_set(year, criterion, status, evidence, note)` (R01: dòng thành Thủ công), `self_assessment_submit(year)` (R01 ghi sổ).
  - Trạng thái: `Met` / `Not met` / `Needs confirmation` (Cần R01 xác nhận) / `Not assessed` (Chưa đánh giá).
  - Hàm tự kiểm đăng ký qua `tracecore_ic_self_checks`, trả `{key: fn(year) -> {"status", "source_ref"}}`:
    - M11 `ic_plan_approved`
    - M12 `ic_chemical_quarterly` (mọi quý đã qua trong năm có `IC Chemical Consumption` đã ghi sổ)
    - M13 `hai_surveillance_active` (đếm ngày mẫu số và đợt thiết bị → Cần R01 xác nhận / Chưa đạt)
    - M14 `amr_surveillance` (đếm chủng phân lập → Cần R01 xác nhận / Chưa đạt)
  - Chỉ tiêu có `indicator`: cộng tử/mẫu số các kỳ đã khóa trong năm rồi so mục tiêu.
  - Seed 8 chỉ tiêu (msgid tiếng Anh, bản Việt ở `vi.csv`): PLAN, TRAIN, CHEM, HAI, AMR, ISO, QI, IT.
- **D9 — Quyền** (ma trận 78 → **81**):

  | Mã | DocType | R01 | R10 | R11 | R13 |
  | --- | --- | --- | --- | --- | --- |
  | DT-ICCR | IC Council Report | R | R | R | R |
  | DT-ICQD38 | IC QD38 Criterion | RW | R | R | R |
  | DT-ICSA | IC Self Assessment | RWS | R | R | R |

  - Child không có dòng trong ma trận. `IC Council Report` chỉ hệ thống ghi.
  - Màn `chi-so` giữ vai trò như cũ. Cổng khoa không đổi quyền Page `tc-ksnk`.
  - Portal đọc `IC Indicator Value` phía server sau khi đã kiểm khoa (R08 không có DocPerm đọc).
- **D10 — Amendment A-145.** Cập nhật Revision History và §5.3 của architecture (4 DocType, trường `council_report_workday`, 2 hook mới), naming §5.3.3, và implementation-plan (ghi A-145 vào dòng FEAT-065). Không đổi FR/BRU.

## Acceptance criteria (EARS)

- **AC-065-01** (FR-M9-24, .1; Q4): Khi R01 hoặc R13 mở SCR-66 với năm có kế hoạch đã ghi sổ, hệ thống phải hiện đúng các chỉ số của kế hoạch theo thứ tự kế hoạch. Mỗi chỉ số có mục tiêu của kế hoạch, giá trị 3 kỳ gần nhất, xu hướng 12 tháng, cỡ mẫu và trạng thái bằng chữ.
- **AC-065-02** (FR-M9-24.1, NFR-PERF-05, D1): Khi mở bảng, hệ thống phải chỉ đọc `IC Indicator Value`, không gọi hàm tính.
- **AC-065-03** (NFR-PERF-05): Với dữ liệu giả 24 tháng × 32 khoa × 20 chỉ số, RPC bảng phải trả về trong ≤ 3 s.
- **AC-065-04** (BRU-RPT-001): Nếu chỉ số có mẫu số 0, hệ thống phải hiện "Không tính", không hiện 0, trên bảng, ô KPI, Cổng khoa và báo cáo Hội đồng.
- **AC-065-05** (FR-M9-24): Khi chọn khoa, hệ thống phải hiện giá trị của khoa đó.
- **AC-065-06** (FR-M9-24.2): Hệ thống phải chỉ cho R01, R10, R11, R13 mở bảng toàn viện; R13 chỉ đọc. R02 gọi RPC phải bị từ chối.
- **AC-065-07** (FR-M9-25; D6): Vào ngày làm việc thứ `council_report_workday` của tháng, lúc 07:00, hệ thống phải sinh `IC Council Report` kỳ tháng trước kèm file PDF và thông báo R01, R13. Ngày khác thì không sinh. Chạy lại cùng ngày không tạo bản trùng.
- **AC-065-08** (FR-M9-25, UC-57 A1): Nếu kỳ chưa khóa, hệ thống phải sinh bản "Tạm". Khi kỳ được khóa sau đó, hệ thống phải sinh lại bản "Chính thức".
- **AC-065-09** (FR-M9-25.1): Hệ thống phải cho R10 đổi `council_report_workday` (1–23). Ngày nghỉ trong Holiday List không tính là ngày làm việc.
- **AC-065-10** (FR-M9-25.2, BRU-RPT-002, NFR-PRIV-01): Báo cáo Hội đồng phải không chứa dữ liệu cá nhân hay mã người bệnh. Nội dung chỉ lấy số liệu tổng hợp.
- **AC-065-11** (BRU-RPT-003): Nếu dữ liệu nguồn đổi sau khi kỳ đã khóa, báo cáo và bảng phải vẫn hiện giá trị đã khóa.
- **AC-065-12** (FR-M9-26): Khi R12 mở Cổng khoa, hệ thống phải hiện chỉ số khoa mình cạnh giá trị toàn viện và danh sách việc cần làm của khoa (mẫu số thiếu, hoạt động quá hạn, phiếu chưa đủ, theo dõi phơi nhiễm).
- **AC-065-13** (FR-M9-26.1): Nếu R12 khoa A yêu cầu khoa B, hệ thống phải từ chối.
- **AC-065-14** (FR-M9-29, .1): Khi R01 lập tự đánh giá năm, hệ thống phải điền sẵn các chỉ tiêu tính được với nguồn "Tự động". Các dòng còn lại "Chưa đánh giá", R01 sửa tay thành nguồn "Thủ công". Làm mới không ghi đè dòng Thủ công. R01 ghi sổ thì khóa bản. R13 chỉ xem.
- **AC-065-15** (UC-57 bước 3, ảnh SCR-66): Màn có đủ 4 trạng thái loading / empty / error / offline và mọi chuỗi qua `__()`/`_()`.

## Tasks (TDD — viết test `FrappeTestCase` trước, thấy fail, rồi mới code)

- **T1 Amendment A-145** (docs): architecture Revision History, §5.3 M9 (4 DocType, trường settings, 2 hook), §5.3.3 naming; implementation-plan dòng FEAT-065.
- **T2 DocType** (AC-065-07, 14; D9): `IC Council Report`, `IC QD38 Criterion`, `IC Self Assessment` + `IC Self Assessment Item`; trường `council_report_workday` trong `IC Program Settings`. Doc events Audit Log, chặn xóa. Ma trận 81 dòng, `custom_docperm.json`, test_permissions 81, test_permissions_v112, test_name_columns.
- **T3 Hook việc cần làm** (AC-065-12; Q3): `core/ksnk_todos.py` (sổ + gộp), các hàm ở `hai_surveillance/todos.py`, `infection_program/todos.py`, `compliance_audit/todos.py`, `occupational_safety/todos.py`, mỗi hàm có test trong module của nó.
- **T4 RPC bảng** (AC-065-01..06, 11): `admin_reports/ic_board.py` + `tracecore.v1.indicator.board`. Test: thứ tự/mục tiêu theo kế hoạch, fallback khi chưa có kế hoạch, lọc khoa, không gọi registry, quyền, BRU-RPT-001, giá trị Tạm. Test hiệu năng dữ liệu giả insert hàng loạt (`frappe.db.bulk_insert`).
- **T5 Báo cáo Hội đồng** (AC-065-07..11): `admin_reports/council_report.py` (ngày làm việc, run_daily, generate, on_period_locked), Print Format, `jinja.methods`, cron, `IC_COUNCIL_REPORT` vào rule mặc định; RPC `council_generate` (R01), `council_reports`.
- **T6 Tự đánh giá** (AC-065-14): `admin_reports/self_assessment.py`, seed `admin_reports/self_assessment_seed.py` (after_migrate + patch), self-check ở `infection_program/self_checks.py`, `compliance_audit/self_checks.py`, `hai_surveillance/self_checks.py`, `microbiology/self_checks.py`; RPC 4 hàm; Print Format "TC IC Self Assessment".
- **T7 Màn SCR-66** (AC-065-15, D2–D4): viết lại `public/js/ksnk/scr_66_chi_so.js` theo ảnh; CSS dùng token trong `ksnk` css có sẵn; test JS nhỏ của hàm thuần (nếu repo có test JS) hoặc test `test_ksnk_nav`.
- **T8 Cổng khoa** (AC-065-12, 13): Portal `/ksnk-khoa/chi-so` + nav + liên kết từ trạng thái `dept` của shell; test get_context theo vai trò.
- **T9 Patch site đang chạy**: `patches.txt` chạy seed chỉ tiêu QĐ 38 và Notification Rule mặc định.
- **T10 Kiểm**: chạy lần lượt từng module test bị đụng, `test_permissions`, `test_permissions_v112`, `test_name_columns`, `test_ksnk_nav`; diff-cover ≥ 70 %; `pre-commit run --all-files`; push nhánh lên GitHub.
