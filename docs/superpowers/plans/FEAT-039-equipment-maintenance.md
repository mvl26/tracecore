# FEAT-039 Bảo trì, kiểm định, hiệu chuẩn và sự cố thiết bị Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [x]`) syntax.

**Goal:** R02 lập kế hoạch và ghi hồ sơ bảo trì / kiểm định / hiệu chuẩn cho từng máy; hệ thống nhắc trước 30 và 7 ngày, cập nhật hạn hiệu lực trên `Equipment`, tự tạo lịch kế tiếp, tự khóa máy quá hạn. Ghi sự cố đưa máy sang Đang sửa chữa, đánh dấu mẻ/lô đang chạy Cần xem xét; đóng sự cố (có kết quả kiểm tra sau sửa) đưa máy về Sẵn sàng.

**Architecture:** DocType `Maintenance Record` (M5 `Equipment`, DT-MAINT, submittable) + child `Maintenance Part`, `Maintenance Affected Load`; dịch vụ `tracecore/equipment/maintenance.py`. Trạng thái máy chỉ đổi qua `equipment.status.set_status` / cờ `flags.tc_equipment`. Chặn tạo mẻ/lô đã có ở `daily_test.equipment_block` (FEAT-040) — FEAT-039 chỉ bổ sung trường hạn và lý do khóa. M5 không import M2: đánh dấu mẻ/lô đang chạy đi qua hook mới `tracecore_equipment_incident` do M2 đăng ký. WF-07 chỉ để hiển thị. Màn SCR-22 là form Desk + Client Script.

**Tech Stack:** Frappe v15, `FrappeTestCase` / `IsolatedTestCase`, Desk Client Script, scheduler `cron`/`daily`.

**Spec:** `docs/srs.md` FR-M5-03 (.1–.3), FR-M5-04 (.1–.4), FR-M5-06 (.2); `docs/use-cases.md` UC-22 (A1, A2, E1–E3); `docs/architecture.md` §5.3 (DT-MAINT, DT-EQUIP), WF-07; `docs/ux-foundations.md` SCR-22; `docs/rtm.md` (TC-22-01, TC-22-02); BRU-EQP-002. Amendment **A-43** (cần tạo, xem Quyết định).

## Global Constraints
- Chỉ `equipment.status` đổi `Equipment.status`; Audit Log Update do doc_events Equipment ghi. Không `set_value('Equipment', …, 'status')` ở nơi khác.
- `Maintenance Record` đi Nháp → Ghi sổ → Hủy, không xóa (`is_submittable=1`, `on_trash` → `core.audit.block_delete`).
- M5 không import M2 (`reprocessing`); chỉ đi qua hook.
- Chuỗi hiển thị qua `_()`/`__()` + `translations/vi.csv` (thuật ngữ QĐ 3671); ngày `dd/mm/yyyy`, VND không lẻ, `Asia/Ho_Chi_Minh`.
- Desk chỉ Client Script, token `--tc-*`; lỗi chặn là `frappe.throw` / `alert-error` inline, không modal/toast cho lỗi chặn.
- Mỗi BRU có ≥ 1 test gắn `@bru("BRU-EQP-002")`. Không chạy E2E, không tạo PR (CLAUDE.md).
- Không làm: email/SMS/leo thang (FEAT-010), `Cost Entry` (FEAT-044), dashboard máy (FEAT-006), đồng bộ ERPNext `Asset Maintenance Log` / `Asset Repair`.

## Quyết định (Amendment A-43, người dùng duyệt 28/10/2026 — chủ đầu tư chưa xác nhận)
| # | Trạng thái | Quyết định |
| :- | :- | :- |
| M1 | [Đã duyệt 28/10/2026] | **Nhắc 30/7 ngày** gửi R02 và R10 qua trung tâm thông báo FEAT-010 (`core.notification.emit`, sự kiện `MAINTENANCE_DUE`, `EQUIPMENT_LOCKED`); đã chuyển từ chuông Desk trực tiếp sau khi FEAT-010 merge. |
| M2 | [Đã duyệt 28/10/2026] | **FR-M5-04.3 hoãn**: chi phí (`cost`, phụ tùng) chỉ lưu trên `Maintenance Record`; `Cost Entry` M7 do FEAT-044 tạo sau từ các hồ sơ đã ghi sổ (hook `tracecore_after_maintenance_submit` để trống). |
| M3 | [Đã duyệt 28/10/2026] | **Loại hồ sơ** `record_type`: `Preventive` (bảo trì), `Inspection` (kiểm định), `Calibration` (hiệu chuẩn), `Incident` (sự cố). Một DocType cho cả bốn (DT-MAINT). |
| M4 | [Đã duyệt 28/10/2026] | **Hạn hiệu lực trên máy**: giữ `Equipment.inspection_due` (kiểm định); thêm `calibration_due` và `maintenance_due` (Date). Ghi sổ hồ sơ Inspection/Calibration/Preventive đặt trường tương ứng = `valid_until` của hồ sơ. |
| M5 | [Đã duyệt 28/10/2026] | **Khóa quá hạn (FR-M5-03.1)**: job 00:00 khóa máy có `inspection_due` hoặc `calibration_due` < hôm nay (`status = Locked`, `lock_reason = Inspection Expired` / `Calibration Expired`). Bảo trì phòng ngừa quá hạn chỉ nhắc, không khóa. `equipment_block` mở rộng kiểm `calibration_due` như `inspection_due`. Máy hấp (áp lực) quá hạn kiểm định không mở khóa tạm được (đã có, FR-M5-06.2); quá hạn hiệu chuẩn thì R02 mở khóa tạm được. |
| M6 | [Đã duyệt 28/10/2026] | **Lịch kế tiếp (FR-M5-03.2)**: ghi sổ hồ sơ có `cycle_months > 0` tự tạo hồ sơ Nháp kế tiếp cùng loại, `planned_date = performed_on + cycle_months`. Sự cố không có chu kỳ. |
| M7 | [Đã duyệt 28/10/2026] | **Đóng hồ sơ = Ghi sổ (submit)**. Inspection/Calibration thiếu `certificate` (Attach) hoặc `valid_until` → chặn (FR-M5-03.3, UC-22 E1). Incident thiếu `post_repair_check` (kết quả kiểm tra sau sửa) → chặn (FR-M5-04.4, E2). Chi phí âm → chặn (E3). |
| M8 | [Đã duyệt 28/10/2026] | **Sự cố**: lưu Nháp sự cố (`record_type = Incident`) ngay lập tức chuyển máy `Repair` (FR-M5-04) và gọi hook `tracecore_equipment_incident(equipment, record)`; M2 đánh dấu mẻ/lô `Running`/đang mở trên máy đó `needs_review = 1`, trả danh sách để điền `Maintenance Affected Load` (FR-M5-04.2). Ghi sổ sự cố → máy `Ready`. Hủy sự cố Nháp → máy về trạng thái trước (`status_before`). |
| M9 | [Đã duyệt] | **Naming series**: `BT-.YYYY.-.#####`, theo dòng "Chứng từ khác" của §5.3.3 (`<PREFIX>-.YYYY.-.#####`); bản đề xuất đầu ghi `BT-.YY.MM.DD.-.####` lệch quy ước nên đã sửa khi ghi A-43. |
| M10 | [Đã duyệt 28/10/2026] | **Quyền**: R02 tạo/sửa/ghi sổ/hủy; R10 tạo/sửa (không ghi sổ); R09 và R01 chỉ đọc; KTV (R03/R05) không thấy. Thêm vào `custom_docperm.json` và `permission_matrix.csv`. |
| M11 | [Đã duyệt 28/10/2026] | **Thuê ngoài (UC-22 A2)**: trường `vendor` (Link Supplier), `contract_no`, `sla_hours` trên hồ sơ; không có logic SLA. |

## Review Focus
- Máy quá hạn kiểm định bị khóa đúng lúc 00:00; máy hấp quá hạn kiểm định R02 mở khóa tạm → bị chặn.
- Ghi sổ kiểm định mới cập nhật `inspection_due` và mở lại máy bị khóa vì quá hạn (nếu không còn lý do khóa khác).
- Sự cố trên máy đang chạy mẻ: mẻ có `needs_review = 1`, máy `Repair`, không tạo được mẻ/lô mới; đóng sự cố thiếu kết quả kiểm tra → chặn.
- Không có đường nào đổi `Equipment.status` ngoài `equipment.status` / `_apply`.
- Nhắc 30/7 ngày gửi đúng một lần mỗi mốc (không gửi lặp mỗi ngày).

## Tasks

### Task 0: Amendment A-43 và tài liệu
**Đáp ứng:** quy trình CLAUDE.md (DocType/naming mới phải qua amendment).
**Files:** Modify `docs/architecture.md` (Revision History A-43, ghi chú A-43, §5.3 dòng DT-MAINT, §5.3.3 naming `BT-`). `docs/srs.md` không có dòng amendment từ A-35 và `docs/rtm.md` không có cột FEAT nên không sửa.
- [x] Ghi M1–M11 với trạng thái đã chốt (người dùng duyệt hết 28/10/2026).
- [x] Commit `docs(architecture): A-43 bảo trì/kiểm định thiết bị (FEAT-039)`.

### Task 1: DocType `Maintenance Record` + child
**Đáp ứng:** FR-M5-03, FR-M5-04; M3, M7, M9, M10, M11.
**Files:** Create `tracecore/equipment/doctype/maintenance_record/{__init__,maintenance_record.json,maintenance_record.py,maintenance_record.js,maintenance_record_list.js,test_maintenance_record.py}`, `tracecore/equipment/doctype/maintenance_part/{__init__,maintenance_part.json,maintenance_part.py}`, `tracecore/equipment/doctype/maintenance_affected_load/{__init__,maintenance_affected_load.json,maintenance_affected_load.py}`; Modify `tracecore/fixtures/custom_docperm.json`, `tracecore/fixtures/permission_matrix.csv`, `tracecore/hooks.py` (doc_events `on_trash` → `block_delete`), `tracecore/tests/factories.py` (`make_maintenance_record`).
**Trường chính:** `equipment` (Link, bắt buộc), `record_type` (Select M3), `status_before` (ẩn), `planned_date`, `cycle_months` (Int), `performed_on` (Date), `vendor` (Link Supplier), `contract_no`, `sla_hours`, `performed_by` (Data), `result` (Select Pass/Fail), `certificate` (Attach), `valid_until` (Date), `cost` (Currency ≥ 0), `occurred_at` (Datetime), `downtime_hours` (Float), `description`, `post_repair_check` (Small Text), `next_record` (Link, read-only), `reminded_30`/`reminded_7` (Check, ẩn), `parts` (Table `Maintenance Part`: item Link Item, qty, rate, amount), `affected_loads` (Table `Maintenance Affected Load`: `load_doctype` Select Sterilization Load/Wash Batch, `load` Dynamic Link, `flagged_at`).
- [x] Test trước: thiếu `equipment` → lỗi; chi phí âm / `qty` âm → chặn (E3); xóa → chặn; R03 không đọc được; R09 đọc được, không ghi.
- [x] Viết JSON + controller `validate` (chỉ kiểm dữ liệu; đổi trạng thái máy ở Task 3/4).
- [x] `bench --site <SITE> migrate`; test pass.

### Task 2: Trường hạn và lý do khóa trên `Equipment`
**Đáp ứng:** FR-M5-03 (cập nhật hạn hiệu lực), FR-M5-06; M4, M5.
**Files:** Modify `tracecore/equipment/doctype/equipment/equipment.json` (thêm `calibration_due`, `maintenance_due`; `lock_reason` thêm `Inspection Expired`, `Calibration Expired`), `tracecore/equipment/daily_test.py` (`equipment_block` + `_inspection_expired` xét `calibration_due`; `unlock_temp` cho phép mở tạm quá hạn hiệu chuẩn), `tracecore/equipment/imports.py` (cột mới, nếu import thiết bị cần), `tracecore/translations/vi.csv`.
- [x] Test trước `@bru("BRU-EQP-002")`: quá hạn hiệu chuẩn → `equipment_block` trả `EQUIPMENT_CALIBRATION_EXPIRED`; R02 mở tạm được; máy hấp quá hạn kiểm định vẫn `UNLOCK_NOT_ALLOWED`.
- [x] Sửa code; test FEAT-040 cũ (`tracecore.equipment.tests.test_daily_test`) vẫn pass.

### Task 3: Dịch vụ `equipment/maintenance.py` — kế hoạch, ghi sổ, lịch kế tiếp
**Đáp ứng:** FR-M5-03, .2, .3; UC-22 bước 2–3, E1; M6, M7.
**Interfaces:** `on_submit(doc)` (gọi từ controller), `before_submit(doc)` (chặn E1/E2/E3), `next_record(doc) -> str | None`, `apply_validity(doc) -> None`.
- [x] Test trước: Inspection thiếu `certificate` hoặc `valid_until` → không ghi sổ được (FR-M5-03.3); ghi sổ Inspection đặt `Equipment.inspection_due = valid_until`; máy đang `Locked` vì `Inspection Expired` → về `Ready`; ghi sổ có `cycle_months = 12` tạo hồ sơ Nháp kế tiếp đúng ngày (FR-M5-03.2), `next_record` trỏ tới nó; hủy hồ sơ đã ghi sổ không đổi lại hạn (ghi Audit `Cancel`).
- [x] Viết dịch vụ; trạng thái máy qua `_apply`/`set_status` có `flags.tc_equipment`.

### Task 4: Sự cố thiết bị + hook M2
**Đáp ứng:** FR-M5-04, .1, .2, .4; UC-22 bước 4–6, E2; M8.
**Files:** Modify `tracecore/equipment/maintenance.py` (`open_incident(doc)`, `close_incident(doc)`), `tracecore/hooks.py` (khai báo `tracecore_equipment_incident = [...]` kèm chú thích hợp đồng), `tracecore/reprocessing/sterilizing.py` và `tracecore/reprocessing/washing.py` (hàm `flag_running_on(equipment, reason) -> list[dict]`: mẻ/lô còn mở trên máy → `needs_review = 1`, Audit), test ở `tracecore/reprocessing/tests/`.
- [x] Test trước: lưu sự cố → máy `Repair`, `status_before` lưu trạng thái cũ; `load.create` / `wash.start` trên máy đó → `EQUIPMENT_NOT_READY` (FR-M5-04.1); mẻ `Running` của máy được `needs_review = 1` và nằm trong `affected_loads` (FR-M5-04.2); ghi sổ sự cố thiếu `post_repair_check` → chặn (FR-M5-04.4); ghi sổ đủ → máy `Ready`; hủy Nháp → về `status_before`.
- [x] Viết code; chạy lại test T2/T5 (`test_washing*`, `test_sterilizing*`, `test_releasing`).

### Task 5: Scheduler khóa quá hạn + nhắc 30/7 ngày
**Đáp ứng:** FR-M5-03 (nhắc), FR-M5-03.1; UC-22 bước 1, A1; M1, M5.
**Files:** Modify `tracecore/equipment/maintenance.py` (`lock_overdue()`, `remind_due()`, `_notify(users, subject, doc)` theo mẫu `par/override.py`), `tracecore/hooks.py` (`"0 0 * * *"`: `lock_overdue`; `daily`: `remind_due`).
- [x] Test trước (đóng băng ngày bằng `frappe.utils` patch / `freeze_time`): máy có `inspection_due` hôm qua → `Locked` + `Inspection Expired` + Audit; máy `Repair`/`Retired` giữ nguyên; hồ sơ Nháp có `planned_date` sau 30 ngày → 1 `Notification Log` cho R02, chạy lại cùng ngày không gửi thêm (`reminded_30`); tương tự mốc 7 ngày.
- [x] Viết code.

### Task 6: Màn SCR-22 (Desk)
**Đáp ứng:** SCR-22; UC-22.
**Files:** `maintenance_record.js` (ẩn/hiện trường theo `record_type`; nút "Lập hồ sơ kế tiếp" chỉ đọc; banner trạng thái máy có chữ), `maintenance_record_list.js` (indicator có chữ: Kế hoạch / Quá hạn / Đã ghi sổ / Sự cố mở), `tracecore/equipment/doctype/equipment/equipment.js` (nút "Ghi sự cố", "Lập kế hoạch" mở form mới; khu "Hạn hiệu lực" hiện `inspection_due`, `calibration_due`, `maintenance_due`), `tracecore/translations/vi.csv`.
- [x] Test asset như `test_incident_desk_assets.py`: file JS tồn tại, chuỗi có trong `vi.csv`, không hex/px ngoài token.
- [x] Kiểm tay trên `tracecore-dev.local`: tạo kiểm định, ghi sổ, ghi sự cố, đóng sự cố.

### Task 7: Hoàn tất nhánh
- [x] `bench --site test_site run-tests --module` cho `tracecore.equipment.*` và các module reprocessing đã sửa; dán kết quả.
- [x] `diff-cover coverage.xml --compare-branch=origin/develop --fail-under=70`; `pre-commit run --all-files` (gồm `check_bru_coverage`).
- [x] Push nhánh `feat/FEAT-039-equipment-maintenance`; **không tạo PR, không chạy E2E**; merge vào `develop` khi người dùng bảo.

## Gap ghi nhận
Email/SMS và leo thang nhắc (FEAT-010); `Cost Entry` M7 từ chi phí sửa chữa (FEAT-044, FR-M5-04.3); NC tự tạo khi sự cố (FEAT-030 có thể nối qua hook sau); đồng bộ ERPNext `Asset Maintenance Log`/`Asset Repair`; theo dõi SLA thuê ngoài; dashboard máy (FEAT-006).

## Ghi chú hiện thực (28/10/2026)
- **Nhánh** `feat/FEAT-039-equipment-maintenance`; commit theo từng task (Task 0–6). Không chạy E2E, không tạo PR.
- **Lệch so với kế hoạch ban đầu:** (1) naming `BT-.YYYY.-.#####` (M9, theo §5.3.3); (2) bảng con `Maintenance Part` dùng `part_name` (Data) và `item` (Link Item, tùy chọn) thay vì chỉ Link Item; (3) thêm cờ `abandoned` + `abandon_reason` và phương thức `abandon` (A-43 M12) vì Frappe không hủy được bản Nháp; (4) mã lỗi `EQUIPMENT_CALIBRATION_EXPIRED` ở `core.errors` và bảng test; (5) `test_errors` thêm `OWN_PIN_RESET` (sót ở `fc9d57f`, test đỏ sẵn trên develop).
- **Không làm** (gap): `Cost Entry` (FEAT-044), email/SMS/leo thang (FEAT-010), đồng bộ `Asset Maintenance Log`/`Asset Repair`, cột hạn mới trong Excel import thiết bị (FEAT-011), logic SLA thuê ngoài.
- **Kiểm tra:** test `FrappeTestCase` các module `tracecore.equipment.*`, `core.tests.test_errors`, `tests.test_permissions`, hồi quy T2/T5/T5b; `pre-commit` (ruff, prettier, eslint, bandit, kiến trúc, BRU) sạch; coverage changed-code 99 % (226 dòng, 2 dòng chưa phủ, ngưỡng 70 %; `diff-cover` so với `origin/develop`); 14 module test, 170 test, đều đạt. Màn SCR-22 chưa được bấm tay trên `tracecore-dev.local`.