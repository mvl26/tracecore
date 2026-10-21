# FEAT-038 Hồ sơ thiết bị và chương trình xử lý (Equipment + Process Program) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** R10 khai báo thiết bị (mã `TB-` tự sinh, khu cửa vào/ra, khấu hao/mẻ, dải an toàn) và chương trình xử lý theo máy (tham số, định mức điện/nước/tiêu hao, loại gói tương thích, yêu cầu BI) trên Desk (SCR-21); kiosk/agent tra thiết bị và chương trình của máy qua `tracecore.v1.equipment.get`.

**Architecture:** Module Frappe `Equipment` (M5, đã đăng ký Module Def) chứa DocType `Equipment`, `Process Program` và các bảng con; quy tắc máy hai cửa dùng `core.zones.check_pass_through` (FEAT-002), mã `TB-` ghi `Code Registry`; không import chéo M1–M10 (đọc khu qua DB/`core.zones`). Giao diện là Desk form + Client Script (ADR-002). Trạng thái Locked/Repair và kiểm định thuộc FEAT-039/040, in QR thuộc FEAT-005.

**Tech Stack:** Frappe v15 (ERPNext `Asset`/`Item` chỉ là Link tùy chọn), Python 3.11, Desk Client Script, Playwright for Python.

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-038; `docs/srs.md` FR-M5-01 (.1–.3), FR-M5-02 (.1–.4); `docs/use-cases.md` UC-21 (luồng chính, A1 định mức mặc định, A2 sao chép chương trình, E1–E3); `docs/architecture.md` §5.3.1 (Equipment, Process Program), §5.3.3 (`TB-.####`), ADR-007 (`param_schema`), ADR-009 (Asset), A-03; BA #08 DT-EQUIP, DT-PROGRAM; BA #16 WF-07 (Sẵn sàng / Khóa / Đang sửa chữa / Ngừng sử dụng). Nền: FEAT-001/018/002 (`core.zones`, `code_registry`, Zone Station).

FR/BRU đáp ứng: FR-M5-01 (.1 khu cửa vào/ra, .2 khấu hao/mẻ, .3 chặn trùng serial; in QR → FEAT-005), FR-M5-02 (.1 cảnh báo thiếu định mức + định mức mặc định, .2 chỉ chương trình của máy đã chọn, .3 giữ dữ liệu khi ngừng, .4 cảnh báo ngoài dải an toàn); BRU-ID-006, BRU-EQP-003, BRU-CST-001, BRU-FLOW-001 (ngoại lệ máy hai cửa).

**Nhánh:** `feat/FEAT-038-equipment-programs`, tách từ `feat/FEAT-002-zone-station-peripherals` (PR #3 đang chờ Codex review). PR base = nhánh FEAT-002 cho tới khi FEAT-002 vào nhánh gốc.

## Quyết định cần duyệt

Ghi nhận 21/10/2026: **E1–E3 của A-03 đã được người dùng đồng ý** — Task 0 đổi chữ "tạm" thành "đã duyệt" cho E1–E3.

| # | Loại | Câu hỏi | Phương án trong plan | Căn cứ | Task |
| :- | :- | :- | :- | :- | :- |
| Q1 | [Chốt] | Khi nào chương trình "đủ định mức" (FR-M5-02.1) và định mức mặc định theo loại máy lấy ở đâu | `norm_status` (chỉ đọc) = `Complete` khi `duration_min > 0`, `kwh_per_cycle > 0`, có ≥ 1 dòng tiêu hao (hóa chất/chỉ thị) và, với loại máy dùng nước (Washer-Disinfector, Steam Sterilizer, Laundry Washer, Ultrasonic Cleaner), `water_l_per_cycle > 0`; ngược lại `Missing`. Cờ `use_default_norms` (chỉ TC R10 và System Manager ghi được; R02 chỉ đọc) + dòng DocType mới **`Equipment Type Norm`** (một dòng cho mỗi loại máy: phút chu trình, kWh, nước, hơi) → `norm_status = Default` khi có dòng mặc định, cảnh báo cam, FEAT-046 không tính giá thành khi `Missing`. Danh sách loại máy dùng nước là hằng số kỹ thuật trong `tracecore/equipment/norms.py` | FR-M5-02.1, UC-21 A1/E2, BRU-EQP-003; "định mức mặc định theo loại máy" | 3 |
| Q2 | [Chốt] | Công thức khấu hao/mẻ (FR-M5-01.2) và vai trò của `Asset` | `depreciation_per_load = nguyên giá ÷ (năm khấu hao × số mẻ kế hoạch/năm)`, làm tròn VND không lẻ, bằng 0 khi một số hạng bằng 0; tính trên chính Equipment (khấu hao đường thẳng). Link `Asset` (ERPNext) chỉ là tham chiếu tùy chọn, không đồng bộ giá trị trong FEAT-038 | A-04 thay dòng thiết bị ở architecture §5.7 ("Khấu hao/mẻ = Asset depreciation/năm ÷ số mẻ kế hoạch"): khấu hao tính trên Equipment, Asset chỉ là tham chiếu tùy chọn; CI không có Setup Wizard nên Asset không được bắt buộc | 1 |
| Q3 | [Chốt] | "Dải an toàn của máy" (FR-M5-02.4) lưu ở đâu | Trường tùy chọn trên Equipment: `safe_temp_min`, `safe_temp_max` (°C), `safe_pressure_max` (bar). Chương trình có nhiệt độ/áp suất ngoài dải → **cảnh báo** (msgprint cam + cờ chỉ đọc `outside_safe_range`), không chặn lưu | FR-M5-02.4 "cảnh báo"; BA không nêu dải ở DT-EQUIP | 1, 3 |
| Q4 | [Xác nhận] | "In QR thiết bị" (FR-M5-01) | FEAT-038 sinh mã `TB-` + ghi `Code Registry`; **in QR nằm ở FEAT-005** (`print.object_label`, chưa có bộ mã hóa QR trong app). FR-M5-01 chỉ đạt đủ khi FEAT-005 xong; ghi trong bảng AC của PR | FR-M9-07, FEAT-005 | 1 |
| Q5 | [Xác nhận] | Trạng thái thiết bị (WF-07) | `status` Select 4 giá trị (`Ready/Locked/Repair/Retired`), mặc định `Ready`, chỉ đổi qua hàm `equipment.status.set_status(equipment, status, reason)` (cờ `flags.tc_equipment`, giống guard của Pack); FEAT-038 chỉ dùng `Retired` (nút "Ngừng sử dụng" cho R10/R02, bắt buộc lý do, Audit Log); `Locked/Repair` do FEAT-039/040 dùng. Thiết bị `Retired` không còn nhận chương trình mới và `equipment.get` trả cảnh báo | BA #16 WF-07, ADR-005 (hệ thống đổi trạng thái bằng code + audit; engine cổng bước là ví dụ) | 1, 4 |
| Q6 | [Xác nhận] | `param_schema` của chương trình | Bảng con `Program Parameter` (`parameter_name`, `unit`, `min_value`, `max_value`, `required`) — DocType con mới ghi ở A-04; FEAT-021/022 sinh form nhập tay từ đây | ADR-007 "param_schema: tên, đơn vị, dải, bắt buộc" | 3 |
| Q7 | [Xác nhận] | Quyền | Equipment, Process Program, Equipment Type Norm: System Manager và TC R10 đọc/ghi/tạo; TC R01, R02 đọc (R02 chỉ đọc trên Process Program, kể cả `use_default_norms`; riêng nút Ngừng sử dụng của Equipment cho R10/R02 qua phương thức riêng, Q5); TC R03..R06 đọc (kiosk tra máy); TC R09 đọc; không ai xóa (chương trình ngừng dùng bằng `is_active = 0`, FR-M5-02.3) | BA #13 DT-EQUIP/DT-PROGRAM, CLAUDE.md "không xóa" | 1, 3 |
| Q8 | [Xác nhận] | Serial và khu | Serial bắt buộc, duy nhất không phân biệt hoa/thường và khoảng trắng đầu/cuối; `zone_in` phải là khu (không phải trạm); `zone_out` rỗng = máy một cửa, khác rỗng → `core.zones.check_pass_through(zone_in, zone_out)` | FR-M5-01.1/.3, BRU-FLOW-001 ngoại lệ | 1 |
| Q9 | [Xác nhận] | Ngoài phạm vi | Test hằng ngày, bảo trì, khóa máy (FEAT-039/040); trình điều khiển dữ liệu máy CSV/API và cờ `is_connected` hoạt động (FEAT-024; FEAT-038 chỉ lưu `is_connected`, `has_printout`); Workflow WF-07 hiển thị; đồng bộ Asset | implementation-plan §3 | — |

## Global Constraints

- Kế thừa Global Constraints của FEAT-001/018/002 (v15, không import chéo M1–M10, chuỗi qua `_()`/`__()` + `vi.csv`, Audit Log mọi thay đổi, không xóa, TDD + `@bru`, coverage changed-code ≥ 70 %, `test_ignore` cho Link ERPNext/HRMS/User vì CI không có Setup Wizard — Equipment test module `test_ignore = ["Asset", "Item", "User"]`).
- Mã thiết bị `TB-.####` (§5.3.3) do hệ thống sinh, không nhập tay, ghi `Code Registry` (prefix `TB`, ref `Equipment`); mã không đổi sau khi tạo.
- Module Frappe `Equipment` đã đăng ký; package Python `tracecore/equipment/`; mọi DocType mới ở module này, **trừ** không có gì ở `TraceCore`/`Admin Reports`.
- Loại thiết bị (Select, nguồn Việt: Hấp/Rửa/Plasma/Hàn/Giặt/Sấy/Siêu âm): `Steam Sterilizer`, `Washer-Disinfector`, `Plasma Sterilizer`, `Sealer`, `Laundry Washer`, `Dryer`, `Ultrasonic Cleaner`.
- Tiền VND không lẻ; ngày `dd/mm/yyyy`; số thập phân dấu phẩy (hiển thị).
- Desk UI: chỉ Client Script trong thư mục DocType; chuỗi `__()` + vi.csv; trạng thái luôn có chữ.
- RPC `tracecore.v1.equipment.get` đọc, không ghi, không `@idempotent`.
- Lệnh: như FEAT-002 (`wsl.exe -d Ubuntu-22.04 --exec bash -lc 'cd ~/tracecore-dev && …'`; bật lại Redis nếu WSL khởi động lại).

## Review Focus

1. Hai thiết bị cùng serial nhưng khác hoa/thường hoặc có khoảng trắng thừa → bị chặn. Test ở Task 1.
2. Máy hai cửa khai báo cửa ra sai chiều hoặc nhảy khu (Bẩn → Vô khuẩn), hoặc `zone_in` là một trạm → bị chặn với lý do rõ. Test ở Task 1.
3. Chương trình thiếu định mức mà R10 chưa bật mặc định → `norm_status = Missing`, cảnh báo, không có đường nào bỏ qua; bật mặc định khi loại máy chưa có dòng `Equipment Type Norm` → bị từ chối. Test ở Task 3.
4. Chương trình đã ngừng (`is_active = 0`) vẫn được tham chiếu bởi dữ liệu cũ, không hiện khi chọn chương trình cho máy, không xóa được. Test ở Task 3, 4.
5. Thiết bị `Retired` bị tra bằng mã `TB-` trên kiosk → trả cảnh báo rõ ràng, không 500 và không liệt kê chương trình để chọn. Test ở Task 4.

---

### Task 0: Ghi quyết định Q1–Q9 vào tài liệu (Amendment A-04) và duyệt E1–E3 của A-03

**Files:** Modify `docs/architecture.md` (Revision History A-04; §5.3.1 M5 note: Q1–Q9, DocType mới `Equipment Type Norm`, `Program Parameter`; đổi "tạm" của E1–E3 trong A-03 thành "đã duyệt — người dùng xác nhận 21/10/2026"), `docs/srs.md` (ghi chú FR-M5-01/02 trỏ A-04; sửa dòng revision A-03), `docs/implementation-plan.md` (dòng FEAT-038: thêm 2 DocType mới vào cột Data).

- [ ] **Step 1:** Ghi A-04: Q1–Q3 "tạm — chờ chủ đầu tư duyệt", Q4–Q9 dev lead xác nhận; E1–E3 (A-03) chuyển sang "đã duyệt (người dùng xác nhận 21/10/2026)". Không thêm/bớt FR/BRU (49 BRU).
- [ ] **Step 2:** `pre-commit run --files <3 docs>`; `bench --site test_site run-tests --module tracecore.tests.test_lint_scripts` OK.
- [ ] **Step 3:** Commit `docs: amendment A-04 quyết định FEAT-038, duyệt E1–E3 của A-03`.

### Task 1: DocType `Equipment`

**Files:** Create `tracecore/equipment/doctype/equipment/{__init__.py,equipment.json,equipment.py,test_equipment.py}`, `tracecore/equipment/status.py`, `tracecore/equipment/tests/__init__.py`, `tracecore/equipment/tests/test_status.py`; Modify `tracecore/hooks.py` (audit `doc_events` cho Equipment), `tracecore/tests/factories.py` (`make_equipment`), `tracecore/translations/vi.csv`.

**Interfaces:**
- Consumes: `core.zones.check_pass_through(zone_in, zone_out)`, `code_registry.register/is_issued`, `core.audit.log`, Zone Station.
- Produces: Equipment (`autoname` `TB-.####`, title `equipment_name`): `equipment_name` (reqd), `equipment_type` (Select, reqd), `manufacturer` (reqd), `model` (reqd), `serial_no` (reqd), `zone_in` (Link Zone Station, reqd), `zone_out` (Link Zone Station), `is_connected`, `has_printout` (Check), `purchase_value` (Currency, reqd ≥ 0), `depreciation_years` (Int, reqd ≥ 1), `planned_loads_year` (Int, reqd ≥ 1), `depreciation_per_load` (Currency, chỉ đọc), `capacity` (Data), `safe_temp_min`, `safe_temp_max` (Int °C), `safe_pressure_max` (Float bar), `commissioned_on` (Date), `inspection_due` (Date), `asset` (Link Asset), `status` (Select `Ready/Locked/Repair/Retired`, mặc định `Ready`, chỉ đọc), `retired_on`, `retired_reason`. `equipment.status.set_status(equipment: str, status: str, reason: str | None = None) -> None` (đặt `flags.tc_equipment`; `Retired` cần lý do; chuyển từ `Retired` sang trạng thái khác bị chặn; ghi Audit Log). Factory: `make_equipment(name="Máy hấp test", equipment_type="Steam Sterilizer", serial="SN-001", zone_in="ZONE-CLEAN", zone_out="ZONE-STERILE", purchase_value=600000000, years=10, loads=3000, **kwargs) -> Document`.

- [ ] **Step 1:** Test: `@bru("BRU-ID-006") test_code_tb_registered_and_immutable` (name khớp `^TB-\d{4}$`, `Code Registry` có dòng prefix `TB`; sửa/ép đổi mã → lỗi), `test_code_cannot_be_typed` (truyền `name` tùy ý vẫn ra `TB-`), `@bru("BRU-CST-001") test_depreciation_per_load_formula` (`600000000/(10*3000) == 20000`; làm tròn `1000000/(3*7)` → số nguyên; `purchase_value = 0` → 0), `test_depreciation_requires_positive_years_and_loads`, `test_serial_unique_case_and_space_insensitive` (Review Focus 1: `"sn-001 "` vs `"SN-001"` → lỗi; serial rỗng → lỗi), `@bru("BRU-FLOW-001") test_two_door_machine_must_exit_to_next_zone` (Review Focus 2: Sạch→Vô khuẩn OK; Bẩn→Vô khuẩn, Sạch→Bẩn lỗi; `zone_out` rỗng OK), `test_zone_in_must_be_a_zone_not_a_station` (`TR-004` → lỗi), `test_safe_range_min_not_above_max`, `test_status_defaults_ready_and_cannot_be_edited_directly` (sửa tay `status` → lỗi), `test_set_status_retired_requires_reason_and_is_audited` (Audit Log Update có old/new `status`), `test_retired_cannot_return` , `test_equipment_cannot_be_deleted`, `test_permissions_match_q7` (kể cả `validate_permissions_for_doctype("Equipment")`), `test_asset_is_optional`.
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực (`test_ignore = ["Asset", "Item", "User"]`); `bench --site test_site migrate`. **Step 4:** PASS toàn app; `check_architecture.py` sạch. **Step 5:** Commit `feat(equipment): hồ sơ thiết bị TB-, khu cửa vào/ra, khấu hao/mẻ, trạng thái có kiểm soát`.

### Task 2: Khung chương trình — `Process Program` và bảng con

**Files:** Create `tracecore/equipment/doctype/process_program/*`, `tracecore/equipment/doctype/{program_consumable,program_compatible_pack_type,program_parameter}/*` (child, chỉ json/py), `tracecore/equipment/doctype/process_program/test_process_program.py`; Modify `tracecore/hooks.py` (audit), `tracecore/tests/factories.py` (`make_program`), `tracecore/translations/vi.csv`.

**Interfaces:**
- Produces: Process Program (`autoname` `field:program_code`, mã viết hoa `[A-Z0-9-]`, title `program_name`): `program_code` (reqd), `equipment` (Link Equipment, reqd, set_only_once), `program_name` (reqd), `temperature` (Int), `pressure` (Float), `duration_min` (Int ≥ 0), `chemical` (Link Item), `kwh_per_cycle`, `water_l_per_cycle`, `steam_kg_per_cycle` (Float ≥ 0), `consumables` (Table `Program Consumable`: `item` Link Item reqd, `qty_per_load`, `qty_per_pack` Float ≥ 0, ít nhất một > 0), `compatible_pack_types` (Table `Program Compatible Pack Type`: `pack_type` Link Item), `parameters` (Table `Program Parameter`: `parameter_name` reqd, `unit`, `min_value`, `max_value`, `required` Check), `requires_bi` (Check), `is_active` (Check, mặc định 1), `use_default_norms` (Check), `norm_status` (Select `Complete/Default/Missing`, chỉ đọc), `outside_safe_range` (Check, chỉ đọc). Factory `make_program(equipment, code="MH-01-134", minutes=4, kwh=3.5, water=0, consumables=None, **kwargs)`.

- [ ] **Step 1:** Test (`test_ignore = ["Asset", "Item", "User"]`): `test_program_code_normalized_and_unique` (`"mh-01-134"` → `MH-01-134`; `"MH 01"` lỗi), `test_program_requires_equipment_and_equipment_cannot_change`, `test_consumable_needs_a_positive_quantity`, `test_parameter_min_not_above_max`, `test_duplicate_pack_type_rejected`, `@bru("BRU-EQP-003") test_program_data_kept_when_inactive` (FR-M5-02.3, Review Focus 4: `is_active = 0` giữ nguyên dữ liệu; không xóa được), `test_retired_equipment_cannot_get_new_program` (Q5), `test_permissions_match_q7`.
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực; migrate. **Step 4:** PASS. **Step 5:** Commit `feat(equipment): chương trình xử lý theo máy với tham số, tiêu hao, loại gói tương thích`.

### Task 3: Định mức, mặc định theo loại máy, dải an toàn

**Files:** Create `tracecore/equipment/norms.py`, `tracecore/equipment/doctype/equipment_type_norm/*`, `tracecore/equipment/tests/test_norms.py`; Modify `process_program.py` (+ test), `tracecore/translations/vi.csv`.

**Interfaces:**
- Produces: `norms.WATER_EQUIPMENT_TYPES: tuple[str, ...]` = `("Steam Sterilizer", "Washer-Disinfector", "Laundry Washer", "Ultrasonic Cleaner")`; `norms.norm_status(program: Document) -> str` (`Complete` / `Default` / `Missing` theo Q1); `norms.default_norm(equipment_type: str) -> dict | None` (`{duration_min, kwh_per_cycle, water_l_per_cycle, steam_kg_per_cycle}` từ `Equipment Type Norm`); `norms.apply_default(program) -> None` (điền định mức thiếu từ dòng mặc định, không ghi đè số đã nhập); `norms.range_warnings(program, equipment) -> list[str]` (nhiệt độ ngoài `[safe_temp_min, safe_temp_max]`, áp suất > `safe_pressure_max`; trống = không kiểm). Equipment Type Norm: `autoname field:equipment_type` (Select cùng danh sách loại máy), `duration_min`, `kwh_per_cycle`, `water_l_per_cycle`, `steam_kg_per_cycle`, `notes`; quyền Q7, không xóa.
- Process Program `validate` gọi các hàm trên: tính `norm_status`, `outside_safe_range`, msgprint cảnh báo cam (một lần cho mỗi lần lưu).

- [ ] **Step 1:** Test: `@bru("BRU-EQP-003") test_norm_status_complete` (đủ phút, kWh, tiêu hao, nước với máy hấp), `@bru("BRU-EQP-003") test_norm_status_missing_blocks_costing_flag` (thiếu kWh → `Missing`; máy Plasma/Sealer không cần nước nhưng thiếu tiêu hao → `Missing`), `test_water_required_only_for_water_equipment_types`, `test_default_norms_fill_only_missing_values` (đã nhập 5 kWh thì giữ 5; trống nước → lấy mặc định; `norm_status == "Default"`), `test_use_default_requires_a_type_norm` (Review Focus 3: không có dòng loại máy → lỗi đã dịch), `test_missing_norm_warning_message`, `@bru("BRU-EQP-003") test_outside_safe_range_warns_but_saves` (150 °C với dải 105–140 → lưu được, `outside_safe_range == 1`, có cảnh báo; không có dải → không cảnh báo), `test_equipment_type_norm_one_row_per_type`.
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực; migrate. **Step 4:** PASS toàn app. **Step 5:** Commit `feat(equipment): định mức và mặc định theo loại máy, cảnh báo ngoài dải an toàn`.

### Task 4: RPC `equipment.get`, sao chép chương trình, hàm chọn chương trình

**Files:** Create `tracecore/equipment/programs.py`, `tracecore/equipment/tests/test_programs.py`, `tracecore/v1/equipment.py`, `tracecore/v1/tests/test_equipment_api.py`; Modify `tracecore/translations/vi.csv`.

**Interfaces:**
- Produces: `programs.active_programs(equipment: str) -> list[dict]` (chỉ `is_active = 1`, theo `program_name`; mỗi mục `{program_code, program_name, temperature, pressure, duration_min, requires_bi, norm_status, compatible_pack_types: [item…]}`; FR-M5-02.2); `programs.copy_program(program: str, equipment: str, new_code: str) -> str` (UC-21 A2: cùng `model` và `manufacturer`, sao chép tham số/định mức/tiêu hao/loại gói/tham số, `is_active = 1`; khác model → lỗi); `tracecore.v1.equipment.get(qr)` (`@frappe.whitelist(methods=["POST"])`, đọc): `qr` đi qua `gs1.parse_scan` — loại `equipment` → `{"ok": true, "equipment": {name, equipment_name, equipment_type, status, zone_in, zone_out, is_connected, has_printout, capacity}, "programs": active_programs(...)}`; mã không phải thiết bị → `SCAN_INVALID` 422; không tồn tại → 404 `EQUIPMENT_NOT_FOUND`; `Retired` → `ok: true` với `programs: []` và `warning` (Review Focus 5). Thêm `EQUIPMENT_NOT_FOUND: 404` vào `core.errors.HTTP_STATUS`. Lỗi nghiệp vụ trả qua `reject_block`, Audit `Reject` (ref Equipment khi có).

- [ ] **Step 1:** Test: `@bru("BRU-EQP-003") test_active_programs_only_of_selected_equipment` (FR-M5-02.2: hai máy, chương trình máy khác không xuất hiện; ngừng dùng không xuất hiện), `test_copy_program_same_model_only` (khác model → lỗi; copy có đủ dòng tiêu hao/loại gói/tham số; mã mới trùng → lỗi), `test_get_returns_equipment_and_programs`, `test_get_rejects_non_equipment_code`, `test_get_unknown_equipment_404_with_audit`, `test_get_retired_equipment_warns_without_programs` (Review Focus 5), `test_get_requires_read_permission` (user không có quyền → `PermissionError`), `test_http_status_equipment_not_found`.
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực. **Step 4:** PASS toàn app; e2e smoke + T4 vẫn xanh. **Step 5:** Commit `feat(v1): equipment.get, chương trình đang dùng của máy, sao chép chương trình cùng model`.

### Task 5: Desk UI SCR-21

**Files:** Create `tracecore/equipment/doctype/equipment/equipment.js`, `tracecore/equipment/doctype/equipment/equipment_list.js`, `tracecore/equipment/doctype/process_program/process_program.js`; Create `tracecore/v1/equipment_admin.py` (whitelisted: `retire(equipment, reason)`, `copy_program(program, equipment, new_code)` dùng `status.set_status`/`programs.copy_program`, quyền R10/R02/SM) + `tracecore/v1/tests/test_equipment_admin_api.py`; Modify `tracecore/translations/vi.csv`.

Hành vi (kiểm được bằng tay/e2e):
1. Equipment form: `zone_in`/`zone_out` chỉ lọc khu (`is_zone = 1`); chọn `zone_in` thì `zone_out` gợi ý đúng khu kế tiếp (lấy từ server, không chép bảng khu trong JS); chỉ báo trạng thái có chữ (Sẵn sàng / Khóa / Đang sửa chữa / Ngừng sử dụng); dòng "Khấu hao/mẻ" hiện số đã tính; list view có cột trạng thái bằng chữ.
2. Nút "Ngừng sử dụng" (R10/R02/SM, chỉ khi `Ready`): hộp thoại lý do bắt buộc → RPC `retire` → tải lại; lỗi hiện `frappe.msgprint` đủ tiêu đề/lý do/hành động.
3. Process Program form: chọn máy lọc nút/trường liên quan; thông báo `norm_status` (Đủ / Dùng mặc định / Thiếu) bằng chữ và màu; nút "Sao chép sang máy khác" (chọn máy cùng model + mã mới) gọi `copy_program`.

- [ ] **Step 1:** Test Python: `test_retire_rpc_requires_reason_and_role` (R10/R02/SM được; R04 không), `test_copy_program_rpc_requires_role`, `test_retire_rpc_idempotent_on_retired` (đã ngừng → lỗi rõ ràng). 
- [ ] **Step 2:** FAIL. **Step 3:** Hiện thực; `bench build --app tracecore`. **Step 4:** PASS; `pre-commit run --all-files` (R3: không chuỗi tiếng Việt trong JS); kiểm tay 3 hành vi trên dev site bằng Playwright (user R10 do `e2e_prepare.sh` tạo), ảnh vào workspace. **Step 5:** Commit `feat(ui): Desk SCR-21 hồ sơ thiết bị và chương trình xử lý`.

### Task 6: E2E, xác minh, PR

**Files:** Create `tests_e2e/test_desk_equipment.py`; Modify `scripts/e2e_prepare.sh` (thiết bị + chương trình demo qua `devdata.ensure_equipment_demo()` ghi `TC_E2E_EQ_*`), `tracecore/setup/devdata.py` (+ `tracecore/tests/test_devdata.py`), `tests_e2e/conftest.py`, `.github/workflows/ci.yml` nếu cần.

- [ ] **Step 1:** `devdata.ensure_equipment_demo() -> dict` (idempotent; dev/test site; tạo `Equipment` máy hấp 2 cửa Sạch→Vô khuẩn + máy rửa Bẩn→Sạch, vài chương trình trong đó một chương trình thiếu định mức, một ngừng dùng, dải an toàn; in JSON). Test: idempotent, từ chối ngoài dev/test.
- [ ] **Step 2:** Test Playwright (WEB 1366×768, user R10): `test_equipment_form_zone_out_follows_zone_in`, `test_retire_equipment_requires_reason`, `test_program_norm_status_shown_and_copy_program`, `test_equipment_list_shows_status_text`. Không ngủ cố định; dọn dữ liệu test (Equipment không xóa được → dùng bản ghi cố định có tên rõ ràng, tái sử dụng).
- [ ] **Step 3:** Xác minh toàn nhánh (dán output thật vào mô tả PR): `run-tests --app tracecore --coverage`; `diff-cover coverage.xml --compare-branch=b60a0fc --fail-under=70`; `pre-commit run --all-files`; `check_architecture.py`; `pytest tracecore_agent`; `e2e_prepare.sh` + toàn bộ `pytest tests_e2e` (dev site cổng 8100); toàn app trên site mới không Setup Wizard rồi xóa site.
- [ ] **Step 4:** Bảng đối chiếu FR-M5-01 (.1–.3), FR-M5-02 (.1–.4), BRU-ID-006, BRU-EQP-003, BRU-CST-001, BRU-FLOW-001 → test chứng minh; ghi rõ FR-M5-01 "in QR" chờ FEAT-005.
- [ ] **Step 5:** Commit `test(e2e): Desk thiết bị và chương trình xử lý`; không push — dừng để người dùng cho Codex review rồi hỏi trước khi mở PR.
