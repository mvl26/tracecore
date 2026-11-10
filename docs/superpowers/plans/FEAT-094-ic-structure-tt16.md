# FEAT-094 Cơ cấu KSNK kiểm đủ điều kiện TT 16/2018 (M11, SCR-47) — kế hoạch

> Nguồn: `docs/implementation-plan.md` §3 E-12 (FEAT-094, AC-094-01..14); `docs/srs.md` FR-M11-01 (.1, .2, .5..01.8), FR-M11-02 (.1..02.4), FR-M11-03 (.3), BRU-ICP-001..003, 006, 007, OQ-V12-04, OQ-V12-11..16 (người dùng chốt 10/11/2026); `docs/architecture.md` Revision History A-138, §5.3; `docs/use-cases.md` UC-40 (bước 1, 7; A1, A4, A5, E1a); `docs/ux-foundations.md` SCR-47 (A-138); văn bản TT 16/2018/TT-BYT Điều 16–22.
> Phụ thuộc: FEAT-057 (cơ cấu, SCR-47), FEAT-059 (`training.certified_employees`, `training.passed_employees`), A-135 (`ic_certificate_types`). Sprint S7. Cỡ M.
> Nhánh: `feat/FEAT-094-ic-structure-tt16` cắt từ `develop` 395971c + merge `docs/amendment-A-138-tt16-structure` (bench phụ `~/tracecore-f026`, site test `test_f026`).
> Song song FEAT-062/066: file dùng chung (`hooks.py`, `setup/install.py`, `patches.txt`, `translations/vi.csv`, `fixtures/*`, `tests/test_permissions*.py`) chỉ **nối thêm** khối có comment `FEAT-094`.

## Đã chốt với người dùng (10/11/2026) — Amendment A-143

- **Q1 — Ngưỡng quy mô tách khỏi ngưỡng Hội đồng.** `IC Structure Profile` thêm `department_min_beds` (Int, mặc định 150): cơ sở có nội trú và số giường ≥ ngưỡng là "Large" (khoa KSNK, trưởng khoa, điều dưỡng trưởng, giám sát viên = giường ÷ tỷ lệ), dưới ngưỡng là "Small" (bộ phận KSNK, người phụ trách, ≥ 1 giám sát viên). `committee_min_beds` chỉ quyết định Hội đồng có bắt buộc không (0 = mọi cơ sở có nội trú; không nội trú luôn "Không áp dụng").
- **Q2 — Bậc học / khối ngành sức khỏe chỉ R02, R10 sửa** (theo DT-EMP hiện có: R01 chỉ đọc Employee). R01 xem lý do trên SCR-47 và báo nhân sự. Không đổi ma trận quyền Employee.

## Quyết định thiết kế (mặc định)

- **D1 — DocType mới** `IC Structure Profile` (module Infection Program, không submittable, naming `BTC-.YYYY.-.##`, track changes) theo architecture §5.3 + `department_min_beds` (A-143). Child `IC Structure Committee Requirement`, `IC Structure Role Requirement`. Mọi chuỗi Select bằng tiếng Anh (dịch trong `vi.csv`).
- **D2 — Vòng đời.** `before_insert`: `version_no` = max + 1, `status` = Draft, xóa `approved_by/on`. `validate`: bản không phải Draft không sửa được (trừ đổi trạng thái do hệ thống, cờ `tc_status_change`). Duyệt qua method `approve` của Document (`frm.call`, không thêm RPC `tracecore.v1`): chỉ `TC R01`/System Manager/Administrator, chỉ từ Draft; bản Approved khác có `effective_from` ≤ `effective_from` của bản mới (khi bản mới đã có hiệu lực) → Superseded; ghi `approved_by` (Employee của user nếu có), `approved_on`; Audit Log cho mỗi đổi trạng thái. `active_profile(on)` = Approved có `effective_from` ≤ `on` mới nhất (hòa → `version_no` lớn).
- **D3 — Fixture Nháp (NFR-MAINT-04).** `infection_program/structure_seed.py::ensure_seed` ở `after_install` và `after_migrate`: chỉ chèn bản "TT 16/2018" khi **chưa có bản `IC Structure Profile` nào** (bản bệnh viện đã sửa/duyệt/xóa-rồi-tạo-lại đều không bị đè). Không dùng `fixtures` của Frappe. Nội dung bộ khởi tạo:
  - `committee_min_beds` 150, `department_min_beds` 150, `committee_rule_severity` Warn, `network_rule` Doctor and Nurse, `allow_one_person_both_roles` 0, `legal_basis` "TT 16/2018/TT-BYT Điều 16–22", `effective_from` 2018-08-15 (ngày hiệu lực của thông tư).
  - Khối Hội đồng: Functional Unit, Microbiology and Laboratory, Pharmacy, High-risk Clinical (Representing, min 1).
  - Vai trò: Head (Large) Bachelor + health + full-time + evidence; Head Nurse (Large) như trên; Surveillance Officer (Large) và (Small) College + health + full-time (chuyên trách) + evidence; Person in Charge (Small) full-time + health + evidence, không bậc học; Person in Charge (Outpatient) không yêu cầu.
- **D4 — Thành phần lấy từ profile.** Khi có profile Approved: thành phần người = các dòng `IC Structure Role Requirement` có `applies_to` = quy mô hoặc Any, theo thứ tự cố định Head → Head Nurse → Person in Charge → Surveillance Officer (khóa `head`, `head_nurse`, `person_in_charge`, `surveillance`). Số yêu cầu: Surveillance Officer ở Large = `required_surveillance(giường, tỷ lệ, rounding)`, còn lại 1. Khi **chưa có profile Approved** (OQ-V12-16): chỉ đếm như FEAT-057 (Hội đồng có/không và đúng 1 Chủ tịch + 1 Thư ký, khoa/bộ phận, mạng lưới Doctor and Nurse, số người chuyên trách đang hiệu lực), ngưỡng lấy từ giá trị mặc định của trường trong DocType (không hằng số trong code), không cảnh báo khối Hội đồng; trả `profile = None` và `profile_notice` "Chưa duyệt bộ tiêu chí cơ cấu".
- **D5 — `qualification.check(person, requirement, settings)`** trả `{status: ok|fail|unverified, reasons[]}`:
  - `full_time_required` và dòng nhân sự không chuyên trách → fail "Chưa đạt: không toàn thời gian".
  - Yêu cầu bậc học hoặc khối ngành mà `tc_education_level` trống → unverified "Chưa xác minh: chưa có bậc học" (OQ-V12-12). Bậc dưới `min_education` → fail "Chưa đạt: bậc học dưới {bậc}". `health_field_required` và `tc_health_field` = 0 (đã có bậc học) → fail "Chưa đạt: không thuộc khối ngành sức khỏe".
  - `evidence_required`: đạt khi có `Certificate` loại được công nhận còn hiệu lực hôm nay (`certificate_types` của dòng, trống thì `ic_certificate_types`) hoặc Training Result đạt của lớp `Full-time IC Staff` (mọi thời điểm ≤ hôm nay). Có Certificate loại được công nhận nhưng hết hạn/không hiệu lực → fail "Chưa đạt: chứng chỉ KSNK hết hiệu lực". Không có bản ghi nào → unverified "Chưa xác minh: chưa có chứng chỉ KSNK".
  - fail thắng unverified; lý do liệt kê đủ.
  - Gọi `training` bằng import trễ (training đã import structure).
- **D6 — Trạng thái thành phần người.** `ok_count` = người đạt (sau loại trùng D7). Thiếu = yêu cầu − ok_count. Thiếu ≤ 0 → ok "Đủ"; thiếu ≤ số người chưa xác minh → `unverified` "Chưa xác minh" (không tính `missing_total`, AC-094-09); còn lại → missing "Thiếu n" (`missing_count` n). Mỗi thành phần có `people[]` (`employee`, `employee_name`, `status`, `status_label`, `reasons`) và `reasons` (chuỗi gộp cho cột Lý do). Cột Yêu cầu của giám sát viên ghi cách làm tròn ("làm tròn lên"/"làm tròn xuống", FR-M11-01.7).
- **D7 — Một người nhiều vai.** `allow_one_person_both_roles` = 0: một nhân viên đã được tính đạt ở một thành phần thì ở thành phần sau (theo thứ tự D4) không được đếm, lý do "Đã được tính cho vai {vai}" (AC-094-06). Áp cho mọi cặp vai, không chỉ < 150 giường.
- **D8 — `IC Program Settings`**: thêm `director` (Link Employee) + `director_name` (fetch, read only), `surveillance_rounding` (Select Up/Down, mặc định Up). `required_surveillance(beds, ratio, rounding="Up")`: Down = floor, tối thiểu 1. `IC Surveillance Staff`: thêm `ic_role` (Head / Head Nurse / Person in Charge / Surveillance Officer, mặc định Surveillance Officer, reqd, in list view); kiểm trùng theo (`employee`, `ic_role`). Patch `a138_ic_staff_role` đặt dòng cũ trống → Surveillance Officer.
- **D9 — Hội đồng (BRU-ICP-002).** Giữ chặn "đúng 1 Chủ tịch + 1 Thư ký" mọi lúc (AC-094-12). Khi có profile Approved: `committee_rule_problems(doc)` trả danh sách khối/vai trò thiếu (Representing và Role với `min_count`), Chủ tịch ≠ `director` (bỏ qua và nhắc khai khi trống), Thư ký không phải người đang hiệu lực có `ic_role` Head hoặc Person in Charge trong nhân sự KSNK. `committee_rule_severity` Block → throw ở validate khi ghi sổ; Warn → msgprint + Audit Log `IC_COMMITTEE_RULE_WARNING` ở `on_submit` (thay `warn_missing_representatives`). `missing_representatives(committee)` giữ tên (dùng ở compute / report), đọc profile.
- **D10 — Mạng lưới.** `network_rule` = Any One Member → khoa đủ khi có ≥ 1 mạng lưới viên hiệu lực (FR-M11-03.3); `department_rows` trả `missing = ["member"]` và nhãn "Thiếu mạng lưới viên". `network.py` (cảnh báo người cuối) giữ nguyên.
- **D11 — `IC Committee Member.representing`** thêm cuối danh sách: Nursing, Quality Management, Planning and General, Infrastructure, Medical Equipment.
- **D12 — Custom Field Employee** `tc_education_level` (Select trống/Vocational/College/Bachelor/Postgraduate) và `tc_health_field` (Check), chèn sau `tc_vaccination_remind_level`, nối vào `fixtures/custom_field.json`. Không đổi permlevel.
- **D13 — RPC** `tracecore.v1.ksnk_structure`: `status` thêm khóa `profile`, `profile_notice`, `can_open_profile`, `settings.director`, `settings.director_name`, `settings.surveillance_rounding`; `save_settings` nhận thêm `director`, `surveillance_rounding`. Không bỏ khóa cũ.
- **D14 — SCR-47.** Bảng thành phần thêm cột **Lý do**; badge `unverified` (`is-warn`, chữ "Chưa xác minh"); khối thông báo "Chưa duyệt bộ tiêu chí cơ cấu" + link `/app/ic-structure-profile` (R01); cài đặt thêm ô mã người đứng đầu (input + tên) và chọn làm tròn. Chỉ token `--tc-*` qua class sẵn có. Form Desk `IC Structure Profile` có nút "Approve" (R01, Nháp) và chỉ đọc khi không phải Nháp.
- **D15 — Script Report "Cơ cấu KSNK còn thiếu"**: thêm cột `reason`; mỗi người không đạt / chưa xác minh của thành phần người là một dòng (`issue_code` `PERSON_FAIL` / `PERSON_UNVERIFIED`); khối Hội đồng lấy từ `committee.problems`.
- **D16 — Quyền.** `DT-ICSP,IC Structure Profile`: R01 RW, R02 R, R10 R, R13 R (ma trận 74 → 75). Child không có dòng. Sinh lại `custom_docperm` bằng `write_fixture`.

## Truy vết AC → task

| AC | Task |
| :- | :- |
| AC-094-01, 02 | T2, T3 |
| AC-094-03 | T5, T8 |
| AC-094-04 | T4, T5 |
| AC-094-05, 06 | T5 |
| AC-094-07, 08, 09 | T4, T5 |
| AC-094-10, 11, 12 | T6 |
| AC-094-13 | T5, T6 |
| AC-094-14 | T5, T7, T8 |

## Tasks (TDD: test `FrappeTestCase` trước, thấy fail, rồi code)

- **T1 — Dữ liệu (FR-M11-01.5..01.8; A-138 a–f, A-143).** DocType + 2 child, field mới IC Program Settings / IC Surveillance Staff / IC Committee Member, Custom Field Employee, patch `ic_role`, dòng ma trận + `custom_docperm`. Test: `test_permissions`, `test_permissions_v112` (DT-ICSP, 75), `test_name_columns`.
- **T2 — Vòng đời profile (FR-M11-01.8; AC-094-01).** `infection_program/structure_profile.py` (`before_insert`, `validate`, `approve`, `active_profile`). Test `doctype/ic_structure_profile/test_ic_structure_profile.py` `@bru("BRU-ICP-001")`.
- **T3 — Fixture Nháp (NFR-MAINT-04; AC-094-02).** `structure_seed.ensure_seed` + hook `after_migrate`/`after_install`. Test: chạy 2 lần không trùng; bản đã sửa/duyệt giữ nguyên.
- **T4 — `qualification.py` (BRU-ICP-006; AC-094-07..09).** Test `tests/test_qualification.py` `@bru("BRU-ICP-006")`.
- **T5 — `structure.compute` (BRU-ICP-001, 003, 006, 007; AC-094-03..09, 13, 14).** Bỏ `REQUIRED_REPRESENTING`, `COMMITTEE_MIN_BEDS`; profile-driven; rounding; tách vai; `people[]`; `unverified`. Test `tests/test_structure.py` thêm lớp `TestStructureProfile` `@bru("BRU-ICP-001", "BRU-ICP-007")`; giữ test FEAT-057 (chế độ chưa duyệt).
- **T6 — Hội đồng (BRU-ICP-002; AC-094-10..13).** `structure.committee_rule_problems`, Block/Warn. Test `test_ic_committee.py` `@bru("BRU-ICP-002")`.
- **T7 — Report + RPC (FR-M11-01.3, 01.7; AC-094-14).** Test `test_structure.py` (report), `v1/tests/test_ksnk_structure_api.py`.
- **T8 — SCR-47 + form profile + `vi.csv` (NFR-ACC-01; AC-094-03, 14).** Test `tests/test_ksnk_scr47.py` (js harness), kiểm bản dịch "Chưa xác minh", "Thiếu".
- **T9 — Tài liệu A-143.** Revision History architecture/srs, §5.3 `department_min_beds`, FR-M11-01.8 ghi chú, quyền Employee R02/R10; rtm thêm file test.

## Kiểm tra

Chạy lần lượt (`--module`): `tracecore.infection_program.tests.test_structure`, `…tests.test_qualification`, `…doctype.ic_structure_profile.test_ic_structure_profile`, `…doctype.ic_committee.test_ic_committee`, `…doctype.ic_program_settings.test_ic_program_settings`, `…doctype.ic_network_member.test_ic_network_member`, `…tests.test_training`, `tracecore.v1.tests.test_ksnk_structure_api`, `tracecore.tests.test_ksnk_scr47`, `tracecore.tests.test_permissions`, `…test_permissions_v112`, `…test_name_columns`. Không full suite, không E2E. `diff-cover … --fail-under=70`, `pre-commit run --all-files`.
