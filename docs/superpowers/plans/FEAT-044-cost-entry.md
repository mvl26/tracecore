# FEAT-044 Nhập chi phí và gắn đối tượng phân bổ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** R09 nhập khoản chi phí (khoản mục, số tiền, kỳ, chứng từ, nguồn hóa đơn/định mức/đồng hồ) và gắn đối tượng phân bổ (thiết bị, khu, chương trình) theo tỷ lệ tổng 100 %; xem báo cáo chi phí theo thiết bị/kỳ. Chi phí bảo trì/sửa chữa từ `Maintenance Record` (FEAT-039) tự sinh `Cost Entry` Nháp để R09 xác nhận.

**Architecture:** Module `Costing` (M7), package `tracecore/costing/`. DocType `Cost Entry` (DT-COSTENTRY, submittable) + child `Cost Allocation`; master `Cost Category` (12 khoản mục cố định, R09 mở rộng, FR-M7-01.1); Single `Cost Settings` giữ ngày khóa kỳ (UC-27 E3). Dịch vụ `tracecore/costing/entry.py` (kiểm dữ liệu, phân bổ theo ngày, tạo từ nguồn khác) và `tracecore/costing/reports.py`. M7 không import M5: nhận chi phí bảo trì qua hook `tracecore_after_maintenance_submit` (do `equipment.maintenance.on_submit` gọi bằng `core.extension.run`). Báo cáo là Script Report `Cost by Target`. Màn SCR-27 là form Desk + Client Script.

**Tech Stack:** Frappe v15, `FrappeTestCase` / `IsolatedTestCase`, Desk Client Script, Script Report.

**Spec:** `docs/srs.md` FR-M7-01 (.1–.4), FR-M7-02 (.1–.3), FR-M5-04.3 (phía M7); `docs/use-cases.md` UC-27 (bước 1–5, A1, E1–E3); `docs/architecture.md` §5.3 (DT-COSTENTRY), §5.3.3; `docs/ux-foundations.md` SCR-27; `docs/rtm.md` (TC-27-01, TC-27-02). Không có BRU gắn FR-M7-01/02 (BRU-CST-001..003 thuộc FEAT-045/046). Amendment **A-47** (cần tạo; A-46 thuộc FEAT-042).

## Global Constraints
- `Cost Entry` đi Nháp → Ghi sổ → Hủy, không xóa (`is_submittable=1`, `on_trash` → `core.audit.block_delete`).
- M7 không import M1–M10 khác; chỉ đi qua `core`, Link hoặc hook. Đối tượng phân bổ là Dynamic Link (Equipment, Zone Station, Process Program).
- Chuỗi hiển thị qua `_()`/`__()` + `translations/vi.csv` (thuật ngữ QĐ 3671); ngày `dd/mm/yyyy`, VND không lẻ, `Asia/Ho_Chi_Minh`.
- Desk chỉ Client Script, token `--tc-*`; lỗi chặn là `frappe.throw`/`alert-error` inline, không modal/toast cho lỗi chặn.
- Không làm: bảng định giá và đơn giá phiên bản (FEAT-045), Cost Sheet và khấu hao theo mẻ (FEAT-046), thuê ngoài chất thải (FEAT-049), nhân công từ ca (UC-27 A2), khấu hao tự sinh hằng tháng (UC-27 bước 6), `Journal Entry`.
- Không chạy E2E, không tạo PR (CLAUDE.md).

## Quyết định (Amendment A-47, người dùng duyệt 29/10/2026 — chủ đầu tư chưa xác nhận)
| # | Trạng thái | Quyết định |
| :- | :- | :- |
| C1 | [Đã duyệt 29/10/2026] | **Naming series** `CP-.YYYY.-.#####` cho `Cost Entry` (dòng "Chứng từ khác" §5.3.3). |
| C2 | [Đã duyệt 29/10/2026] | **Submittable**: Nháp → Ghi sổ → Hủy (UC-27 bước 5 "Ghi sổ"; CLAUDE.md). UC ghi "không có trạng thái" nhưng quy tắc chứng từ chung thắng. Ghi sổ yêu cầu ≥ 1 dòng phân bổ tổng 100 %. |
| C3 | [Đã duyệt 29/10/2026] | **Khoản mục**: DocType mới `Cost Category` (tên, `is_system`, `is_active`), 12 loại cố định tạo khi cài/migrate (khấu hao, bảo trì, sửa chữa, phụ tùng, điện, nước máy, nước RO, hơi, khí nén, nhân công, đồ bảo hộ, thuê ngoài), R09 thêm loại mới; không loại nào bị xóa, chỉ tắt `is_active`, và loại hệ thống không đổi tên (FR-M7-01.1; tên gốc xem A-47 trong architecture). Cần vì `Select` cố định không mở rộng được. |
| C4 | [Đã duyệt 29/10/2026] | **Nguồn** `source`: `Invoice` / `Norm` / `Meter`. `Meter` nhận `opening_reading`, `closing_reading`, `unit`; `quantity = closing − opening`, chỉ số hoặc hiệu âm → chặn (FR-M7-01.3, .4). Số tiền vẫn nhập tay (đơn giá phiên bản là FEAT-045). |
| C5 | [Đã duyệt 29/10/2026] | **Kỳ**: `period_from` ≤ `period_to`. Khoản theo tháng phân bổ theo ngày trong kỳ: `amount / số ngày` (FR-M7-01.2); hàm `amount_in(entry, from, to)` cho báo cáo và FEAT-046, làm tròn VND, ngày cuối nhận phần dư để tổng khớp. |
| C6 | [Đã duyệt 29/10/2026] | **Khóa kỳ (E3)**: Single `Cost Settings.locked_until` (Date). Tạo/sửa/ghi sổ/hủy `Cost Entry` có `period_from` ≤ `locked_until` → chặn, "cần mở kỳ". Chỉ R01 sửa `locked_until`. Repo chưa có khái niệm khóa kỳ; không dùng `Accounting Period` của ERPNext vì ràng buộc theo Company/chứng từ kế toán. |
| C7 | [Đã duyệt 29/10/2026] | **Phân bổ** child `Cost Allocation`: `target_type` (Equipment / Zone Station / Process Program), `target` (Dynamic Link), `percent` (> 0, ≤ 100). Tổng ≠ 100 khi có dòng → chặn lưu (FR-M7-02.1); trùng đối tượng → chặn. Nháp rỗng được lưu, Ghi sổ thì phải có dòng. |
| C8 | [Đã duyệt 29/10/2026] | **Liên kết kế toán**: `cost_center` (Link Cost Center, tùy chọn), `document_no` và `document_date` (chứng từ). `Journal Entry` không làm. |
| C9 | [Đã duyệt 29/10/2026] | **Từ bảo trì (FR-M5-04.3, UC-27 A1)**: ghi sổ `Maintenance Record` có `cost > 0` loại Preventive / Incident / Calibration / Inspection → `Cost Entry` **Nháp** (khoản mục Bảo trì hoặc Sửa chữa; số tiền = `cost` của hồ sơ, chi tiết phụ tùng ghi vào mô tả), phân bổ 100 % cho máy đó, `source = Invoice`, trỏ ngược `source_doctype/source_name`. R09 xác nhận số tiền rồi ghi sổ; hồ sơ nguồn đã Hủy thì không ghi sổ được. Idempotent theo `source_name`. Hủy hồ sơ nguồn không xóa Cost Entry (cấm xóa). |
| C10 | [Đã duyệt 29/10/2026] | **Hoãn**: khấu hao tự sinh hằng tháng (UC-27 bước 6) và nhân công từ ca (A2). Khấu hao đã nằm ở `Equipment.depreciation_per_load` và FEAT-046 tính theo mẻ; tạo thêm Cost Entry hằng tháng sẽ tính trùng. Cần chủ đầu tư xác nhận cách tính trước khi làm. |
| C11 | [Đã duyệt 29/10/2026] | **Báo cáo** Script Report `Cost by Target` (FR-M7-02.3, UC-27 bước 5): lọc kỳ, đối tượng, khoản mục; mỗi khoản đã ghi sổ chia theo ngày giao kỳ lọc × tỷ lệ phân bổ; có tổng; xuất Excel là tính năng chuẩn của Frappe. |
| C12 | [Đã duyệt 29/10/2026] | **Quyền**: giữ ma trận đã có DT-COSTENTRY (R09 RWS, R01 đọc + hủy, R02/R10 đọc); thêm DT-COSTCAT (R09 RW, R01/R02/R10 đọc) và DT-COSTSET (R01 RW, R09 đọc). Cập nhật ghi chú "future FEAT-045" thành FEAT-044. |

## Review Focus
- Tổng tỷ lệ ≠ 100 hoặc số âm/chỉ số đồng hồ ngược → không lưu được; kỳ đã khóa → không tạo/sửa/ghi sổ/hủy được.
- `amount_in` chia theo ngày cộng lại đúng bằng số tiền (không mất đồng lẻ); báo cáo khớp tổng.
- Cost Entry từ bảo trì không bị tạo trùng khi ghi sổ lại/hủy–sửa; M7 không import `equipment`.
- Không xóa được Cost Entry; loại hệ thống của Cost Category không xóa/đổi tên được.

## Tasks

### Task 0: Amendment A-47 và tài liệu
**Đáp ứng:** quy trình CLAUDE.md (DocType mới `Cost Category`, `Cost Settings`, naming `CP-` phải qua amendment).
**Files:** Modify `docs/architecture.md` (Revision History A-47, ghi chú, §5.3 dòng DT-COSTENTRY + `Cost Category`/`Cost Settings`, §5.3.3 naming `CP-`), `tracecore/fixtures/permission_matrix.csv`.
- [x] Ghi C1–C12 với trạng thái đã chốt sau khi người dùng duyệt.
- [x] Commit `docs(architecture): A-47 nhập chi phí và phân bổ (FEAT-044)`.

### Task 1: DocType `Cost Category` + `Cost Settings`
**Đáp ứng:** FR-M7-01.1; UC-27 E3; C3, C6, C12.
**Files:** Create `tracecore/costing/doctype/cost_category/…`, `tracecore/costing/doctype/cost_settings/…`, `tracecore/costing/setup.py` (`ensure_categories`, gọi từ `after_install` và patch cho site đã cài); Modify `tracecore/hooks.py`, `tracecore/patches.txt`, `tracecore/fixtures/custom_docperm.json` (qua `write_fixture`), `tracecore/translations/vi.csv`.
- [x] Test trước: 12 khoản mục hệ thống tồn tại; `ensure_categories` chạy hai lần không nhân đôi; xóa/đổi tên loại hệ thống → chặn; R09 thêm loại mới được; chỉ R01 sửa `locked_until`.
- [x] Viết JSON, controller, `ensure_categories`; `bench --site <SITE> migrate`; test pass.

### Task 2: DocType `Cost Entry` + `Cost Allocation`
**Đáp ứng:** FR-M7-01, .2, .3, .4; FR-M7-02, .1; UC-27 bước 1–4, E1, E2; C1, C2, C4, C5, C7, C8.
**Files:** Create `tracecore/costing/doctype/cost_entry/{__init__,cost_entry.json,cost_entry.py,cost_entry.js,cost_entry_list.js,test_cost_entry.py}`, `tracecore/costing/doctype/cost_allocation/…`; Modify `tracecore/hooks.py` (`on_trash` → `block_delete`, audit events), `tracecore/tests/factories.py` (`make_cost_entry`), `tracecore/translations/vi.csv`.
**Trường chính:** `category` (Link Cost Category, bắt buộc), `amount` (Currency ≥ 0), `period_from`, `period_to`, `source` (Select), `opening_reading`, `closing_reading`, `unit`, `quantity` (read-only), `document_no`, `document_date`, `cost_center`, `description`, `source_doctype`/`source_name` (ẩn, read-only), `allocations` (Table `Cost Allocation`), `amended_from`.
- [x] Test trước: số tiền âm, chỉ số âm hoặc đóng < mở → chặn; `period_to` < `period_from` → chặn; tổng tỷ lệ ≠ 100 (99, 101, 33+33+33) → chặn lưu; đúng 100 (kể cả 33,33,34) → lưu; đối tượng trùng → chặn; Ghi sổ không dòng phân bổ → chặn; `quantity` tính đúng từ đồng hồ; xóa → chặn; R03 không đọc được.
- [x] Viết JSON + controller `validate`, `before_submit`; migrate; test pass.

### Task 3: Dịch vụ `costing/entry.py` — phân bổ theo ngày và khóa kỳ
**Đáp ứng:** FR-M7-01.2, FR-M7-02.2 (nền); UC-27 E3; C5, C6.
**Interfaces:** `amount_in(entry, date_from, date_to) -> int`, `allocated_to(entry, target_type, target, date_from, date_to) -> int`, `check_period_open(period_from) -> None`.
- [x] Test trước: khoản 3.100.000 đ kỳ 31 ngày, giao kỳ lọc 10 ngày = 1.000.000; tổng các ngày = đúng số tiền (không mất lẻ, ví dụ 100.000 / 30 ngày); giao rỗng = 0; kỳ khóa chặn tạo/sửa/ghi sổ/hủy nhưng cho đọc; mở kỳ (đổi `locked_until`) cho phép lại.
- [x] Viết dịch vụ; nối vào controller; test pass.

### Task 4: Chi phí từ bảo trì (hook)
**Đáp ứng:** FR-M5-04.3 (phía M7); UC-27 A1; C9.
**Files:** Modify `tracecore/equipment/maintenance.py` (`on_submit` gọi `extension.run("tracecore_after_maintenance_submit", doc)`), `tracecore/hooks.py` (đăng ký handler M7), Create `tracecore/costing/from_maintenance.py`; tests `tracecore/costing/tests/test_from_maintenance.py`.
- [x] Test trước: ghi sổ hồ sơ `cost = 2.000.000` loại Incident → một `Cost Entry` Nháp khoản "Sửa chữa", phân bổ 100 % đúng máy, `source_name` = hồ sơ; ghi sổ lại không tạo trùng; `cost = 0` không tạo; hồ sơ nguồn bị Hủy → Cost Entry Nháp không ghi sổ được; test kiến trúc `check_architecture` vẫn sạch (M7 không import M5).
- [x] Viết handler; test pass; `tracecore.equipment.tests.test_maintenance` vẫn pass.

### Task 5: Script Report `Cost by Target`
**Đáp ứng:** FR-M7-02.3; UC-27 bước 5; C11.
**Files:** Create `tracecore/costing/report/cost_by_target/{__init__,cost_by_target.json,cost_by_target.py,cost_by_target.js}`; tests `test_cost_by_target.py`.
- [x] Test trước: hai khoản (một nửa kỳ lọc, một đủ kỳ) phân bổ 60/40 cho hai máy → số liệu theo máy đúng; chỉ tính khoản đã Ghi sổ (Nháp và Hủy bị loại); lọc theo khoản mục/đối tượng; dòng tổng bằng tổng các dòng; R03 không mở được báo cáo.
- [x] Viết báo cáo; test pass.

### Task 6: Client Script và bản dịch
**Đáp ứng:** UC-27 bước 3–4 (hiển thị); SCR-27.
**Files:** Modify `tracecore/costing/doctype/cost_entry/cost_entry.js`, `tracecore/translations/vi.csv`; Create `tracecore/tests/test_cost_entry_desk_assets.py` (kiểm chuỗi `__()` đều có bản dịch, như các test `*_desk_assets` hiện có).
- [x] Form hiển thị tổng tỷ lệ hiện tại và cảnh báo inline khi ≠ 100; chỉ hiện trường đồng hồ khi `source = Meter`; lọc `target` theo `target_type`.
- [x] Test chuỗi dịch pass.

### Task 7: Hoàn tất
- [x] `bench --site test_site run-tests --app tracecore --module` cho các module mới và `tracecore.equipment.tests.test_maintenance`; `--coverage` + `diff-cover … --compare-branch=origin/develop --fail-under=70`.
- [x] `pre-commit run --all-files` sạch; `bench --site <SITE> migrate` + `bench build --app tracecore`.
- [x] Ghi vào cuối plan: kết quả test, coverage, các mục hoãn (C10) và điểm lệch; push nhánh `feat/FEAT-044-cost-entry`. Merge vào `develop` khi người dùng bảo.
