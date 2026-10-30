# FEAT-002 Khu – trạm – thiết bị ngoại vi – máy in/cuộn – mẫu nhãn cấu hình không code — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** R10 khai báo trên Desk (SCR-33) khu một chiều, trạm thuộc đúng một khu với chức năng giới hạn theo khu, thiết bị ngoại vi theo trạm, máy in/cuộn và mẫu nhãn mà không cần sửa code; trạm chưa gán khu không được kích hoạt; agent kéo cấu hình trạm qua `tracecore.v1.station.config`.

**Architecture:** Mở rộng DocType `Zone Station` (module Admin Reports) + child `Station Peripheral`; quy tắc khu/trạm dùng chung ở `tracecore/core/zones.py` (để M5 FEAT-038 dùng cho máy hai cửa mà không import M9); RPC hiện có (`ping`, `require_station`, `require_step`, `station.config`) tôn trọng trạng thái kích hoạt; UI là Desk form + Client Script trong thư mục DocType (ADR-002). Printer, Label Template, `set_roll`, dialect ZPL đã có từ FEAT-018 — FEAT-002 chỉ thêm UI cấu hình và xem trước.

**Tech Stack:** Frappe v15, Python 3.11, Desk Client Script (JS), Playwright for Python.

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-002; `docs/srs.md` FR-M9-03 (.1–.3), FR-M2-08.2, FR-M2-08.4, BRU-FLOW-001, BRU-ID-006, NFR-MAINT-01; `docs/use-cases.md` UC-33 (bước 1–2, E1); `docs/architecture.md` §5.3.1 (Zone Station, Printer, Label Template), §5.3.3 (`TR-.###`), ADR-001, ADR-006, A-02; BA #08 DT-ZONE (record_type, zone_type, parent_zone, station_function, peripherals, qr_code, is_active), BA #13 ma trận DT-ZONE (R01 R, R02 R, R09 R, R10 R/W/S/A). Nền: FEAT-001, FEAT-018 (Printer, Label Template, `core.print.set_roll`, `station_printers`, `v1.station.config`).

FR/BRU/AC đáp ứng: FR-M9-03, FR-M9-03.1 (mã TR- + sổ đăng ký; in QR trạm thuộc FEAT-005), FR-M9-03.2 (helper cửa vào/ra, dùng ở FEAT-038), FR-M9-03.3, FR-M2-08.2, FR-M2-08.4; BRU-FLOW-001, BRU-ID-006.

**Nhánh:** `feat/FEAT-002-zone-station-peripherals`, tách từ `feat/FEAT-018-t4-packing-cycle-id` (PR #2 chưa merge). PR base = nhánh FEAT-018 cho tới khi FEAT-018 vào nhánh trên.

## Quyết định cần duyệt

| # | Loại | Câu hỏi | Phương án trong plan | Căn cứ | Task |
| :- | :- | :- | :- | :- | :- |
| E1 | [Chốt] | Mã của khu do R10 tạo | Khu mới đặt tên tự sinh `ZONE-.##` (khu không phải đối tượng quét); 3 khu fixture giữ `ZONE-DIRTY/CLEAN/STERILE`; trạm giữ `TR-.###` | §5.3.3 chỉ quy định `TR-`; BA mẫu dùng "KB", "KVK" | 2 |
| E2 | [Chốt] | Trạm chưa gán khu | Được lưu nhưng `is_active = 0` và không bật được tới khi có khu (thay cho việc báo lỗi như FEAT-001). Mọi RPC trạm và `ping` từ chối trạm không hoạt động với mã mới `STATION_INACTIVE` (409) | FR-M9-03.3, UC-33 E1 | 2, 4 |
| E3 | [Chốt] | Chức năng trạm theo khu | Bẩn: T1, T2 · Sạch: T3, T4, T5 · Vô khuẩn: T5b, T6, T7 · Khoa: T8 · Nhà giặt, Kho chất thải: chưa có chức năng (FEAT-033/047 thêm) | srs Glossary "Khu bẩn/sạch/vô khuẩn", FR-M9-03 "chức năng giới hạn theo khu" | 1, 2 |
| E4 | [Xác nhận] | Thiết bị ngoại vi | Child `Station Peripheral` chỉ cho máy quét và cân (loại, model, kết nối USB HID/Serial/TCP, host, port, cổng serial, baud, đang dùng). Máy in vẫn là DocType Printer (FEAT-018) và hiện trong tab Kết nối của trạm; giao diện dữ liệu máy (CSV/API) thuộc FEAT-024 | architecture §5.3.1, ADR-006 | 3 |
| E5 | [Xác nhận] | Máy hai cửa | `core.zones.check_pass_through(zone_in, zone_out)`: cửa ra phải là khu kế tiếp theo chiều Bẩn → Sạch → Vô khuẩn; FEAT-038 gọi khi lưu Equipment | FR-M9-03.2, BRU-FLOW-001 | 1 |
| E6 | [Xác nhận] | Mã TR- và sổ đăng ký | Trạm mới ghi `Code Registry` (prefix `TR`, ref Zone Station); patch ghi bù cho trạm fixture `TR-001..007`; in nhãn QR trạm để FEAT-005 | FR-M9-03.1, FR-M9-07, BRU-ID-006 | 2 |
| E7 | [Xác nhận] | Xem trước mẫu nhãn trên Desk | Nút "Xem trước" dựng mẫu với dữ liệu mẫu (`sample_pack_context`) và hiện ZPL trong hộp thoại; không gọi dịch vụ ngoài (Labelary) và chưa có "In thử" từ Desk (cần đường in server → máy in của FEAT-005) | FR-M2-08.4, ADR-006 | 4, 5 |
| E8 | [Xác nhận] | Quyền | Zone Station: System Manager và TC R10 đọc/ghi/tạo; TC R01, R02, R09 đọc; không ai xóa (vô hiệu bằng `is_active`; xóa mềm danh mục là FEAT-004) | BA #13 DT-ZONE, CLAUDE.md "không xóa" | 2 |

## Global Constraints

- Kế thừa Global Constraints của FEAT-001 và FEAT-018 (v15, không import chéo M1–M10, chuỗi qua `_()`/`__()` + `vi.csv`, Audit Log mọi thay đổi, không xóa, TDD + `@bru`, coverage changed-code ≥ 70 %, `test_ignore` cho Link ERPNext/HRMS/User vì CI không có Setup Wizard).
- Mã: khu `ZONE-.##` (mới), trạm `TR-.###` ghi `Code Registry` prefix `TR`; không cho nhập tay mã trạm.
- Bảng chức năng theo khu (E3) là hằng số duy nhất `core.zones.STEPS_BY_ZONE_TYPE`; JS lấy từ server (không chép lại trong JS).
- Từ chối trạm không hoạt động: `core.errors.Block` mã `STATION_INACTIVE` → 409 (thêm vào `HTTP_STATUS` và bảng ADR-003). `ping` trả `station_error.code = "STATION_INACTIVE"`.
- Desk UI: chỉ Client Script trong thư mục DocType (`<doctype>.js`), không sửa SCSS Frappe; chuỗi qua `__()`.
- Lệnh: như FEAT-018 (`wsl.exe -d Ubuntu-22.04 --exec bash -lc 'cd ~/tracecore-dev && …'`).

## Review Focus

1. Sửa khu cha của một trạm đang hoạt động sang khu khác loại (ví dụ trạm T4 chuyển sang khu Bẩn) → bị chặn vì chức năng không hợp với khu mới, không âm thầm đổi `zone_type`. Test ở Task 2.
2. Bỏ khu cha của trạm đang hoạt động → trạm tự về không hoạt động (hoặc bị chặn lưu), không còn trạm hoạt động mà không có khu. Test ở Task 2.
3. Kiosk/agent đang chạy ở một trạm vừa bị tắt → lần quét/heartbeat kế tiếp nhận `STATION_INACTIVE` rõ ràng, không 500. Test ở Task 4.
4. Hai thiết bị ngoại vi cùng `TCP host:port` trên một trạm hoặc kết nối Serial thiếu cổng → bị chặn khi lưu. Test ở Task 3.
5. Mẫu nhãn bị R10 sửa hỏng rồi bấm "Xem trước" → hộp thoại hiện lỗi đã dịch, không 500. Test ở Task 4.

---

### Task 0: Ghi quyết định E1–E8 vào tài liệu (Amendment A-03)

**Files:** Modify `docs/architecture.md` (Revision History A-03; §5.3.1 dòng Zone Station; ADR-003 bảng HTTP thêm `STATION_INACTIVE` 409 và `LABEL_RENDER_FAILED` 422 (khi là lỗi của RPC xem trước; vẫn là cảnh báo trong kết quả sinh Cycle ID); §5.3.3 thêm `ZONE-.##`), `docs/srs.md` (ghi chú FR-M9-03 trỏ A-03).

- [ ] **Step 1:** Ghi A-03: E1–E3 "tạm — chờ chủ đầu tư duyệt", E4–E8 dev lead xác nhận. Không thêm/bớt FR/BRU (49 BRU).
- [ ] **Step 2:** `pre-commit run --files <3 docs>`; `bench --site test_site run-tests --module tracecore.tests.test_lint_scripts` OK.
- [ ] **Step 3:** Commit `docs: amendment A-03 quyết định FEAT-002 (tạm, chờ chủ đầu tư duyệt)`.

### Task 1: `core.zones` — chức năng theo khu, máy hai cửa

**Files:** Create `tracecore/core/zones.py`, `tracecore/core/tests/test_zones.py`; Modify `tracecore/core/errors.py` (thêm `STATION_INACTIVE`: 409), `tracecore/core/tests/test_errors.py`, `tracecore/translations/vi.csv`.

**Interfaces — Produces:**
- `STEPS_BY_ZONE_TYPE: dict[str, tuple[str, ...]]` = `{"Dirty": ("T1", "T2"), "Clean": ("T3", "T4", "T5"), "Sterile": ("T5b", "T6", "T7"), "Department": ("T8",), "Linen": (), "Waste": ()}`.
- `ZONE_FLOW: tuple[str, ...]` = `("Dirty", "Clean", "Sterile")`.
- `allowed_steps(zone_type: str) -> tuple[str, ...]`; `check_step(zone_type: str, step: str | None) -> None` (bước không hợp lệ → `frappe.ValidationError` đã dịch, nêu khu và các bước được phép; `None`/rỗng luôn hợp lệ).
- `check_pass_through(zone_in: str, zone_out: str | None) -> None` (tham số là tên Zone Station loại khu; `zone_out` rỗng = máy một cửa; khác → phải đúng khu kế tiếp của `zone_in` trong `ZONE_FLOW`, ngược lại `ValidationError`).

- [ ] **Step 1:** Test: `test_allowed_steps_by_zone_type` (đúng bảng E3), `@bru("BRU-FLOW-001") test_check_step_rejects_step_outside_zone` (`check_step("Dirty", "T4")` → lỗi; `("Clean", "T4")` → None; `("Linen", "T1")` → lỗi; `("Clean", None)` → None), `@bru("BRU-FLOW-001") test_pass_through_must_go_to_next_zone` (`ZONE-DIRTY`→`ZONE-CLEAN` OK; `ZONE-CLEAN`→`ZONE-STERILE` OK; `ZONE-DIRTY`→`ZONE-STERILE` lỗi; `ZONE-CLEAN`→`ZONE-DIRTY` lỗi; `ZONE-STERILE`→bất kỳ lỗi; `zone_out=None` OK; tham số là trạm (`TR-004`) → lỗi), `test_station_inactive_maps_to_409`.
- [ ] **Step 2:** FAIL → **Step 3:** hiện thực → **Step 4:** PASS; `check_architecture.py` sạch → **Step 5:** Commit `feat(core): quy tắc chức năng trạm theo khu và máy hai cửa`.

### Task 2: Zone Station đầy đủ

**Files:** Modify `tracecore/admin_reports/doctype/zone_station/{zone_station.json,zone_station.py,test_zone_station.py}`, `tracecore/hooks.py` (doc_events audit + block delete cho Zone Station), `tracecore/patches.txt`, `tracecore/translations/vi.csv`; Create `tracecore/patches/v0_1/register_station_codes.py`.

**Interfaces:**
- Consumes: `core.zones.check_step`, `code_registry.register`, `is_issued`.
- Produces: trường mới `is_active` (Check, mặc định 1), `description` (Small Text); `zone_type` của trạm luôn lấy từ khu cha; quyền theo E8.

Quy tắc controller:
- Khu: `autoname` → `ZONE-.##` (bỏ qua số đã dùng); bỏ `parent_zone`, `station_step`; `zone_type` bắt buộc; đổi `zone_type` của khu đang có trạm hoạt động mà làm chức năng của trạm không còn hợp lệ → lỗi.
- Trạm: `autoname` `TR-.###` như cũ; `after_insert` ghi `Code Registry` (prefix `TR`, ref Zone Station, idempotent); không có khu cha → `is_active = 0`; bật `is_active` khi không có khu → lỗi "Trạm chưa gán khu không kích hoạt được"; khu cha phải là khu; `check_step(parent.zone_type, station_step)`.
- Không xóa: `on_trash` → `audit.block_delete`.

- [ ] **Step 1:** Test (`test_ignore = ["User"]`): `test_new_zone_named_zone_series` (khu mới → `ZONE-01`…, fixtures không đổi), `@bru("BRU-ID-006") test_station_code_registered` (trạm mới có dòng Code Registry prefix `TR`), `test_patch_registers_fixture_stations` (xóa dòng registry giả lập bằng savepoint rồi chạy patch → `TR-001..007` có dòng; chạy 2 lần không lỗi), `test_station_without_zone_saved_inactive` (FR-M9-03.3), `test_cannot_activate_station_without_zone`, `@bru("BRU-FLOW-001") test_station_step_must_match_zone` (T4 trong khu Bẩn → lỗi), `test_moving_station_to_other_zone_type_checks_step` (Review Focus 1), `test_removing_zone_deactivates_station` (Review Focus 2: trạm hoạt động bỏ khu → lưu với `is_active = 0`), `test_zone_type_change_blocked_when_stations_conflict`, `test_zone_station_cannot_be_deleted`, `test_permissions_match_e8` (gồm `validate_permissions_for_doctype("Zone Station")`), giữ các test FEAT-001 (sửa `test_station_requires_zone_parent` thành: không khu → lưu được nhưng không hoạt động; khu cha là trạm → lỗi).
- [ ] **Step 2:** FAIL → **Step 3:** hiện thực + patch `[post_model_sync]`; `bench --site test_site migrate` → **Step 4:** PASS toàn app → **Step 5:** Commit `feat(admin_reports): Zone Station kích hoạt theo khu, chức năng theo khu, mã TR- vào sổ đăng ký`.

### Task 3: Station Peripheral (child)

**Files:** Create `tracecore/admin_reports/doctype/station_peripheral/{station_peripheral.json,station_peripheral.py,__init__.py}`; Modify `zone_station.json` (Table `peripherals`, chỉ hiện với trạm), `zone_station.py` (kiểm child), `test_zone_station.py`, `tracecore/translations/vi.csv`.

**Interfaces — Produces:** child fields `peripheral_type` (Select `Scanner/Scale`, reqd), `model` (Data), `connection` (Select `USB HID/Serial/TCP`, reqd), `host` (Data), `port` (Int), `serial_port` (Data, ví dụ `COM3`, `/dev/ttyUSB0`), `baud_rate` (Int), `is_active` (Check, mặc định 1), `notes` (Small Text).

Quy tắc: `TCP` cần `host` + `port` 1–65535; `Serial` cần `serial_port`, `baud_rate` mặc định 9600; `USB HID` không cần gì; khu không được có thiết bị ngoại vi; hai dòng `TCP` cùng `host:port` hoặc hai dòng `Serial` cùng `serial_port` trong một trạm → lỗi; cân (`Scale`) không được dùng `USB HID`.

- [ ] **Step 1:** Test: `test_tcp_requires_host_and_port`, `test_serial_requires_port_and_defaults_baud`, `test_duplicate_endpoint_rejected` (Review Focus 4), `test_zone_cannot_have_peripherals`, `test_scale_cannot_be_hid`, `test_peripheral_change_audited` (Audit Log Update của Zone Station có `peripherals`).
- [ ] **Step 2:** FAIL → **Step 3:** hiện thực; migrate → **Step 4:** PASS → **Step 5:** Commit `feat(admin_reports): thiết bị ngoại vi theo trạm (máy quét, cân)`.

### Task 4: RPC tôn trọng trạng thái trạm, `station.config` đầy đủ, xem trước mẫu nhãn

**Files:** Modify `tracecore/v1/__init__.py` (`ping`), `tracecore/v1/_common.py` (`require_station`, `require_step`), `tracecore/v1/station.py`, `tracecore/v1/tests/test_ping.py`, `tracecore/v1/tests/test_station_api.py`, `tracecore/v1/tests/test_pack_api.py` (một test trạm tắt); Create `tracecore/v1/label_template.py`, `tracecore/v1/tests/test_label_template_api.py`; Modify `tracecore/translations/vi.csv`.

**Interfaces — Produces:**
- `ping(station)`: trạm `is_active = 0` → `station_error = {"code": "STATION_INACTIVE", title, reason, action}` (dịch).
- `require_station(station)` (agent RPC FEAT-001) ném `frappe.ValidationError` đã dịch khi trạm không hoạt động; `require_step(station, step)` trả `Block(STATION_INACTIVE)` trước khi kiểm bước.
- `station.config(station)` trả `{"station": {name, label, zone, zone_type, step, is_active}, "printers": [...như cũ], "peripherals": [{peripheral_type, model, connection, host, port, serial_port, baud_rate}]}` (chỉ thiết bị `is_active`); trạm không hoạt động → `STATION_INACTIVE` (409, body chuẩn).
- `tracecore.v1.label_template.preview(template, unicode=0)` (`@frappe.whitelist()`, GET/POST, role System Manager hoặc TC R10): trả `{"zpl": str}` dựng từ `sample_pack_context()` với kích thước/dpi/ngôn ngữ của mẫu; lỗi dựng → `{"ok": false, "error": {...}}` (422, mã `LABEL_RENDER_FAILED` thêm vào bảng HTTP là 422) — không 500.

- [ ] **Step 1:** Test: `test_ping_inactive_station`, `@bru("BRU-FLOW-001") test_t4_scan_rejected_at_inactive_station` (409 `STATION_INACTIVE`, Audit Reject), `test_agent_heartbeat_rejected_for_inactive_station` (Review Focus 3), `test_station_config_includes_station_and_active_peripherals`, `test_preview_returns_zpl_for_sample`, `test_preview_broken_template_is_422` (Review Focus 5), `test_preview_requires_r10_or_system_manager`.
- [ ] **Step 2:** FAIL → **Step 3:** hiện thực (cập nhật bảng `HTTP_STATUS` cho `LABEL_RENDER_FAILED` → 422) → **Step 4:** PASS toàn app; e2e smoke FEAT-001 + T4 (FEAT-018) vẫn xanh → **Step 5:** Commit `feat(v1): trạm không hoạt động bị từ chối, station.config có thiết bị ngoại vi, xem trước mẫu nhãn`.

### Task 5: Desk UI cấu hình (SCR-33)

**Files:** Create `tracecore/admin_reports/doctype/zone_station/zone_station.js`, `tracecore/tracecore/doctype/printer/printer.js`, `tracecore/tracecore/doctype/label_template/label_template.js`; Create `tracecore/v1/zone.py` (`allowed_steps(zone)` whitelisted, đọc) + test; Modify `tracecore/translations/vi.csv`.

Hành vi (mỗi dòng kiểm được bằng tay/e2e):
1. Zone Station: chọn "Là khu" ẩn khu cha, chức năng, thiết bị ngoại vi; khu cha chỉ lọc khu (`is_zone = 1`); khi chọn khu cha, ô Chức năng trạm chỉ còn các bước được phép (lấy từ `tracecore.v1.zone.allowed_steps`); trạm không hoạt động có chỉ báo "Không hoạt động" trên form và trong list view (indicator có chữ).
2. Printer: `station` chỉ lọc trạm; `label_type_loaded` chỉ lọc Item nhóm Label có phương pháp; nút "Nạp cuộn nhãn" mở hộp thoại nhận mã cuộn `CN-` + ô xác nhận "Tôi đã lắp cuộn này vào máy in" → gọi `tracecore.v1.printer.set_roll(roll_code, station, printer)` → hiện kết quả (loại nhãn, số nhãn chờ đã gửi, nhãn chờ lỗi) rồi tải lại form; lỗi → `frappe.msgprint` với tiêu đề/lý do/hành động (Desk không phải màn trạm).
3. Label Template: nút "Xem trước" (2 lựa chọn: có dấu / bỏ dấu) gọi `label_template.preview` → hộp thoại hiện ZPL trong khối mã chỉ đọc + nút sao chép; lỗi → hộp thoại báo lỗi đã dịch.

- [ ] **Step 1:** Test Python: `test_allowed_steps_rpc` (khu Sạch → `["T3","T4","T5"]`; tên không phải khu → `[]`). 
- [ ] **Step 2:** FAIL → **Step 3:** hiện thực; `bench build --app tracecore` → **Step 4:** PASS; `pre-commit run --all-files` sạch; kiểm tay 3 hành vi trên dev site bằng Playwright (user R10 do `e2e_prepare.sh` tạo ở Task 6), lưu ảnh vào workspace → **Step 5:** Commit `feat(ui): Desk cấu hình khu-trạm, nạp cuộn nhãn, xem trước mẫu nhãn`.

### Task 6: E2E Desk, xác minh và PR

**Files:** Create `tests_e2e/test_desk_admin.py`; Modify `scripts/e2e_prepare.sh` (thêm user `TC R10` cho e2e, mật khẩu ngẫu nhiên vào file env 600), `tests_e2e/conftest.py`, `.github/workflows/ci.yml` nếu cần.

- [ ] **Step 1:** Test Playwright (WEB 1366×768, user R10): `test_station_step_options_follow_zone` (tạo trạm mới, chọn khu Sạch → chỉ T3/T4/T5), `test_station_without_zone_shows_inactive`, `test_load_roll_dialog_updates_printer` (máy in demo TR-004 nạp cuộn plasma → label type đổi), `test_label_template_preview_shows_zpl`.
- [ ] **Step 2:** `scripts/e2e_prepare.sh tracecore-dev.local` rồi `pytest tests_e2e` (toàn bộ, gồm smoke và T4) → PASS.
- [ ] **Step 3:** Xác minh: `run-tests --app tracecore --coverage`; `diff-cover coverage.xml --compare-branch=origin/feat/FEAT-018-t4-packing-cycle-id --fail-under=70`; `pre-commit run --all-files`; `check_architecture.py`; `pytest tracecore_agent`; chạy toàn app trên một site mới không Setup Wizard rồi xóa site.
- [ ] **Step 4:** Bảng đối chiếu FR-M9-03(.1–.3), FR-M2-08.2/.4, BRU-FLOW-001, BRU-ID-006 → test chứng minh, đưa vào mô tả PR.
- [ ] **Step 5:** Commit `test(e2e): Desk cấu hình khu-trạm và máy in`; không push — hỏi người dùng trước khi mở PR.
