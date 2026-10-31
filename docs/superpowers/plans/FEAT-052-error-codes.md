# FEAT-052 Khung mã lỗi Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mã hóa các kiểm soát nghiệp vụ thành danh mục cấu hình được theo viện, hiển thị thống nhất, có Nhật ký lỗi và bản in HDSD.

**Architecture:** Danh mục nằm trên `Block` hiện có: `Block.code` giữ nguyên, thêm `error_code` tra từ danh mục. Service `tracecore/core/error_codes.py` quyết định mức độ, ghi Nhật ký và cấp phép tạm. Kiểm tra theo máy (HC-001/003) tính tại `equipment_block`, không ghi trạng thái máy.

**Tech Stack:** Frappe v15, Python 3.11, FrappeTestCase, Page `station`.

**Spec:** Amendment A-71 trong `docs/architecture.md`; FR-M9-17..21, FR-M5-07, FR-M4-03.1 trong `docs/srs.md`.

## Global Constraints

- Không đổi giá trị `Block.code` hiện có; JS và test cũ dựa vào nó.
- Mã khóa cứng: CT-001, CT-002, DC-002, QT-001, QT-002, HC-001, HC-003, TB-001, TB-003, TB-004, NS-001, NS-003. `check()` và Settings đều từ chối đổi.
- Cho phép tạm tối đa 24 giờ, có lý do, không tự duyệt cho mình.
- Chỉ `core.step_gate` đổi trạng thái Set Unit; chỉ `equipment.status.set_status` đổi `Equipment.status`.
- `core` không import M1–M10; đi qua hook.
- Chuỗi qua `_()`/`__()`, `translations/vi.csv`; test không so khớp chữ tiếng Việt; giao diện chỉ dùng token `--tc-*`; STN chữ ≥ 16 px, nút ≥ 48 px.
- Nhánh `feat/FEAT-052-error-codes` tạo từ `dlocal/develop`; không push, không PR; merge `--no-ff` vào develop local; không chạy E2E.

## Review Focus

1. Lỗi trên RPC ném `BlockedError` (Desk) hoặc GET: dòng Nhật ký vẫn còn sau khi request kết thúc. Test ở Task 1.3.
2. Phát lại offline cùng `X-Idempotency-Key`: không thêm dòng Nhật ký. Test ở Task 1.3.
3. Viện sửa hướng dẫn rồi chạy migrate: nội dung không bị ghi đè; mã mới vẫn được thêm. Test ở Task 1.1.
4. Máy Cảnh báo TB-002 qua nửa đêm: `lock_overdue` không khóa. Máy áp lực vẫn khóa theo TB-004. Test ở Task 3.1.
5. Giấy phép NS-001 hết hạn giữa phiên: phiên không kéo dài quá `valid_until`. Test ở Task 5.2.

---

### Task 0.1: Tài liệu A-71 (GĐ0)

**Files:** Modify `docs/architecture.md`, `docs/srs.md`, `docs/use-cases.md`, `docs/ux-foundations.md`, `docs/rtm.md`, `docs/implementation-plan.md`; Create `docs/superpowers/plans/FEAT-052-error-codes.md`.

- [ ] Ghi A-71 vào Revision History, §5.3 (4 + 1 DocType mới), ADR-003 (thêm `error_code`, `warnings`).
- [ ] SRS: thêm FR-M9 cho danh mục, Nhật ký, bản in; sửa FR-M4-03.1 và FR-M4-02.2 (ngoại lệ cho phép tạm NS-001); thêm FR-M5 cho lô theo máy.
- [ ] Commit `docs: amendment A-71 khung mã lỗi`.

### Task 1.1: Danh mục và seed

**Files:** Create `tracecore/tracecore/doctype/tracecore_error_code/`, `.../tracecore_error_code_station/`, `tracecore/setup/error_codes.json`; Modify `tracecore/setup/seed.py`, `hooks.py` (`after_migrate`); Test `tracecore/core/tests/test_error_codes.py`.

**Produces:** `seed.ensure_error_codes() -> None`.

- [ ] Test: `test_seed_has_all_required_codes` (đủ mã §2), `test_code_format_rejected` (`XX-1` lỗi), `test_seed_keeps_hospital_edits` (sửa `guide`, seed lại, giữ nguyên), `test_seed_adds_missing_code`. Thấy fail.
- [ ] Hiện thực DocType, JSON, seed. Chạy test pass. Commit.

### Task 1.2: Cấu hình trong TraceCore Settings

**Làm sau khi #1806 merge** vì cùng sửa Settings.

**Files:** Create `tracecore/tracecore/doctype/tracecore_error_rule/`; Modify `tracecore_settings.json`, `tracecore_settings.py`; Create `tracecore/core/error_codes.py`.

**Produces:** `rule_of(error_code) -> dict` gồm `enabled, severity, warn_days, approver_roles`, có cache, xóa khi lưu Settings.

- [ ] Test: `test_locked_code_rejects_severity_change`, `test_locked_code_rejects_disable`, `test_change_effective_without_restart`, `test_invalid_role_rejected`. Thấy fail.
- [ ] Hiện thực. Chạy test pass. Commit.

### Task 1.3: Nhật ký lỗi

**Files:** Create `tracecore/tracecore/doctype/tracecore_error_log/`; Modify `tracecore/core/error_codes.py`, `tracecore/v1/_common.py`.

**Produces:** `record(error_code, station, object_type, object_name, status="Open", client_ts=None) -> str`; `mark_resolved(error_code, object_type, object_name) -> int`.

- [ ] Test: `test_reject_writes_log`, `test_log_survives_blocked_error_rollback`, `test_log_survives_get_request`, `test_replay_same_key_no_second_row`, `test_delete_forbidden`, `test_input_error_not_logged`. Thấy fail.
- [ ] Hiện thực tại `reject_block`, `_live`, `_replay`, `run_at_step`. Chạy test pass. Commit.

### Task 1.4: Gán mã vào Block

**Files:** Modify `tracecore/core/errors.py`, `tracecore/core/error_codes.py`, `setup/error_codes.json`.

**Produces:** `catalog_of(block_code, context=None) -> dict | None`; `Block.as_dict()` thêm `error_code`, `error_name`, `object_label`, `guide_url` khi có mã.

- [ ] Test: `test_as_dict_keeps_old_keys`, `test_mapped_block_has_error_code`, `test_every_block_code_mapped_or_excluded` (quét `HTTP_STATUS` và mã trong code so với danh mục + danh sách loại trừ), `test_ct001_only_when_indicator_failed`. Thấy fail.
- [ ] Hiện thực. Chạy test `--app tracecore` để xác nhận không vỡ test cũ. Commit. **Merge GĐ1.**

### Task 2.1: Hiển thị thống nhất

**Files:** Create `tracecore/public/js/station_error.js`; Modify `ui/page/station/station.js`, 12 file `station_*.js` có `alertHtml`.

**Produces:** `tcErrorTitle(error) -> string` trả `[Mã] – Tên – đối tượng`, không có mã thì trả `error.title`.

- [ ] Test server cho payload của mỗi nhóm: `test_payload_hc001_has_machine_and_lot` và tương tự. Thấy fail rồi hiện thực phía server.
- [ ] Sửa các `alertHtml`, `renderError`. `bench build`, kiểm tay trên trạm T2 và T6. Commit.

### Task 2.2: Mở Hướng dẫn xử lý

**Files:** Create `tracecore/v1/error_code.py`; Modify `station_error.js`, `translations/vi.csv`.

**Produces:** RPC `tracecore.v1.error_code.guide(error_code) -> {code, name, guide_html}`.

- [ ] Test: `test_guide_html_sanitized` (bỏ `<script>`), `test_unknown_code_rejected`, `test_requires_session`. Thấy fail.
- [ ] Hiện thực; nút 1 chạm, panel inline, offline hiện trạng thái offline. Commit.

### Task 2.3: Báo cáo in danh mục theo trạm

**Files:** Create `tracecore/admin_reports/report/error_code_catalog/`.

- [ ] Test: `test_filter_by_station`, `test_filter_by_code`, `test_print_includes_guide`, `test_disabled_code_marked`. Thấy fail.
- [ ] Hiện thực Script Report + bản in. Commit. **Merge GĐ2.**

### Task 3.1: Mức độ cấu hình được (TB-002, DC-001)

**Files:** Modify `core/error_codes.py`, `equipment/daily_test.py`, `equipment/maintenance.py`, `reprocessing/assembly.py`, `reprocessing/packing.py`, `v1/_common.py`.

**Produces:** `check(error_code, block, object_type, object_name) -> Block | None`; response thêm `warnings: [{error_code, title, ...}]`.

- [ ] Test có `@bru("BRU-EQP-002")`: `test_tb002_warn_allows_load_and_logs`, `test_tb002_disabled_no_log`, `test_lock_overdue_skips_when_warn`, `test_pressure_inspection_always_blocked`, `test_unlock_cannot_bypass_tb004`. Test có `@bru("BRU-REP-003")`: `test_dc001_warn_allows_pack_and_prints_shortage`, `test_no_bom_still_blocked`. Thấy fail.
- [ ] Hiện thực. Chạy test pass. Commit.

### Task 3.2: Hiển thị cảnh báo trên trạm

**Files:** Modify `station_error.js`, các màn T2, T3, T4, T5.

- [ ] Test server: `test_warnings_in_response_keep_ok_true`. Thấy fail, hiện thực.
- [ ] Hiện cảnh báo inline dùng `--tc-warn-fill`, có chữ, không chặn thao tác; kiểm tay. Commit. **Merge GĐ3.**

### Task 4.1: Lô hóa chất theo máy (HC-001, HC-002, HC-003)

**Files:** Create `tracecore/equipment/doctype/equipment_chemical_lot/`, `tracecore/equipment/chemical_lots.py`, RPC `tracecore.v1.equipment.declare_chemical_lot`; Modify `equipment.json`, `equipment_type_norm.json` (cờ `requires_chemical_lot`), `equipment/daily_test.py`, `reprocessing/washing.py`, `public/js/station_t2.js`.

**Produces:** `chemical_block(equipment) -> Block | None`, gọi từ `equipment_block`.

- [ ] Test `@bru("BRU-INV-001")`: `test_expired_lot_blocks_with_machine_and_lot`, `test_unlock_temp_does_not_bypass_hc001`, `test_replace_lot_clears_block_and_resolves_log`, `test_no_declared_lot_blocks_when_flagged`, `test_type_not_flagged_unaffected`, `test_near_expiry_warns_with_n_days`, `test_status_stays_ready`, `test_batch_prefilled_from_machine_lot`. Thấy fail.
- [ ] Hiện thực; `.v1` có `@idempotent`. Migrate. Chạy test pass. Commit. **Merge GĐ4.**

### Task 5.1: NS-001, NS-002, NS-003 khi đăng nhập

**Files:** Modify `core/station_auth.py`, `v1/station.py`, `ui/page/station/station.js`.

- [ ] Test `@bru("BRU-HR-001")`: `test_unknown_card_stays_card_invalid`, `test_expired_cert_shows_ns001_with_cert_type`, `test_no_competency_shows_ns003`, `test_near_expiry_login_ok_with_warning`, `test_rejection_writes_error_log`. Thấy fail.
- [ ] Hiện thực; thẻ lạ/không hoạt động vẫn trả `CARD_INVALID`. Commit.

### Task 5.2: Cho phép tạm NS-001

**Files:** Modify `core/error_codes.py`, `core/station_auth.py`, `tracecore_error_log.js`; Create `tracecore/v1/error_code.py::grant_permit`.

**Produces:** `grant_permit(error_log, hours, reason) -> dict`; `active_permit(error_code, object_type, object_name) -> dict | None`.

- [ ] Test `@bru("BRU-HR-002")`: `test_r02_grants_and_login_passes`, `test_login_rejected_after_expiry`, `test_session_capped_at_valid_until`, `test_over_24h_rejected`, `test_self_approval_rejected`, `test_role_from_settings_respected`, `test_log_has_approver_and_until`, `test_permit_only_for_ns001`. Thấy fail.
- [ ] Hiện thực; duyệt từ dòng Nhật ký trên Desk. Commit. **Merge GĐ5.**

### Task 6.1: TB-001 và các mã còn lại

- [ ] Sau khi #1806 merge: test `test_tb001_payload_lists_missing_tests`, `test_unlock_still_bypasses_tb001`; gán mã theo bản `daily_test.py` mới. Commit.

### Task 6.2: Báo cáo thống kê

**Files:** Create `tracecore/admin_reports/report/error_log_statistics/`.

- [ ] Test: `test_group_by_code_station`, `test_date_filter`, `test_only_r01_r02_r10_can_read`. Thấy fail, hiện thực. Commit.

### Task 6.3: Nội dung và hoàn tất

- [ ] Viết bản nháp Hướng dẫn xử lý cho từng mã, ghi rõ là nháp chờ khoa KSNK duyệt; dịch `vi.csv`.
- [ ] Chạy `run-tests --app tracecore --coverage`, `diff-cover --fail-under=70`, `pre-commit run --all-files`; dán kết quả. Đối chiếu từng câu nghiệm thu của ticket. **Merge GĐ6.**
