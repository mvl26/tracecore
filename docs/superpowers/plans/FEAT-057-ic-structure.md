# FEAT-057 Cơ cấu KSNK — Hội đồng, mạng lưới viên, bộ phận giám sát, màn SCR-47 — kế hoạch

> Nguồn: `docs/implementation-plan.md` §3 E-12 (FEAT-057), §6.1 DoD v1.12; `docs/srs.md` FR-M11-01..03 (+ .1–.4), BRU-ICP-001..003, OQ-V12-04; `docs/use-cases.md` UC-40; `docs/architecture.md` §5.3.1 (IC Program Settings, IC Committee, IC Network Member), §5.3.3 (`HDK-.YYYY.-.##`, `ML-.#####`), ADR-009, ADR-015, A-131; `docs/ux-foundations.md` SCR-47; bản giao diện `docs/design-refs/v1.12/SCR-47_CoCau.png`.
> Phụ thuộc: FEAT-056 (đã merge `develop` e03989a). Sprint S6. Cỡ M.
> Nhánh: `feat/FEAT-057-ic-structure` (bench phụ `~/tracecore-f006`, site test `test_f006`).
> Không đụng: Page `station`, `tracecore-theme.css`, Portal, màn M1–M10. File dùng chung chỉ **thêm** dòng (hooks, ma trận quyền, `name_columns`, `vi.csv`, `EVENTS` của `core.notification`).

## Quyết định đã chốt (người dùng trả lời 09/11/2026)

- **D1 — Khoa KSNK và giám sát viên** (tài liệu thiếu chỗ lưu → **Amendment A-132**, ghi vào architecture §5.3.1 + Revision History trước khi code):
  - `IC Program Settings` thêm `ic_department` (Link Department, "Khoa / bộ phận KSNK").
  - Bảng con mới **`IC Surveillance Staff`** (istable, module Infection Program) trong `IC Program Settings.surveillance_staff`: `employee` (Link Employee, bắt buộc), `employee_name` (fetch), `full_time` (Check "Chuyên trách", mặc định 1), `is_active` (Check, mặc định 1). R01 nhập danh sách (UC-40 bước 7).
- **D2 — Khoa phải kiểm mạng lưới** (A-132): Custom Field Department `tc_ic_network_required` (Check, "Bắt buộc mạng lưới KSNK"); R01/R10 đánh dấu khoa lâm sàng, cận lâm sàng. BRU-ICP-003 chỉ kiểm khoa có cờ này, `disabled = 0`, `is_group = 0`.
- **D3 — Gán R12 tự động** (architecture §5.3.1 IC Network Member): mạng lưới viên hiệu lực mà `Employee.user_id` có giá trị → thêm Role `TC R12` + User Permission `Department` = khoa của dòng; khi user không còn dòng hiệu lực nào ở khoa đó → gỡ User Permission khoa đó; không còn dòng hiệu lực nào → gỡ Role `TC R12`. Mỗi lần gán/gỡ ghi Audit Log.
- **D4 — Làm tròn giám sát viên** (OQ-V12-04): giữ giả định SRS — `ceil(bed_count / surveillance_ratio_beds)`, tối thiểu 1. Một hằng duy nhất trong `structure.py`, đổi được khi R01 trả lời.
- **D5 — Quyền** (FR-M11-01.4; S = ghi sổ, A = hủy/sửa đổi):

  | DocType | R01 | R02 | R10 | R11 | R12 | R13 |
  | --- | --- | --- | --- | --- | --- | --- |
  | IC Program Settings (**sửa dòng FEAT-056**: R01 R → RW, vì FR-M11-01.4 "R01 tạo và sửa mọi DocType M11" và R01 nhập giám sát viên/khoa KSNK) | RW | — | RW | R | — | R |
  | IC Committee (submittable) | RWSA | — | R | R | — | R |
  | IC Network Member | RW | RW | R | R | R (khoa mình, User Permission) | R |

  Child `IC Committee Member`, `IC Surveillance Staff` theo quyền cha (không có dòng ma trận). Script Report: R01, R02, R10, R11, R13.
- **D6 — RPC của SCR-47**: domain `ksnk_structure` (không dùng `tracecore.v1.ic.*` — dành cho FEAT-074/D3). `tracecore.v1.ksnk_structure.status` (GET, chỉ đọc), `tracecore.v1.ksnk_structure.save_settings` (POST, R01/R10; đi qua `doc.save()` nên DocPerm quyết định), `tracecore.v1.ksnk_structure.submit_committee` (POST, R01). Hội đồng và mạng lưới viên nhập chi tiết trên Desk form (cột "Blocks" của FEAT-057: "Desk form + validate hook"); màn SCR-47 mở form, không làm form nhập riêng.
- **D7 — Cảnh báo R01 khi vô hiệu mạng lưới viên cuối cùng** (FR-M11-03.2): sự kiện mới `IC_NETWORK_GAP` thêm vào `core.notification.EVENTS` (vai trò mặc định `TC R01`), gọi `core.notification.emit`; kèm `frappe.msgprint` cho người đang sửa và Audit Log.

## Acceptance criteria (EARS)

- **AC-1** (FR-M11-01, FR-M11-01.1, BRU-ICP-001): Khi `bed_count` ≥ 150 (ngưỡng TT 16/2018, hằng số; khác `surveillance_ratio_beds` là tỷ lệ cấu hình) và có nội trú (ví dụ 420), `structure.compute()` trả 4 thành phần bắt buộc: Hội đồng KSNK, Khoa KSNK, Mạng lưới KSNK, Giám sát viên chuyên trách với yêu cầu tối thiểu `ceil(420/150) = 3`; 2 giám sát viên → "Thiếu 1".
- **AC-2** (FR-M11-01.2, BRU-ICP-001, UC-40 A1/A2): Khi < 150 giường có nội trú (120) → bắt buộc Bộ phận KSNK, Mạng lưới, ≥ 1 người chuyên trách; Hội đồng "Không bắt buộc". Khi không có nội trú → chỉ bắt buộc 1 người phụ trách KSNK; thành phần khác "Không áp dụng".
- **AC-3** (FR-M11-01.3, NFR-ACC-01): Mỗi thành phần có `status` mã cố định (`ok` / `missing` / `warning` / `na` / `optional`) và nhãn chữ đã dịch ("Đủ", "Thiếu …", "Không áp dụng", "Không bắt buộc"); thành phần thiếu luôn có chữ "Thiếu".
- **AC-4** (FR-M11-02, FR-M11-02.1, BRU-ICP-002, UC-40 E1): Khi R01 ghi sổ `IC Committee` không có đúng 1 Chủ tịch và 1 Thư ký, hệ thống từ chối và thông báo chỉ rõ vai trò thiếu hoặc thừa (ví dụ "Thiếu Thư ký", "Có 2 Chủ tịch").
- **AC-5** (FR-M11-02.2): Khi thành phần thiếu đại diện Vi sinh–Xét nghiệm, Dược hoặc Lâm sàng nguy cơ cao, ghi sổ vẫn thành công, hiện cảnh báo liệt kê khối thiếu và ghi một Audit Log (`action` Update, `reason` nêu khối thiếu).
- **AC-6** (UC-40 A3): `IC Committee` có `valid_from` bắt buộc, `valid_to` ≥ `valid_from`; Hội đồng hiệu lực = bản đã ghi sổ có hiệu lực tại hôm nay, mới nhất theo `valid_from`; bản cũ giữ nguyên. Tên `HDK-.YYYY.-.##`. Một nhân viên không lặp trong thành phần.
- **AC-7** (FR-M11-03, FR-M11-03.1, BRU-ICP-003): Khi danh sách mạng lưới thay đổi, mỗi khoa có `tc_ic_network_required` thiếu bác sĩ hoặc thiếu ĐD/HS/KTV đang hiệu lực vào danh sách thiếu với lý do bằng chữ ("Thiếu bác sĩ", "Thiếu ĐD/HS/KTV"); khoa chỉ có điều dưỡng → "Thiếu bác sĩ".
- **AC-8** (FR-M11-03.2, UC-40 E2): Khi vô hiệu (hoặc đổi khoa) mạng lưới viên cuối cùng của một nhóm ở một khoa bắt buộc, hệ thống cảnh báo R01 (`IC_NETWORK_GAP`), hiện msgprint và ghi Audit Log; khoa vào danh sách thiếu.
- **AC-9** (architecture §5.3.1, D3, UC-40 E3): Mạng lưới viên hiệu lực có user → user có Role `TC R12` và User Permission Department khoa đó; R12 khoa A đọc `IC Network Member` khoa A, không đọc được khoa B; vô hiệu dòng cuối → gỡ quyền.
- **AC-10** (Script Report): "Cơ cấu KSNK còn thiếu" (`IC Structure Gaps`, module Infection Program) mỗi dòng là một mục thiếu (thành phần hoặc khoa), cột `issue` có chữ "Thiếu" (kiểm với `lang = vi`), cột `issue_code` cố định; cơ cấu đủ → 0 dòng.
- **AC-11** (A-131, SCR-47): Registry `SCREENS` có slug `co-cau`, SCR-47, UC-40, nhóm `program`, vai trò R01, R02, R10, R11, R13, System Manager; badge = số thành phần thiếu qua hook `tracecore_ksnk_badges`. Màn gồm: tiêu đề + tag "SCR-47 · UC-40" + badge "Thiếu N thành phần"; khối Cài đặt chương trình (R10/R01 sửa, vai trò khác chỉ đọc); bảng trạng thái cơ cấu; khối Hội đồng hiệu lực (thành viên, cảnh báo thiếu đại diện); bảng mạng lưới theo khoa; nút "Ghi sổ thành phần Hội đồng" (chỉ R01, khi có bản Nháp) và "Xuất danh sách mạng lưới (Excel)" (report view Desk); lỗi chặn hiện `alert-error` inline. Đủ 4 trạng thái (shell FEAT-056). Chỉ token `--tc-*`, chữ qua `__()`.
- **AC-12** (NFR-SEC-09, F-22, D5): Test ma trận quyền khớp D5 cho 3 dòng (sửa DT-ICSET, thêm DT-ICCOM, DT-ICNET); `custom_docperm.json` sinh lại bằng `write_fixture`; test cũ R01–R10 vẫn pass.
- **AC-13**: Audit (`_AUDIT_EVENTS`) cho `IC Committee` (kèm `on_update_after_submit`) và `IC Network Member`; `name_columns` có cột tên `employee_name` ở form/list; chuỗi qua `_()`/`__()` có trong `translations/vi.csv`; toàn bộ test app pass trên site test.

## Tasks (TDD — viết test trước, thấy fail rồi mới code)

0. **Amendment A-132** (D1, D2). `docs/architecture.md`: Revision History + §5.3.1 (dòng IC Program Settings thêm `ic_department`, `surveillance_staff`; dòng mới `IC Surveillance Staff`; Custom Field Department `tc_ic_network_required`). `docs/rtm.md` cột Test của FR-M11-01..03 khi xong. Commit `docs(arch): A-132 …` trước code.
1. **Engine cơ cấu** (AC-1..AC-3, D4). `tracecore/infection_program/structure.py`: `required_surveillance(bed_count, ratio)`, `compute()` → `{bed_count, components:[{key, label, requirement, current, status, status_label, missing_count}], departments:[…], committee, missing_total}`; `check(doc, method)` là validate hook (`infection_program.structure.check`) đăng ký cho `IC Committee` và `IC Network Member`. Test `infection_program/tests/test_structure.py`: `@bru("BRU-ICP-001")` 420/120/không nội trú, 150 → 1, 151 → 2.
2. **IC Program Settings mở rộng** (D1). Thêm `ic_department`, `surveillance_staff` (child `IC Surveillance Staff`); kiểm nhân viên không trùng. Test bổ sung vào `test_ic_program_settings.py`.
3. **IC Committee + IC Committee Member** (AC-4..AC-6). DocType submittable, autoname `HDK-.YYYY.-.##`, `decision_no`, `decision_date`, `decision_file` (Attach), `valid_from`, `valid_to`, `members`. `before_submit`: đếm Chủ tịch/Thư ký (BRU-ICP-002); `on_submit`: cảnh báo thiếu khối + Audit Log. Test `@bru("BRU-ICP-002")`.
4. **IC Network Member** (AC-7..AC-9, D3, D7). DocType autoname `ML-.#####`, `employee`, `employee_name`, `department`, `member_type` (Doctor / Nurse / Midwife / Technician), `appointed_on`, `decision_no`, `is_active`. `on_update`: so trạng thái trước/sau → cảnh báo nhóm cuối; đồng bộ Role R12/User Permission. Sự kiện `IC_NETWORK_GAP` trong `EVENTS`. Custom Field `Department.tc_ic_network_required` (fixture). Test `@bru("BRU-ICP-003")`, R12 khoa A/B.
5. **Script Report "Cơ cấu KSNK còn thiếu"** (AC-10). `infection_program/report/ic_structure_gaps/`. Test với `frappe.local.lang = "vi"`.
6. **RPC + màn SCR-47** (AC-11, D6). `v1/ksnk_structure.py`; `ui/ksnk.py` thêm màn `co-cau`; badge qua hook `tracecore_ksnk_badges` → `infection_program.structure.badges`; `public/js/ksnk/scr_47_co_cau.js`; CSS thêm vào `public/css/ksnk.css` chỉ token. Test `v1/tests/test_ksnk_structure_api.py`, `ui/tests/test_ksnk_nav.py` (mục mới theo vai trò), test JS theo mẫu `tests/test_ksnk_page.py`.
7. **Quyền, audit, tên, dịch** (AC-12, AC-13). `permission_matrix.csv` (sửa DT-ICSET, thêm DT-ICCOM, DT-ICNET) → `write_fixture`; `test_permissions.py` 57 → 59 dòng; `test_permissions_v112.py` thêm dòng; hooks `_AUDIT_EVENTS` + `doc_events` validate; `core/name_columns.py` không cần thêm đích mới (Employee, Department đã có) — chạy `scripts/add_name_columns.py` cho DocType mới; `translations/vi.csv` nối thêm.
8. **Kiểm tra cuối**. `bench --site test_f006 migrate`; `run-tests` module mới, rồi full app chạy nền (đọc `Ran`/`OK`/`FAILED`, không tin exit code); `diff-cover coverage.xml --compare-branch=origin/develop --fail-under=70`; `pre-commit run --all-files`; `bench build --app tracecore` (nvm). Không E2E. Push `origin feat/FEAT-057-ic-structure`; không PR, không merge.

## Ngoài phạm vi

- Biên bản họp Hội đồng, kế hoạch năm, văn bản (FEAT-058); đào tạo mạng lưới (FEAT-059); Cổng khoa cho R12 (A-131 e); xác minh "Chủ tịch là Giám đốc" theo chức danh HRMS (BRU-ICP-002 chỉ kiểm số lượng vai trò — không có dữ liệu chức danh chuẩn).
