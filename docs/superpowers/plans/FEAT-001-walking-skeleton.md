# FEAT-001 Walking Skeleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chứng minh mọi container của architecture §5.1 chạy thật: Chromium kiosk → Page `station` → RPC `tracecore.v1.*` → `core.gs1` + DocType → MariaDB; song song kiosk/CLI → Station Agent → máy in ZPL (hoặc file); Audit Log hook; CI xanh; script deploy viết sẵn. Không có nghiệp vụ thật.

**Architecture:** App Frappe v15 `tracecore` (modular monolith, ADR-001). Dịch vụ xuyên suốt ở package Python `tracecore/core/`; DocType nền ở module Frappe `TraceCore`; RPC mỏng ở `tracecore/v1/` gọi xuống `core`. Station Agent là chương trình Python stdlib riêng (`tracecore_agent/`) nói chuyện với server bằng RPC + API key.

**Tech Stack:** Frappe/ERPNext v15 (tag `v15.123.1` / `v15.123.0`), HRMS `v15.64.5`, Python 3.11, MariaDB 10.6, Redis 7, Node 18, `pylibdmtx` 0.1.10 (libdmtx 0.7.5), Pillow, Playwright for Python, ruff, eslint/prettier, bandit, pip-audit, diff-cover, GitHub Actions.

**Spec:** `docs/implementation-plan.md` §2 (bảng Real/Stub + Done when), §6 F-1..F-20; `docs/architecture.md` §5.2, §5.3, §5.3.3, ADR-002/003/004/006/008/012; `docs/design.md` + `docs/tokens.json`; `CLAUDE.md`.

FR/BRU đáp ứng: FR-M9-07 (partial: Code Registry + GIAI, .1 không sửa/không cấp lại, .3 từ chối mã lạ + ghi log), FR-M9-14 (partial: 4 trạng thái shell), BRU-ID-001, BRU-ID-006; NFR-SEC-03 (audit append-only), EI-SW-003/004.

## Global Constraints

- Frappe/ERPNext/HRMS `version-15`, Python 3.11, Node 18, MariaDB 10.6, Redis 7. Không lên v16.
- **Module (amendment 2026-10-19, đã duyệt):** Module Def `Core` (frappe) và `HR` (hrms) đã tồn tại, nên: dịch vụ ở package thường `tracecore/core/`; DocType nền (Audit Log, Code Registry, Idempotency Key, Print Job) ở module `TraceCore`; Set Unit + Instrument Set Type ở `Instrument`; Zone Station (khung) ở `Admin Reports`; Page `station` ở `UI`; M4 chỉ có package `tracecore/hr/`, chưa đăng ký Module Def. Module Def đăng ký: `TraceCore, Instrument, Reprocessing, Linen, Equipment, Inventory, Costing, Par, Admin Reports, Waste, UI`.
- Không import chéo giữa package M1–M10; chỉ đi qua `tracecore.core` hoặc Link/hook.
- Chỉ `core.step_gate` được đổi `Set Unit.status` (skeleton chưa có step_gate → `status` read-only, mặc định `New`).
- `Audit Log` append-only: permission không có write/delete; `before_save` ném lỗi khi không phải bản mới; `on_trash` ném lỗi.
- RPC tên `tracecore.v1.<domain>.<action>`; RPC ghi của trạm/agent và `set_unit.get` dùng `@tracecore.core.idempotency.idempotent` với header `X-Idempotency-Key` (UUID) và `client_ts` ISO 8601 có offset (lưu UTC).
- Mã GS1 và DataMatrix sinh ở server qua `core.gs1`; Set ID = GIAI (AI 8004) = `name` của Set Unit, không cho nhập tay.
- Tiền tố GS1 dev/staging: `tc_gs1_company_prefix` trong `site_config.json`, mặc định `9520000` (prefix GS1 `952` dành cho demo, OQ-05/P-13: nhãn in ghi `TEST`).
- Mọi chuỗi hiển thị qua `_()` / `__()`; nguồn tiếng Anh, bản dịch ở `tracecore/translations/vi.csv`. Không có ký tự tiếng Việt trong string literal của `.py/.js/.html` (trừ docstring, test, translations).
- Giao diện chỉ dùng biến `--tc-*` sinh từ `docs/tokens.json`; không gõ hex/px trong CSS của Page. STN: chữ ≥ 16 px, nút ≥ 48 px (chính 56), focus ring 3 px.
- Lỗi chặn trên trạm: `alert-error` inline (kết quả → lý do → hành động), không modal/toast. Màn trạm có đủ loading / empty / error / offline.
- Ngày `dd/mm/yyyy`, 24 h, `Asia/Ho_Chi_Minh` (System Settings đặt ở `after_install`).
- Không commit secrets / `site_config.json`; chỉ commit `*.example`.
- `install_prod.sh` chỉ viết, chỉ chạy `--dry-run`.
- TDD: `FrappeTestCase`, mỗi BRU có test gắn `@bru("BRU-…")`. Coverage changed-code ≥ 70 % (`diff-cover --fail-under=70`).

## Review Focus

1. Chuỗi từ máy quét HID có tiền tố AIM `]d2`, FNC1 truyền thành `\x1d` hoặc bị mất, kèm `\r\n`/Tab cuối → `parse_scan` vẫn nhận ra GIAI (test ở Task 2).
2. Bấm Enter hai lần / bấm "Thử lại" sau timeout → cùng `X-Idempotency-Key`, server trả lại response đã lưu, không ghi trùng (test ở Task 7; Page dùng lại key khi Thử lại, sinh key mới cho lần quét mới — Task 11).
3. Mất mạng giữa lúc quét → Page chuyển trạng thái offline trong ≤ timeout 8 s, không treo loading (e2e ở Task 13).
4. `?station=` thiếu hoặc không tồn tại → trạng thái error có hành động, không màn trắng (test `ping` ở Task 8, e2e ở Task 13).
5. Administrator xóa Audit Log từ Desk / REST hoặc sửa bản ghi → bị từ chối (test ở Task 5).

---

### Task 1: Khung module, hạ tầng test, amendment tài liệu

**Files:**
- Modify: `tracecore/modules.txt`, `tracecore/hooks.py`, `pyproject.toml`, `CLAUDE.md`, `docs/architecture.md`
- Create: `tracecore/{instrument,reprocessing,linen,equipment,inventory,costing,par,admin_reports,waste,ui}/__init__.py`, `tracecore/core/__init__.py`, `tracecore/hr/__init__.py`, `tracecore/v1/__init__.py`, `tracecore/setup/__init__.py`, `tracecore/setup/install.py`, `tracecore/tests/__init__.py`, `tracecore/tests/utils.py`, `tracecore/tests/test_install.py`

**Interfaces:**
- Produces: `tracecore.tests.utils.bru(*ids) -> decorator` (gắn `__bru__`), `tracecore.tests.utils.request_headers(headers: dict)` (context manager giả lập `frappe.local.request.headers`), `tracecore.setup.install.after_install()`.

- [ ] Step 1: Viết `test_install.py`: `test_module_defs_registered` (11 Module Def ở trên có `app_name == "tracecore"`, không có `Core`/`HR` thuộc tracecore), `test_system_settings_localized` (`language == "vi"`, `time_zone == "Asia/Ho_Chi_Minh"`, `date_format == "dd/mm/yyyy"`, `time_format == "HH:mm"`).
- [ ] Step 2: Chạy `bench --site test_site run-tests --module tracecore.tests.test_install` → FAIL.
- [ ] Step 3: Ghi `modules.txt`; tạo package; `after_install` đặt System Settings (language vi, time_zone, date_format, time_format, number_format `#.###,##`, first_day_of_the_week Monday); thêm `pylibdmtx~=0.1.10` vào `pyproject.toml` dependencies; viết `tests/utils.py`. Amendment: sửa danh sách module trong `CLAUDE.md`, thêm ghi chú §5.2/§5.3 + 1 dòng Revision History (2026-10-19) trong `docs/architecture.md`.
- [ ] Step 4: Cài lại app trên `test_site` (`uninstall-app` + `install-app`) → test PASS.
- [ ] Step 5: Commit `feat(core): khung 11 module, after_install vi, amendment module`.

### Task 2: `core.gs1` — GIAI, parse_scan, DataMatrix PNG, ZPL `^BXN`

**Files:** Create `tracecore/core/gs1.py`, `tracecore/core/tests/__init__.py`, `tracecore/core/tests/test_gs1.py`

**Interfaces:**
- Produces (thuần Python, không gọi DB):
  - `class GS1Error(ValueError)` (thuộc tính `code: str`)
  - `CSET82: frozenset[str]`
  - `make_giai(prefix: str, asset_ref: str) -> str` — prefix `^\d{4,12}$`, asset_ref ≠ rỗng và thuộc CSET82, tổng ≤ 30 ký tự.
  - `giai_hri(giai) -> str` = `"(8004)" + giai`; `giai_payload(giai) -> str` = `"\x1d8004" + giai` (GS đầu = FNC1).
  - `parse_scan(raw: str, company_prefix: str | None = None) -> dict` → `{"type": "set"|"pack"|"employee"|"equipment"|"location"|"station"|"roll"|"container"|"unknown", "id": str|None, "raw": str}`. Bỏ `\r\n\t`/khoảng trắng hai đầu, tiền tố AIM `]d2 ]d1 ]Q3 ]C1`, GS đầu; nhận `(8004)…`, `8004…` (tới GS kế tiếp), GIAI trần bắt đầu bằng `company_prefix` (mặc định từ `frappe.conf.tc_gs1_company_prefix` hoặc `9520000`); mã nội bộ theo §5.3.3: `NV-\d{5}`, `TB-\d{4}`, `KE-\d{4}`, `TR-\d{3}`, `CN-\d{5}`, `CT-\d{6}-\d{5}`, `CY-\d{6}-(T\d{2}-)?\d{4}`; > 120 ký tự → unknown.
  - `encode_datamatrix_png(payload: str, module_px: int = 6, margin_px: int = 12) -> bytes` (libdmtx qua `pylibdmtx.wrapper`, `DmtxPropFnc1 = 0x1D`).
  - `decode_datamatrix_png(png: bytes) -> str` (decoder đặt FNC1 = GS; trả chuỗi có `\x1d` ở FNC1).
  - `zpl_datamatrix(payload: str, x: int, y: int, module_dots: int = 6) -> str` → `^FO{x},{y}^BXN,{module_dots},200,0,0,1,_,1^FD{data}^FS`, trong đó GS → `_1`, `_` → `__`.
- [ ] Step 1: Test: `test_make_giai_valid` (`make_giai("9520000","BPT01000001") == "9520000BPT01000001"`), `test_make_giai_rejects` (prefix chữ, 3 chữ số, 13 chữ số, asset_ref có `#`/khoảng trắng/rỗng, tổng 31 ký tự → `GS1Error`), `test_parse_scan_variants` (`"]d2\x1d80049520000BPT01000001\r\n"`, `"(8004)9520000BPT01000001"`, `"80049520000BPT01000001"`, `"9520000BPT01000001"` đều → set/`9520000BPT01000001`), `test_parse_scan_internal_codes` (NV-00012→employee, TB-0003→equipment, KE-0001→location, TR-004→station, CN-00001→roll, CT-261019-00001→container, CY-261019-0001 và CY-261019-T04-0001→pack), `test_parse_scan_unknown` (`"ABC"`, `""`, `"8004"`, 200 ký tự, `"(01)0952..."` → unknown), `test_datamatrix_png_roundtrip` (decode == `"\x1d8004"+giai`, PNG header `\x89PNG`), `test_zpl_datamatrix` (chứa `^BXN,6,200`, `^FD_18004`, `A_B` → `A__B`).
- [ ] Step 2: Chạy `--module tracecore.core.tests.test_gs1` → FAIL.
- [ ] Step 3: Hiện thực `gs1.py`.
- [ ] Step 4: PASS. Step 5: Commit `feat(core): core.gs1 GIAI, parse_scan, DataMatrix PNG và ZPL`.

### Task 3: Zone Station (khung), Instrument Set Type (khung), fixtures Role/Zone

**Files:** Create `tracecore/admin_reports/doctype/zone_station/{__init__,zone_station.json,zone_station.py,test_zone_station.py}`, `tracecore/instrument/doctype/instrument_set_type/{…}`, `tracecore/fixtures/role.json`, `tracecore/fixtures/zone_station.json`; Modify `hooks.py` (`fixtures`).

**Interfaces:**
- Zone Station: `zone_station_name` Data reqd; `is_zone` Check; `zone_type` Select `Dirty|Clean|Sterile|Department|Linen|Waste`; `parent_zone` Link Zone Station; `station_step` Select `|T1|T2|T3|T4|T5|T5b|T6|T7|T8`. autoname `naming_series:` `TR-.###`. Validate: trạm (is_zone=0) bắt buộc `parent_zone` là khu và `zone_type` lấy theo khu cha.
- Instrument Set Type: `type_code` Data reqd unique (A–Z0–9, 2–8 ký tự, viết hoa) = name; `set_type_name` Data reqd (title); `method` Select `Steam|Plasma` reqd.
- Fixtures: Role `TC R01`…`TC R10`, `TC Agent` (desk_access 1). Zone Station: `ZONE-DIRTY`, `ZONE-CLEAN`, `ZONE-STERILE` (is_zone=1) và trạm `TR-001`…`TR-007` = T1…T7 (T1–T2 → ZONE-DIRTY, T3–T5 → ZONE-CLEAN, T6–T7 → ZONE-STERILE).
- Produces: `tracecore.tests.factories.make_set_type(type_code="TST", method="Steam") -> Document`.
- [ ] Step 1: Test: `test_fixture_zones` (3 khu + `TR-004` có `parent_zone == "ZONE-CLEAN"`, `zone_type == "Clean"`, `station_step == "T4"`), `test_station_requires_zone_parent`, `test_roles_exist` (11 role), `test_set_type_code_validation` (`"bpt 1"` → lỗi; `"bpt1"` lưu thành `BPT1`).
- [ ] Step 2: FAIL → Step 3: tạo DocType JSON + controller + fixtures + `factories.py` → `bench --site test_site migrate` → Step 4: PASS → Step 5: Commit `feat(admin_reports,instrument): Zone Station và Instrument Set Type khung, fixtures role/khu`.

### Task 4: Code Registry + `core.code_registry`

**Files:** Create `tracecore/tracecore/doctype/code_registry/{…,test_code_registry.py}`, `tracecore/core/code_registry.py`

**Interfaces:**
- Code Registry fields: `code` Data unique (= name, autoname `field:code`), `prefix` Data, `ref_doctype` Link DocType, `ref_name` Dynamic Link, `issued_on` Datetime, `issued_at` Link Zone Station, `status` Select `Active|Disabled`, `disabled_on` Datetime, `disabled_reason` Small Text. Permission: System Manager read only; `in_create = 1`.
- Controller: không phải bản mới mà đổi `code/prefix/ref_doctype/ref_name/issued_on` → `frappe.ValidationError`; `on_trash` → luôn `frappe.ValidationError` (không xóa để không cấp lại).
- Produces: `register(code, prefix, ref_doctype=None, ref_name=None, station=None) -> str` (trùng → `CodeAlreadyIssuedError(frappe.ValidationError)`); `is_issued(code) -> bool`; `next_set_id(type_code: str) -> str` = `gs1.make_giai(company_prefix(), type_code + serial6)` với serial lấy từ naming series `"{prefix}{type_code}.######"`, bỏ qua serial đã có trong registry; `company_prefix() -> str`.
- [ ] Step 1: Test (`@bru("BRU-ID-006")`): `test_register_and_duplicate_rejected`, `test_registry_entry_immutable`, `test_registry_entry_cannot_be_deleted` (kể cả Administrator), `test_next_set_id_unique_and_registered` (2 lần gọi khác nhau, cả hai `is_issued`, bắt đầu bằng `company_prefix()`); `@bru("BRU-ID-001")` `test_next_set_id_skips_issued_serial` (đăng ký trước serial kế tiếp → hàm trả serial sau đó).
- [ ] Step 2–4: FAIL → hiện thực → PASS. Step 5: Commit `feat(core): Code Registry chặn sửa/xóa/cấp lại mã`.

### Task 5: Audit Log append-only + `core.audit`

**Files:** Create `tracecore/tracecore/doctype/audit_log/{…,test_audit_log.py}`, `tracecore/core/audit.py`

**Interfaces:**
- Audit Log: autoname `autoincrement`; fields `timestamp` Datetime, `user` Link User, `station` Link Zone Station, `ref_doctype` Link DocType, `ref_name` Dynamic Link, `action` Select `Create|Update|Submit|Cancel|Delete|Login|Reject|Override|View Patient Code|Sync`, `old_value` JSON, `new_value` JSON, `reason` Small Text, `device` Data, `request_id` Data, `client_ts` Datetime (UTC). Permission: System Manager read; không write/create/delete cho role nào; `in_create = 1`, `track_changes = 0`. Index: `(ref_doctype, ref_name, timestamp)`, `(user, timestamp)`, `(station, timestamp)` qua `on_doctype_update()`.
- Controller: `before_save` không phải bản mới → `AuditLogImmutableError`; `on_trash` → `AuditLogImmutableError`.
- Produces: `log(action, ref_doctype=None, ref_name=None, old=None, new=None, reason=None, station=None, device=None, client_ts=None) -> str` (ghi bằng `ignore_permissions`, user = session user, station/device/request_id mặc định từ header `X-TC-Station`/`X-TC-Device`/`X-Request-ID`); `on_document_event(doc, method)` (after_insert → Create toàn bộ snapshot; on_update khi không `in_insert` → Update với diff field đổi; on_submit/on_cancel → Submit/Cancel); `block_delete(doc, method)` → `frappe.ValidationError` + không xóa; `snapshot(doc) -> dict` bỏ field kiểu Password và field meta chuẩn.
- [ ] Step 1: Test: `test_log_inserts_row`, `test_audit_log_cannot_be_modified`, `test_audit_log_cannot_be_deleted_by_administrator`, `test_no_role_has_write_or_delete` (duyệt DocPerm), `test_system_manager_user_has_no_delete_permission` (`frappe.has_permission(..., "delete", user=…) is False`), `test_snapshot_drops_password_fields` (doc `User` có `new_password`), `test_station_from_header` (dùng `request_headers`).
- [ ] Step 2–4. Step 5: Commit `feat(core): Audit Log append-only và core.audit`.

### Task 6: Set Unit (GIAI là name) + audit hook

**Files:** Create `tracecore/instrument/doctype/set_unit/{…,test_set_unit.py}`; Modify `hooks.py` (`doc_events["Set Unit"]`), `tracecore/tests/factories.py` (`make_set_unit`).

**Interfaces:**
- Set Unit fields: `set_id` Data read-only unique, `set_type` Link Instrument Set Type reqd, `department` Link Department, `status` Select `New|In Circulation|Processing|Reprocess|Sterile|At Department|End of Life|Disposed` default `New` read-only, `cycles_used` Int default 0 read-only, `max_cycles` Int reqd (> 0), `active_cycle_id` Data read-only, `current_station` Link Zone Station, `is_loaner` Check. `autoname()` → `self.name = self.set_id = code_registry.next_set_id(type_code)` rồi `register(...)` sau insert (`after_insert` controller). `validate`: bản đã có mà `set_id` đổi → lỗi. Permission: System Manager create/read/write; `TC R01..R10` read; không ai delete.
- `doc_events`: after_insert/on_update/on_submit/on_cancel → `tracecore.core.audit.on_document_event`; on_trash → `tracecore.core.audit.block_delete`.
- Produces: `factories.make_set_unit(set_type=None, max_cycles=300, **kw) -> Document`.
- [ ] Step 1: Test: `@bru("BRU-ID-001")` `test_set_id_is_generated_giai` (name == set_id, bắt đầu bằng prefix + type_code, `parse_scan(name)["type"] == "set"`), `@bru("BRU-ID-001")` `test_user_supplied_name_ignored`, `@bru("BRU-ID-001")` `test_set_id_cannot_be_changed`, `@bru("BRU-ID-006")` `test_set_id_registered_in_code_registry`, `test_create_and_update_write_audit_log` (Create có `new_value.set_type`; sửa `max_cycles` → Update với `old_value.max_cycles`/`new_value.max_cycles`), `test_delete_blocked`.
- [ ] Step 2–4. Step 5: Commit `feat(instrument): Set Unit GIAI + audit hook`.

### Task 7: `client_ts`, Idempotency Key, `@idempotent`, purge

**Files:** Create `tracecore/core/client_time.py`, `tracecore/core/idempotency.py`, `tracecore/tracecore/doctype/idempotency_key/{…}`, `tracecore/core/tests/test_idempotency.py`; Modify `hooks.py` (`scheduler_events.daily`).

**Interfaces:**
- `parse_client_ts(value: str) -> datetime` (naive UTC; thiếu offset hoặc sai định dạng → `ClientTimestampError(frappe.ValidationError)`).
- Idempotency Key: autoname `field:key`; `key` Data unique, `endpoint` Data, `user` Link User, `station` Link Zone Station, `request_hash` Data, `response` JSON, `created_at` Datetime, `client_ts` Datetime. Permission: System Manager read.
- `idempotent(fn)`: đọc `X-Idempotency-Key` (UUID) và kwarg `client_ts`; thiếu/sai → `IdempotencyKeyError` (HTTP 400); hash = sha256(endpoint + JSON kwargs sắp xếp, bỏ `cmd`); key đã có: cùng user + hash → trả `json.loads(response)` không chạy lại; khác → `IdempotencyConflictError` (HTTP 409). Key mới: insert dòng trước, chạy `frappe.call(fn, **kwargs)`, cập nhật `response`. Lỗi trong hàm → transaction rollback (key không lưu).
- `purge_expired(days: int = 30) -> int`.
- [ ] Step 1: Test: `test_parse_client_ts` (`"2026-10-19T09:00:00+07:00"` → `02:00` UTC; `"2026-10-19T09:00:00"` → lỗi), `test_missing_or_invalid_key_rejected`, `test_missing_client_ts_rejected`, `test_replay_returns_stored_response_without_rerun` (bộ đếm gọi = 1), `test_same_key_different_payload_conflict`, `test_same_key_other_user_conflict`, `test_purge_expired`.
- [ ] Step 2–4. Step 5: Commit `feat(core): Idempotency Key và decorator @idempotent`.

### Task 8: RPC `v1.ping`, `v1.set_unit.get`, `v1.audit.query`

**Files:** Modify `tracecore/v1/__init__.py`; Create `tracecore/v1/set_unit.py`, `tracecore/v1/audit.py`, `tracecore/v1/tests/{__init__,test_ping.py,test_set_unit_api.py,test_audit_api.py}`

**Interfaces:**
- `ping(station: str | None = None) -> dict` → `{"app": "tracecore", "version", "site", "time_zone", "server_time" (ISO có offset), "station": {"name","label","step","zone_type"} | None, "station_error": {code,title,reason,action} | None, "agent": dict | None}` (agent = heartbeat cache theo station).
- `set_unit.get(set_id: str, client_ts: str) -> dict` (`@frappe.whitelist()` + `@idempotent`): thành công `{"ok": True, "set_unit": {set_id, set_type, set_type_name, method, status, cycles_used, max_cycles, active_cycle_id, current_station, is_loaner, department}}`; thất bại `{"ok": False, "error": {"code", "title", "reason", "action"}}` + `audit.log("Reject", reason=code)`. Mã lỗi: `SCAN_INVALID` (parse_scan unknown: "Invalid code" / "Code {0} was not issued by TraceCore." / "Rescan the set tag or call R02."), `SCAN_WRONG_TYPE` (mã hợp lệ nhưng không phải bộ), `SET_NOT_FOUND`. Không có quyền đọc Set Unit → `frappe.PermissionError`.
- `audit.query(ref_doctype=None, ref_name=None, user=None, station=None, from_ts=None, to_ts=None, limit=50) -> list[dict]` qua `frappe.get_list` (tôn trọng permission, limit ≤ 500).
- [ ] Step 1: Test: `test_ping_fields` (time_zone `Asia/Ho_Chi_Minh`, server_time có offset), `test_ping_station_info` (`TR-004` → zone_type Clean, step T4), `test_ping_unknown_station` (station_error code `STATION_NOT_FOUND`), `@bru("BRU-ID-006")` `test_get_unknown_code_vietnamese_error_and_audit` (lang `vi`: title == "Mã không hợp lệ", có Audit Log `Reject`), `test_get_returns_set_unit_under_1s`, `test_get_wrong_type`, `test_get_not_found`, `test_get_requires_read_permission`, `test_audit_query_filters`.
- [ ] Step 2–4. Step 5: Commit `feat(v1): RPC ping, set_unit.get, audit.query`.

### Task 9: `core.print`, Print Job, `v1.print.*`, `v1.agent.heartbeat`, provisioning

**Files:** Create `tracecore/core/print.py`, `tracecore/tracecore/doctype/print_job/{…}`, `tracecore/v1/print.py`, `tracecore/v1/agent.py`, `tracecore/setup/provision.py`, tests `tracecore/core/tests/test_print.py`, `tracecore/v1/tests/test_agent_api.py`.

**Interfaces:**
- Print Job: autoname `autoincrement`; `station` Link Zone Station, `printer` Data (IP:port hoặc `file`), `template` Data, `payload` Code (ZPL), `data` JSON, `status` Select `Queued|Printed|Failed` default Queued, `output_mode` Select `Printer|File`, `output_ref` Data, `attempts` Int, `error` Small Text, `reprint_reason` Small Text, `printed_at` Datetime. Permission: System Manager read/write, TC Agent read/write (không delete).
- `core.print.render_test_label(station: str) -> dict` → `{"giai","hri","zpl","preview_png"(bytes)}`; ZPL: `^XA^CI28^PW590^LL354` + `zpl_datamatrix(giai_payload(giai), 30, 40)` + dòng chữ ASCII `TraceCore TEST`, `(8004) <giai>`, `Station <station>`, `^XZ`; GIAI test = `make_giai(company_prefix(), "TEST" + yymmddHHMMSS)` (không đăng ký Code Registry — chỉ là nhãn thử). Preview PNG 590×354 (300 dpi, 50×30 mm) = DataMatrix + text bằng Pillow.
- `core.print.create_job(station, zpl, data, template) -> str`; `core.print.ack(job, status, output_mode, output_ref=None, error=None) -> dict`.
- `v1.print.test_label(station, client_ts) -> {"print_job","giai","zpl","preview_png_b64"}` (role TC Agent, `@idempotent`); `v1.print.ack(print_job, status, output_mode, client_ts, output_ref=None, error=None) -> {"ok": True, "status"}` (role TC Agent, `@idempotent`).
- `v1.agent.heartbeat(station, client_ts, agent_version=None, queue_depth=None, printer=None) -> {"ok": True, "server_time"}` (role TC Agent, `@idempotent`; lưu `frappe.cache.hset("tc_agent_heartbeat", station, …)` để `ping` đọc).
- `setup.provision.agent_user(station: str, config_path: str) -> str`: tạo/cập nhật user `agent-<tr-004>@local` (role TC Agent), sinh API key/secret, ghi thẳng vào INI `config_path` (chmod 600), chỉ in đường dẫn. `setup.provision.station_user(station: str, password: str) -> str`: user `station-<t4>@local` role theo khu (T1–T2 R03, T3–T5 R04, T6–T7 R06).
- [ ] Step 1: Test: `test_render_test_label` (ZPL bắt đầu `^XA`, kết thúc `^XZ`, có `^BXN` và `_18004`; PNG decode ra `"\x1d8004"+giai`), `test_test_label_creates_queued_job`, `test_ack_marks_printed` (status Printed, output_mode File, printed_at có giá trị), `test_ack_unknown_job`, `test_agent_endpoints_require_role` (user không có TC Agent → PermissionError), `test_heartbeat_visible_in_ping`, `test_provision_agent_user_writes_config` (file chứa `api_key`, không in secret ra stdout).
- [ ] Step 2–4. Step 5: Commit `feat(core): core.print, Print Job, RPC agent/print, provisioning user kỹ thuật`.

### Task 10: `scripts/build_tokens.py` → `tokens.css` + `tracecore-theme.css`

**Files:** Create `scripts/build_tokens.py`, `tracecore/public/css/tokens.css` (sinh), `tracecore/public/css/tracecore-theme.css` (sinh), `tracecore/tests/test_build_tokens.py`; Modify `hooks.py` (`app_include_css`).

**Interfaces:**
- `build(tokens: dict) -> tuple[str, str]` (tokens.css, theme.css); `main(argv=None) -> int` với `--check` (khác file trên đĩa → in diff, exit 1). Bảng `CSS_VARS: list[tuple[str, str]]` (tên `--tc-*` theo design.md §2.2 → đường dẫn token), giải alias `{color-raw.navy}`, shadow → `0 6px 24px rgba(...)`, cubicBezier → `cubic-bezier(...)`, fontFamily → danh sách có nháy cho tên nhiều từ; `[data-surface="STN|PDA|DEPT"]` từ `surface-override`; khối `prefers-reduced-motion` và `:focus-visible` như design.md §2.2. Theme: ánh xạ biến Frappe v15 (design.md §2.3, tên biến đối chiếu `frappe/public/scss/common/css_variables.scss`) sang `var(--tc-*)`.
- [ ] Step 1: Test: `test_generated_css_matches_design` (`--tc-primary:#1F4E79`, `--tc-warn-fill:#B85A00`, `--tc-touch-min:48px`; khối STN có `--tc-fs-base:19px`), `test_every_var_reference_defined`, `test_committed_css_up_to_date` (`build()` == file đã commit).
- [ ] Step 2–4. Step 5: Commit `feat(ui): build_tokens.py sinh tokens.css và theme Desk từ tokens.json`.

### Task 11: Page `station` (UI), PWA `sw.js`/`manifest.json`, `vi.csv`

**Files:** Create `tracecore/ui/page/station/{__init__.py,station.json,station.js,station.css,station.html}`, `tracecore/www/sw.js`, `tracecore/www/sw.py`, `tracecore/www/manifest.json`, `tracecore/www/manifest.py`, `tracecore/translations/vi.csv`, `tracecore/tests/test_station_page.py`.

**Interfaces:**
- Consumes: `tracecore.v1.ping`, `tracecore.v1.set_unit.get` (Task 8).
- Page `station` (roles: System Manager, TC R01–R10): toàn màn hình (ẩn navbar/sidebar Desk khi ở trang), `data-surface="STN"`, zonebar 8 px màu theo `zone_type` (Dirty→`--tc-zone-dirty`, Clean→clean, Sterile→sterile, Department→dept, Waste→waste), tiêu đề trạm + tag tên khu bằng chữ, scan-box (input mono, `inputmode="none"`, `autocomplete="off"`, luôn focus lại sau mọi click/blur, Enter = quét, nút "Quét" ≥ 56 px), card kết quả `aria-live="polite"`.
- 4 trạng thái: **loading** (skeleton 3 dòng), **empty** ("Scan the Set ID on the set tag."), **error** (alert-error: tiêu đề đậm + lý do + hành động; nút "Retry" · "Switch to offline" · "Call R02"), **offline** (banner dưới zonebar "Offline — transactions are kept on this device" + card offline). Kết quả: card `res` với Set ID mono, badge trạng thái có chữ, loại bộ, phương pháp, "x/y chu trình", trạm hiện tại.
- Gọi RPC bằng `fetch` POST `/api/method/tracecore.v1.set_unit.get` với header `X-Frappe-CSRF-Token`, `X-Idempotency-Key` (`crypto.randomUUID()`, dùng lại khi Retry), `X-TC-Station`, body `{set_id, client_ts}` (ISO có offset); timeout 8 s → offline nếu lỗi mạng; ghi `performance.now()` lúc shell sẵn sàng vào `data-shell-ms` (đo R-07).
- SW: precache `/assets/tracecore/css/tokens.css`, `station`-scope network-first; đăng ký `navigator.serviceWorker.register("/sw.js", {scope: "/app/station"})`. Manifest: `start_url /app/station?station=TR-004`, `display fullscreen`, màu = `color.surface.page` / `color.primary.default`.
- vi.csv: mọi chuỗi `_()`/`__()` của app + nhãn DocType/field/option.
- [ ] Step 1: Test: `test_station_page_registered` (Page `station`, module UI, roles có `TC R04`), `test_service_worker_served` (render `/sw.js` có `CACHE_NAME`), `test_manifest_served` (JSON `start_url` bắt đầu `/app/station`), `test_vi_translations_cover_source_strings` (quét `_("…")`/`__("…")` trong `tracecore/**/*.py|js` → mỗi chuỗi có trong vi.csv), `test_vi_translation_examples` (`"Invalid code"` → `"Mã không hợp lệ"`).
- [ ] Step 2–4. Step 5: Commit `feat(ui): Page station kiosk 4 trạng thái, PWA shell, vi.csv`.

### Task 12: Station Agent `tracecore_agent`

**Files:** Create `tracecore_agent/{__init__,__main__,config,queue,printer,client,server,cli}.py`, `tracecore_agent/agent.ini.example`, `tracecore_agent/tests/{conftest,test_queue,test_printer,test_server,test_client,test_cli_hello}.py`, `deploy/systemd/tracecore-agent.service`.

**Interfaces (stdlib only, Python ≥ 3.10):**
- `config.load(path) -> AgentConfig` (dataclass: `server_url, api_key, api_secret, station, printer_host, printer_port=9100, output_dir, listen_host="127.0.0.1", listen_port=8765, db_path`); `printer_host` rỗng → chế độ File.
- `queue.PrintQueue(db_path)`: `enqueue(zpl, preview_png: bytes|None, print_job: str|None) -> str` (uuid), `claim_next() -> Job|None`, `mark_done(job_id, output_ref)`, `mark_failed(job_id, error)` (attempts += 1; ≥ 3 → `failed`, ngược lại `pending`), `depth() -> int`.
- `printer.send_tcp(host, port, zpl: str, timeout=5.0) -> None`; `printer.write_file(output_dir, job_id, zpl, preview_png) -> str` (ghi `<job>.zpl` + `<job>.png`, trả đường dẫn .zpl).
- `client.ServerClient(cfg)`: `call(method, **data) -> dict` (POST `/api/method/<method>`, header `Authorization: token key:secret`, `X-Idempotency-Key`, thêm `client_ts`), `heartbeat(queue_depth)`, `test_label()`, `ack(print_job, status, output_mode, output_ref=None, error=None)`.
- `server.make_server(cfg, queue) -> ThreadingHTTPServer`: `GET /health` → `{"status":"ok","station","queue_depth","printer_mode"}`; `POST /print` body `{"zpl", "preview_png_b64"?, "print_job"?}` → 202 `{"job_id"}`; khác → 404/400.
- `cli.main(argv) -> int`: `serve` (HTTP + vòng xử lý hàng đợi), `health`, `hello` (heartbeat → `v1.print.test_label` → enqueue → xử lý ngay → `v1.print.ack` → in `Print Job <name>: Printed (<mode>) <output_ref>`).
- [ ] Step 1: Test (pytest, `python -m pytest tracecore_agent`): `test_queue_retry_then_failed`, `test_send_tcp_delivers_bytes` (socket server cục bộ), `test_write_file_outputs_zpl_and_png`, `test_health_endpoint`, `test_print_endpoint_enqueues`, `test_client_sends_auth_and_idempotency_headers` (HTTP stub), `test_hello_file_mode_end_to_end` (stub trả test_label → file .zpl/.png được ghi, ack gửi `status=Printed`, `output_mode=File`).
- [ ] Step 2–4. Step 5: Commit `feat(agent): Station Agent tối giản /health /print hàng đợi SQLite`.

### Task 13: E2E Playwright smoke

**Files:** Create `tests_e2e/conftest.py`, `tests_e2e/test_station_smoke.py`, `tests_e2e/pytest.ini`.

**Interfaces:** env `TC_BASE_URL` (mặc định `http://127.0.0.1:8000`), `TC_E2E_USER`, `TC_E2E_PASSWORD`. Fixture `api` (requests.Session đăng nhập `/api/method/login`), fixture `test_set_unit` (tạo Instrument Set Type `E2E` + Set Unit qua REST, trả set_id). Viewport 1366×768.
- [ ] Step 1: Test: `test_scan_known_giai_shows_card_within_1s` (zonebar có class `tc-zone-clean`, input đang focus, gõ set_id + Enter → card chứa set_id hiện ≤ 1000 ms), `test_unknown_code_shows_vietnamese_error` (gõ `XYZ-123` → `alert-error` chứa "Mã không hợp lệ"), `test_offline_state` (`context.set_offline(True)` → quét → banner offline hiện), `test_missing_station_shows_error`.
- [ ] Step 2: Chạy trên dev site (`bench start`) → PASS (sau Task 11). Step 3: Commit `test(e2e): smoke kiosk station bằng Playwright`.

### Task 14: Lint nội bộ: BRU coverage, kiến trúc, pre-commit

**Files:** Create `scripts/check_bru_coverage.py`, `scripts/check_architecture.py`, `tracecore/tests/test_lint_scripts.py`; Modify `.pre-commit-config.yaml`, `pyproject.toml` (`[tool.bandit]`).

**Interfaces:**
- `check_bru_coverage.py`: `known_brus(srs_text) -> set[str]` (mở rộng dải `BRU-ID-001…006`, `BRU-WST-001..004`, cộng ID lẻ → 49 BRU), `markers(paths) -> dict[str, list[str]]`; exit 1 nếu marker trỏ BRU không tồn tại; `--strict` thêm exit 1 khi còn BRU chưa có test; luôn in "BRU covered x/49".
- `check_architecture.py`: R1 cấm `import/from tracecore.<Mx>` từ package M khác (M1–M10 = instrument, reprocessing, linen, hr, equipment, inventory, costing, par, admin_reports, waste); R2 cấm ghi `status` của Set Unit (`set_value("Set Unit"…status`, `db_set("status"` trong `instrument/doctype/set_unit`) ngoài `tracecore/core/step_gate.py`; R3 cấm string literal có ký tự tiếng Việt trong `.py` (bỏ docstring, chuỗi trong `_()`), `.js/.html` (bỏ comment, dòng có `__(`), loại trừ `translations/`, `tests/`, `test_*.py`, `tests_e2e/`.
- pre-commit thêm: bandit (`-c pyproject.toml`), local hooks `check-bru-coverage`, `check-architecture`, `build-tokens --check`.
- [ ] Step 1: Test: `test_known_brus_count_49`, `test_unknown_marker_fails`, `test_cross_module_import_detected`, `test_set_unit_status_write_detected`, `test_vietnamese_literal_detected_but_docstring_allowed`.
- [ ] Step 2–4; `pre-commit run --all-files` sạch. Step 5: Commit `chore(lint): check_bru_coverage, check_architecture, bandit trong pre-commit`.

### Task 15: CI, deploy scripts, tài liệu repo

**Files:** Create `.github/workflows/ci.yml`, `.github/actions/setup-bench/action.yml`, `.github/CODEOWNERS`, `CONTRIBUTING.md`, `deploy/pins.env`, `deploy/staging.env.example`, `deploy/site_config.json.example`, `scripts/install_dev.sh`, `scripts/install_prod.sh`, `scripts/restore.sh` (F-4/F-16, chỉ viết, có `--dry-run`); Modify `README.md`.

Ngoài phạm vi skeleton (ghi rõ trong PR): axe-core (F-14), JSON logger/Prometheus (F-15), ma trận quyền đầy đủ + 2FA + chính sách mật khẩu (FEAT-003), naming series của DocType chưa tạo (F-10), đo R-07 trên mini PC thật (chỉ đo được trên máy dev).

**Interfaces:**
- `deploy/pins.env`: `FRAPPE_REF=v15.123.1` (`d2efa796…`), `ERPNEXT_REF=v15.123.0` (`e864addb…`), `HRMS_REF=v15.64.5` (`e58e0c22…`), `PYTHON_VERSION=3.11`, `NODE_VERSION=18`.
- CI `ci.yml` (on PR + push main): job `lint` (pre-commit all files, `pip-audit .`, `python -m pytest tracecore_agent --cov`); job `test` (composite setup-bench: services mariadb:10.6 + redis:7, bench init theo pins, get-app erpnext/hrms/tracecore, new-site `test_site`, install; `run-tests --app tracecore --coverage`; đổi `<source>` coverage.xml về `$GITHUB_WORKSPACE`; `diff-cover coverage.xml agent-coverage.xml --compare-branch=origin/main --fail-under=70`); job `e2e` (setup-bench, `bench build`, `bench --site test_site serve --port 8000 &`, `playwright install --with-deps chromium`, `pytest tests_e2e`).
- `install_dev.sh`: idempotent; `bench init --frappe-branch $FRAPPE_REF`, get-app pinned, `new-site` (mật khẩu đọc từ env hoặc `~/.tracecore-dev-secrets`, không echo), install apps, developer_mode, `test_site` allow_tests.
- `install_prod.sh [--dry-run]`: idempotent (bỏ bước đã xong), `bench init`, get-app pinned, new-site, install, `setup production`, systemd agent; `--dry-run` chỉ in lệnh.
- [ ] Step 1: `bash -n` cả hai script; `shellcheck` nếu có; `install_prod.sh --dry-run` in đủ bước, không chạy gì. `check-yaml` cho workflow.
- [ ] Step 2: Commit `ci: GitHub Actions lint/test/e2e, script cài dev/prod, cấu hình mẫu`.

### Task 16: Xác minh Done when + PR

- [ ] `bench --site tracecore-dev.local uninstall-app tracecore --yes` rồi `install-app tracecore` (Done 1: sạch, `migrate` không lỗi).
- [ ] `bench --site test_site run-tests --app tracecore --coverage` xanh; `diff-cover` ≥ 70 %; `pre-commit run --all-files` sạch; `python -m pytest tracecore_agent` xanh.
- [ ] `bench start`; e2e Playwright xanh (Done 2).
- [ ] Provision agent TR-004 → `python3 -m tracecore_agent hello --config …` → Print Job `Printed` (File), mở `.png` kiểm bằng mắt, decode DataMatrix (Done 3).
- [ ] Audit Log: tạo/sửa Set Unit sinh log; DELETE REST bị từ chối (Done 4).
- [ ] `install_prod.sh --dry-run` (Done 6, phần viết).
- [ ] Push nhánh (cần người dùng cho phép), mở PR vào `main`, theo dõi CI (Done 5).
