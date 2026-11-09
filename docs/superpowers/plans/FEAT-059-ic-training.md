# FEAT-059 Đào tạo KSNK trên HRMS Training và sinh viên thực tập — kế hoạch

> Nguồn: `docs/implementation-plan.md` §3 E-12 (FEAT-059), §6.1 DoD v1.12; `docs/srs.md` FR-M11-09 (+ .1, .2), FR-M11-10 (+ .1), FR-M11-11 (+ .1), FR-M4-02, BRU-ICP-001, BRU-RPT-001; `docs/use-cases.md` UC-42 (bước 1–4, A1, A2, E1–E3); `docs/architecture.md` §5.3.1 (Trainee Induction, HRMS Training Program/Event/Result + Custom Field `tc_ic_category`), §5.3.3 (`SV-.YYYY.-.#####`), ADR-009, A-131; `docs/ux-foundations.md` SCR-49; ảnh `docs/design-refs/v1.12/SCR-49_DaoTao.png`.
> Phụ thuộc: FEAT-056, FEAT-057 (đã merge `develop` 9a27e60). FEAT-058/060 đang merge — merge `origin/develop` mới vào nhánh trước full suite. Sprint S6. Cỡ S.
> Nhánh: `feat/FEAT-059-ic-training` (bench phụ `~/tracecore-f043`, site test `test_f043`).
> Không đụng: Page `station`, `tracecore-theme.css`, Portal, màn M1–M10, engine M9 (`admin_reports/indicator.py`), DocType của HRMS (chỉ thêm Custom Field). File dùng chung chỉ **nối thêm** (hooks, ma trận quyền, `vi.csv`, `EVENTS`, `ui/ksnk.py`, `tc_ksnk.css`, `custom_field.json`).
> Ngoài phạm vi: phần "Cải tiến chất lượng & đề tài" và "Tự đánh giá" của SCR-49 (FEAT-072 thêm sau — màn để chỗ, không hiện khối rỗng giả).

## Chỗ tài liệu thiếu hoặc lệch — người dùng chọn phương án đề xuất cho Q1–Q4 ngày 09/11/2026

- **Q1 — "Training Result đạt" là gì?** HRMS `Training Result Employee` chỉ có `hours`, `grade` (Data tự do), `comments`; không có trường Đạt/Không đạt.
  - Đề xuất: Custom Field `Training Result Employee.tc_ic_passed` (Check "Đạt", mặc định 1). Đạt = Training Result **đã ghi sổ** + dòng nhân viên có `tc_ic_passed = 1`. → Amendment A-135 (a).
  - Khác: coi mọi dòng trong Training Result đã ghi sổ là đạt (không thêm trường; không ghi được người trượt).
- **Q2 — FR-M11-10 "đào tạo theo quy định" tính thế nào?**
  - Đề xuất: đối tượng = hợp (không trùng) của giám sát viên **chuyên trách** đang hiệu lực (`IC Surveillance Staff` A-132), thành viên **Hội đồng hiệu lực** (`structure.active_committee`), **mạng lưới viên** đang hiệu lực. Một người đạt khi trong **năm báo cáo** có Training Result đạt thuộc chương trình loại đúng nhóm của mình (chuyên trách → "Chuyên trách"; Hội đồng/mạng lưới → "Hội đồng – mạng lưới"; người ở 2 nhóm chỉ cần 1 loại đúng) **hoặc** có `Certificate` loại KSNK còn hiệu lực tại ngày cuối kỳ (UC-42 A1).
  - Loại chứng chỉ KSNK được công nhận (open issue của UC-42): thêm `IC Program Settings.ic_certificate_types` (Small Text, mỗi dòng một loại, R01 nhập) → A-135 (b). Không mã hóa cứng tên chứng chỉ.
  - Khác: chấp nhận mọi loại `tc_ic_category` cho mọi nhóm.
- **Q3 — Sinh viên đào tạo muộn: chặn hay cảnh báo?** FR-M11-11.1 + UC-42 E1 ghi "cảnh báo và đánh dấu Chưa đạt trước thực tập"; ảnh SCR-49 lại có khối đỏ "Không ghi nhận được SV-00233" (kiểu lỗi chặn) trong khi bảng vẫn có dòng SV-00233 "Muộn hơn ngày bắt đầu".
  - Đề xuất: theo SRS — **lưu được**, hiện cảnh báo (msgprint màu cam) và tự đặt trạng thái. Trên SCR-49 khối dưới bảng đổi thành `alert-warning` "N sinh viên đào tạo muộn hơn ngày bắt đầu: …" (không dùng `alert-error` vì không chặn — quy tắc design.md).
  - Khác: chặn lưu khi `trained_on` > `period_from` (khi đó không có trạng thái "Muộn hơn ngày bắt đầu").
  - Kèm: thêm `Trainee Induction.status` (Select chỉ đọc, hệ thống tính: Hợp lệ / Chưa đào tạo / Muộn hơn ngày bắt đầu) → A-135 (c). `result` = Select Đạt / Không đạt (kết quả bài kiểm tra). "Tỷ lệ đạt theo kỳ" = số có `status` Hợp lệ và `result` Đạt / số sinh viên có `period_from` trong kỳ. Không submittable (bản ghi danh sách như `IC Network Member`).
- **Q4 — R02 và màn SCR-49.** UC-42 cho R02 là tác nhân chính (đào tạo, thực tập) nhưng FEAT-056 không cho R02 mở Page `tc-ksnk` (FEAT-057 giữ nguyên).
  - Đề xuất: giữ FEAT-056 — SCR-49 cho R01, R10, R11, R13, System Manager. R02 làm trên Desk: form `Trainee Induction`, HRMS Training, Script Report "Đào tạo KSNK theo khoa" (có cột người chưa học, nút nhắc trong report). Ma trận quyền thêm `TC R01`/`TC R02` vào HRMS `Training Program` (RW), `Training Event` (RWS), `Training Result` (RWS) qua Custom DocPerm — hiện chỉ HR Manager/HR User có quyền.
  - Khác: thêm `TC R02` vào `PAGE_ROLES` của `tc-ksnk` (R02 thấy menu mục SCR-49 duy nhất).

## Quyết định theo tài liệu (không cần hỏi)

- **D1 — Custom Field `Training Program.tc_ic_category`** (architecture §5.3.1 đã có): Select `""` / Basic IC / Full-time IC Staff / Committee and Network / New Staff (nhãn vi: KSNK cơ bản / Chuyên trách / Hội đồng – mạng lưới / Tân tuyển). Training Event thừa hưởng qua `training_program`. Event không có chương trình hoặc chương trình không có loại → không vào tử số; report và SCR-49 hiện cảnh báo "N lớp đào tạo chưa gắn loại KSNK" (UC-42 E2).
- **D2 — FR-M11-09 công thức**: kỳ báo cáo `YYYY-MM` của M9 → cộng dồn từ 01/01 tới ngày cuối tháng đó (năm tới nay). Mẫu số = `Employee` `status = Active`, `department` = khoa, `date_of_joining` ≤ ngày cuối kỳ (FR-M11-09.2: nghỉ việc không tính). Tử số = trong mẫu số, người có Training Result đạt (Q1) của Training Event có `start_time` trong khoảng và chương trình loại KSNK cơ bản. Mẫu số 0 → "Không tính" (BRU-RPT-001, E3). Làm tròn 1 chữ số, dấu phẩy (38/40 → 95,0 %).
- **D3 — Chỉ số qua hook** `tracecore_ic_indicators` → `tracecore.infection_program.training.register`, 3 khóa: `IC_TRAINING_BASIC` (FR-M11-09), `IC_TRAINING_CORE` (FR-M11-10; theo khoa = đối tượng có `Employee.department` là khoa đó), `IC_TRAINEE_INDUCTION` (FR-M11-11). Mỗi hàm `(period, department)` → `(tử, mẫu, cỡ mẫu)`. Dòng danh mục `IC Indicator` do R01 tạo (nội dung chuyên môn, không fixture) như FEAT-058. Mục tiêu và trạng thái "Đạt / Dưới mục tiêu" trên SCR-49 lấy `national_target` của `IC Indicator` có `source_method = IC_TRAINING_BASIC`; chưa có dòng → hiện "Chưa có mục tiêu".
- **D4 — Nhắc người chưa học** (UC-42 A2): sự kiện mới `IC_TRAINING_REMINDER` trong `core.notification.EVENTS` (vai trò mặc định `TC R01`; người nhận = `user_id` của nhân viên chưa học). RPC `tracecore.v1.ksnk_training.remind` (POST, R01/R02/R10) nhận khoa + năm, tính lại danh sách ở server, gọi `core.notification.emit(users=…)`, trả số đã gửi và số người không có tài khoản. Không nhắc tự động theo lịch (tài liệu chỉ nói "có thể gửi nhắc"). → A-135 (d).
- **D5 — Trainee Induction**: module Infection Program, autoname `SV-.YYYY.-.#####`; trường `full_name`, `school`, `department` (Link Department, bắt buộc), `period_from`, `period_to` (≥ `period_from`), `trained_on`, `result`, `status` (Q3). Không có thông tin người bệnh. Audit Log qua `_AUDIT_EVENTS`.
- **D6 — Quyền** (S = ghi sổ):

  | DocType | R01 | R02 | R10 | R11 | R12 | R13 |
  | --- | --- | --- | --- | --- | --- | --- |
  | Trainee Induction | RW | RW | R | R | R (khoa mình) | R |
  | Training Program (HRMS, Q4) | RW | RW | — | — | — | — |
  | Training Event (HRMS, Q4) | RWS | RWS | — | — | — | — |
  | Training Result (HRMS, Q4) | RWS | RWS | — | — | — | — |

  Script Report "Đào tạo KSNK theo khoa": R01, R02, R10, R11, R13.
- **D7 — RPC của SCR-49**: domain `ksnk_training` (không dùng `tracecore.v1.ic.*`). `status` (GET: năm; 3 thẻ KPI, bảng theo khoa, danh sách chưa đạt FR-M11-10, sinh viên thực tập của năm, cảnh báo E2), `remind` (POST, D4). Không có RPC trạm/PDA → không cần `@idempotent`. Lỗi nghiệp vụ `{ok:false, error:{title, reason, action}}` như `ksnk_structure`.

## Acceptance criteria (EARS)

- **AC-1** (FR-M11-09, FR-M11-09.1): Khi khoa có 40 nhân viên Active và 38 người có Training Result đạt của chương trình KSNK cơ bản trong năm, `training.basic_rate` trả 38/40 và màn hiện "95,0 %".
- **AC-2** (FR-M11-09.2, UC-42 E2): Nhân viên `status ≠ Active` không vào mẫu số; Training Result chưa ghi sổ, dòng `tc_ic_passed = 0`, chương trình không có `tc_ic_category` hoặc loại khác KSNK cơ bản, lớp ngoài năm → không vào tử số; số lớp chưa gắn loại hiện thành cảnh báo.
- **AC-3** (BRU-RPT-001, UC-42 E3): Khoa không có nhân viên Active → tỷ lệ "Không tính", không chia cho 0.
- **AC-4** (FR-M11-10, FR-M11-10.1, UC-42 A1, Q2): Mạng lưới viên không có chứng chỉ KSNK còn hiệu lực và không có Training Result đạt đúng loại → vào danh sách chưa đạt; có Certificate loại nằm trong `ic_certificate_types`, còn hạn tại ngày cuối kỳ → đạt cho FR-M11-10 nhưng **không** tính cho FR-M11-09; người vừa là Hội đồng vừa mạng lưới chỉ đếm 1 lần.
- **AC-5** (FR-M11-11, FR-M11-11.1, UC-42 E1, Q3): Lưu `Trainee Induction` có `trained_on` > `period_from` → cảnh báo, `status` = "Muộn hơn ngày bắt đầu"; `trained_on` trống → "Chưa đào tạo"; `trained_on` ≤ `period_from` → "Hợp lệ"; `period_to` < `period_from` bị chặn. Tên `SV-.YYYY.-.#####`.
- **AC-6** (UC-42 A2, D4): R02 gọi nhắc cho khoa → `IC_TRAINING_REMINDER` gửi đúng user của người chưa học trong năm; người đã học không nhận; trả số người không có tài khoản; vai trò không có quyền (R11, R13) bị từ chối.
- **AC-7** (D3, FR-M9-27): `core.indicators.registry()` có 3 khóa của D3; gọi qua engine M9 với kỳ `YYYY-MM` trả đúng tử/mẫu như AC-1, AC-4, AC-5; M9 không import M11.
- **AC-8** (Script Report): "Đào tạo KSNK theo khoa" (`IC Training by Department`, module Infection Program) có bộ lọc năm, khoa; cột khoa, nhân viên, đã đào tạo, tỷ lệ, trạng thái (chữ "Đạt" / "Dưới mục tiêu" / "Không tính"), số chưa học; xuất Excel bằng nút chuẩn; dòng tổng toàn viện.
- **AC-9** (A-131, SCR-49): Registry `SCREENS` có slug `dao-tao`, SCR-49, UC-42, nhóm `program`, vai trò theo Q4; màn gồm tiêu đề + tag "SCR-49 · UC-42" + badge năm; 3 thẻ KPI (nhân viên đào tạo cơ bản, chuyên trách–Hội đồng–mạng lưới, sinh viên chưa đào tạo trước ngày bắt đầu); bảng tỷ lệ theo khoa (trạng thái có chữ, link "Nhắc N người" khi có người chưa học và người dùng có quyền nhắc); danh sách chưa đạt FR-M11-10; bảng sinh viên thực tập (mã Courier New, trạng thái có chữ); khối cảnh báo theo Q3; nút "Mở lịch đào tạo (HRMS)" (`/app/training-event`) và "Xuất báo cáo đào tạo (Excel)" (mở Script Report). Đủ 4 trạng thái (shell FEAT-056). Chỉ token `--tc-*`, chữ qua `__()`.
- **AC-10** (NFR-SEC-09, F-22, D6): Test ma trận quyền khớp D6; `custom_docperm.json` sinh lại bằng `write_fixture`; R12 khoa A không đọc `Trainee Induction` khoa B; test quyền cũ vẫn pass.
- **AC-11**: Audit cho `Trainee Induction`; Custom Field qua fixture; chuỗi qua `_()`/`__()` có trong `vi.csv` (không chứa mã BRU-/FR-/UC- trong chuỗi giao diện); toàn bộ test app pass.

## Tasks (TDD — viết test trước, thấy fail rồi mới code)

0. **Amendment A-135** (Q1–Q4, D4 sau khi người dùng chốt): `docs/architecture.md` Revision History + §5.3.1 (Trainee Induction thêm `status`; HRMS Training thêm Custom Field `Training Result Employee.tc_ic_passed`; IC Program Settings `ic_certificate_types`; sự kiện `IC_TRAINING_REMINDER`). Kiểm số trên `origin/develop` trước khi ghi. Commit `docs(arch): A-135 …` trước code.
1. **Custom Field + Settings**: fixture `Training Program.tc_ic_category`, `Training Result Employee.tc_ic_passed`; `IC Program Settings.ic_certificate_types`. Test fixture có mặt sau migrate.
2. **Engine `infection_program/training.py`** (AC-1..AC-4, AC-7): `basic_rows(year_or_period, department=None)`, `core_staff_rows(...)`, `passed_employees(start, end, category)`, `certified_employees(on_date)`, `register()`. Test `infection_program/tests/test_training.py` (dựng Employee/Training Program/Event/Result trong test; `@bru("BRU-RPT-001")` mẫu số 0; `@bru("BRU-ICP-001")` đối tượng chuyên trách).
3. **Trainee Induction** (AC-5): DocType + controller `validate` tính `status`, cảnh báo. Test `test_trainee_induction.py`.
4. **Nhắc** (AC-6): `EVENTS["IC_TRAINING_REMINDER"]`; `training.remind(department, year)`. Test trong `test_training.py`.
5. **Script Report** `infection_program/report/ic_training_by_department/` (AC-8). Test với `frappe.local.lang = "vi"`.
6. **RPC + màn SCR-49** (AC-9, D7): `v1/ksnk_training.py`; `ui/ksnk.py` thêm màn `dao-tao`; `public/js/ksnk/scr_49_dao_tao.js`; CSS nối cuối `tc_ksnk.css`. Test `v1/tests/test_ksnk_training_api.py`, cập nhật test nav/page.
7. **Quyền, audit, hook, dịch** (AC-10, AC-11): `permission_matrix.csv` thêm DT-ICTRN (+ 3 dòng HRMS nếu Q4 đề xuất) → `write_fixture`; `test_permissions.py`/`test_permissions_v112.py`; hooks `tracecore_ic_indicators`, `_AUDIT_EVENTS`; `scripts/add_name_columns.py`; `vi.csv` nối thêm.
8. **Kiểm tra cuối**: merge `origin/develop` mới (FEAT-058/060) nếu đã có; `bench --site test_f043 migrate`; run-tests module mới, rồi full app chạy nền khi không có lượt `run-tests` khác (đọc `Ran`/`OK`/`FAILED`); `diff-cover --compare-branch=origin/develop --fail-under=70`; `pre-commit run --all-files`; `bench build --app tracecore`. Không E2E. Cập nhật `docs/rtm.md` cột Test FR-M11-09..11. Push `origin feat/FEAT-059-ic-training`; không PR, không merge.
