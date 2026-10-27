# FEAT-009 — Offline outbox, dải mã cấp trước, Sync Conflict

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans (Native). Steps use checkbox (`- [ ]`).

**Goal:** Trạm T1, T4 và PDA T8 tiếp tục ghi nhận ≥ 4 giờ khi mất mạng, tự phát lại theo `client_ts` khi có mạng, xung
đột đưa R02 qua Sync Conflict + NC.

**Architecture:** Client: `tcOutbox` (IndexedDB) + `tcApi.call()` trong Page `station`; Service Worker precache shell và
cache snapshot đọc. Server: `core.code_range` (dải CY- offline), `core.sync` (Sync Conflict + NC), phát lại = gọi lại
đúng RPC gốc với cùng `X-Idempotency-Key` + header `X-TC-Replay: 1`; `station_session` kiểm phiên **tại `client_ts`**.

**Tech Stack:** Frappe v15, Python 3.11, JS thuần trong Page `station` (không Vue), IndexedDB, Service Worker,
WebCrypto RSA-OAEP, Playwright Python (`context.set_offline(True)`).

**Đầu vào:** implementation-plan §3 FEAT-009 (FR-M9-06, .1, .2, .3; FR-M2-07.11; FR-M1-06.4; NFR-AVAIL-02;
UC-33, UC-05/08/13 E3; SCR-33, SCR-34..37, offline indicator SCR-05..12), ADR-003, architecture §5.3 (Code Range,
Sync Conflict), §6.5. Amendment **A-40** (Task 1).

**Nhánh:** `feat/FEAT-009-offline-outbox` từ develop local (bench `~/benches/tracecore-f041`). Không PR; merge develop
local, không push.

## Quyết định đã chốt (người dùng 26/10/2026, ghi vào A-40)

- **Q1 Phạm vi:** luồng ghi offline = T1 tiếp nhận, T4 sinh Cycle ID, T8 xác nhận sử dụng. T2/T3/T5/T6/T7 vẫn chặn khi
  offline (giữ màn "Station offline"), dùng lại nền này ở FEAT sau.
- **Q2 Từ chối khi phát lại:** mọi 4xx nghiệp vụ (`ok: false` + `http_status` 404/409/422) và 403 → `Sync Conflict` +
  Incident NC loại `Sync Conflict`, giữ bản server, phát tiếp mục sau. 5xx / mạng → dừng, thử lại sau.
- **Q3 Phiên khi phát lại:** nhận nếu Station Session hợp lệ **tại `client_ts`**: đúng trạm, `started_at ≤ client_ts ≤
  absolute_expires_at`, và nếu đã đóng thì `ended_at ≥ client_ts` với `end_reason ≠ "Employee Disabled"`. Phiên còn
  mở thì `last_activity_at = max(last_activity_at, client_ts)` (không khóa Idle oan sau khi mạng về).
- **Q4 Code Range:** 200 mã/trạm/ngày, `CY-YYMMDD-T<NNN>-NNNN` (NNN = số của trạm `TR-NNN`), cấp khi online (đăng nhập
  thẻ và khi còn < 20 %), hết hiệu lực 00:00 ngày sau. Server nhận mã chỉ khi thuộc dải của đúng trạm, đúng ngày
  của `client_ts`, chưa dùng.

## Quyết định thiết kế của dev lead (ghi vào A-40, chờ duyệt)

- **D1 Nhãn T4 offline:** GS1/DataMatrix chỉ sinh tại server (CLAUDE.md), nên offline T4 giữ chỗ Cycle ID, màn hiện
  mã HRI + "Nhãn sẽ in khi có mạng"; Print Job tạo lúc phát lại.
- **D2 Mã bệnh nhân offline:** không lưu rõ trong IndexedDB. Snapshot T8 trả public key RSA-OAEP 2048 của site; PDA mã
  hóa `patient_code` → `patient_code_enc` (base64). Server giải mã bằng private key (TraceCore Settings, trường
  Password). Không có `crypto.subtle` (không secure context) → T8 offline chặn nhập, báo cần HTTPS.
- **D3 T1 offline gộp một lệnh:** phiếu nháp chưa có tên khi offline, nên T1 offline ghi một mục outbox
  `receive.submit_offline` chứa toàn bộ phiếu (người giao, các bộ, dòng xác nhận, ghi chú); ảnh bất thường không chụp
  offline.
- **D4 Kiểm offline chỉ theo snapshot** (ADR-003 Consequences): snapshot làm mới 10 phút khi online.
- **D5 `v1.sync.replay`** của implementation-plan hiện thực bằng header phát lại trên RPC gốc (ADR-003: "cùng
  X-Idempotency-Key"); module `tracecore.v1.sync` giữ `snapshot` và `status`.
- **D6 FR-M1-06.4:** `Step Gate Result.recorded_at` = giờ hệ thống của `client_ts` khi có; lịch sử Set Unit đã sắp theo
  `recorded_at` / `packed_at`.

## Global Constraints

- RPC `tracecore.v1.<domain>.<action>`; RPC ghi trạm `@idempotent`; `client_ts` ISO 8601 có offset.
- Chỉ `core.step_gate` đổi trạng thái Set Unit. Mã GS1/DataMatrix chỉ sinh ở server.
- Mọi chuỗi qua `_()` / `__()`, dịch ở `translations/vi.csv`. Chỉ token `--tc-*`; chữ ≥ 16 px, nút ≥ 48 px.
- Trạng thái offline không chỉ bằng màu: banner có chữ "Offline – n giao dịch chờ".
- Mỗi BRU/AC có test `@bru(...)` khi có BRU; test `FrappeTestCase` viết trước.
- DocType mới (Code Range, Sync Conflict) ở module `TraceCore`; không `delete` permission trên Sync Conflict.

## Review Focus

1. Cùng mục outbox phát lại hai lần (tab kiosk mở lại, SW + timer cùng chạy) → server trả response đã lưu, không tạo
   trùng Pack/Usage (Task 4 test `test_replay_twice_same_key`).
2. Mã offline trùng giữa hai trạm hoặc dùng mã của ngày hôm trước → từ chối `CODE_RANGE_INVALID` 409 thành Sync
   Conflict, không tạo Pack (Task 2/5).
3. Giao dịch offline lúc 23:30 phát lại 00:10 → Cycle ID và báo cáo theo ngày `client_ts` (NFR-L10N-01) (Task 5).
4. Phiên bị khóa vì nhân viên nghỉ việc trước `client_ts` → không nhận (Task 3 `test_replay_after_disable`).
5. Mã bệnh nhân không xuất hiện rõ trong Sync Conflict `client_state`, Audit Log hay error log (Task 6).

---

### Task 1: Amendment A-40 (docs)

**Files:** Modify `docs/architecture.md` (Revision History, ADR-003 bullet chốt 4xx, §5.3 Code Range / Sync Conflict
fields, §5.3.3 naming offline `CY-YYMMDD-T<NNN>-NNNN`), `docs/rtm.md` (FR-M9-06, FR-M2-07.11, FR-M1-06.4 → test files).

- [ ] Ghi A-40: Q1–Q4, D1–D6 ở trên, nguồn "người dùng chốt 26/10/2026; D1–D6 tạm, chờ chủ đầu tư".
- [ ] Commit `docs(architecture): Amendment A-40 offline FEAT-009`.

### Task 2: Code Range — DocType + `core.code_range` + `v1.code_range.allocate`

**Files:** Create `tracecore/tracecore/doctype/code_range/` (json, py, test), `tracecore/core/code_range.py`,
`tracecore/v1/code_range.py`, `tracecore/core/tests/test_code_range.py`. Modify `tracecore/core/gs1.py:63` (regex
`CY-\d{6}-(?:T\d{2,3}-)?\d{4}`).

**Interfaces (Produces):**
- DocType `Code Range` (autoname hash): `station` Link Zone Station, `prefix` Data (`CY-261026-T004-`), `range_date`
  Date, `from_no` Int, `to_no` Int, `issued_at` Datetime, `issued_to` Link Station Session, `expires_at` Datetime,
  child-free; uniqueness (station, range_date, from_no).
- `core.code_range.SIZE = 200`, `REFILL_RATIO = 0.2`.
- `allocate(station: str, on: date, session: str | None) -> dict` → `{"name", "prefix", "from_no", "to_no",
  "expires_at"}`; dải tiếp nối dải trước của cùng trạm/ngày (series `CY-YYMMDD-T<NNN>-` qua `getseries`, không chồng).
- `claim(code: str, station: str, on: date) -> None` — kiểm `code` thuộc dải của `station` ngày `on`, chưa có trong
  Code Registry; sai → `BlockedError(Block("CODE_RANGE_INVALID", ...))` 409 (thêm vào `core.errors.HTTP_STATUS`);
  đúng → `code_registry.register(code, "CY", "Pack", code, station)`.
- RPC `tracecore.v1.code_range.allocate(station, client_ts, token)` (`@station_session(*PACKING_ROLES)`,
  `@idempotent`) → `{"ok": true, "ranges": [...]}` trả mọi dải còn hạn của trạm hôm nay, cấp thêm nếu còn < 20 %.

- [ ] Test trước: `test_allocate_200_codes_station_prefix` (prefix `CY-261026-T004-`, to−from+1 = 200),
  `test_second_allocate_continues_series`, `test_claim_rejects_other_station`, `test_claim_rejects_other_day`,
  `test_claim_rejects_used_code`, `test_parse_scan_offline_cycle_id` (gs1), `test_allocate_refills_below_20_percent`.
- [ ] Chạy `bench --site test_f041 run-tests --module tracecore.core.tests.test_code_range` → FAIL.
- [ ] Hiện thực; chạy lại → PASS; `bench --site test_f041 migrate`.
- [ ] Commit `feat(core): Code Range cấp dải Cycle ID offline (FEAT-009, FR-M9-06.2)`.

### Task 3: Phát lại — phiên tại `client_ts` và Sync Conflict + NC

**Files:** Create `tracecore/tracecore/doctype/sync_conflict/` (json, py, js nút "Đã xử lý"), `tracecore/core/sync.py`,
`tracecore/core/tests/test_sync.py`. Modify `tracecore/core/station_auth.py` (thêm `as_replay_user`),
`tracecore/v1/_common.py:51-110` (`station_session`), `incident_capa.json` (thêm `Sync Conflict` vào `incident_type`),
`tracecore/reprocessing/incidents.py` (`on_sync_conflict`).

**Interfaces:**
- `REPLAY_HEADER = "X-TC-Replay"` trong `core.sync`; `is_replay() -> bool`.
- `station_auth.as_replay_user(token: str, station: str, client_ts: datetime)` context manager, quy tắc Q3; lỗi →
  `SESSION_INVALID` / `SESSION_EXPIRED` Block như hiện có.
- `station_session` khi `is_replay()`: dùng `as_replay_user`; sau khi `fn` trả `{"ok": False, "error"}` hoặc ném
  `frappe.PermissionError` → `core.sync.record_conflict(...)` rồi trả body như cũ (mã HTTP giữ nguyên).
- DocType `Sync Conflict` (naming `SC-.YYYY.-.#####`): `station`, `employee`, `user`, `endpoint`, `idempotency_key`
  (unique), `client_ts`, `synced_at`, `http_status` Int, `error_code`, `ref_doctype`, `ref_name` (Dynamic Link),
  `client_state` Code JSON (đã lọc `patient_code*`, `token`), `server_state` Code JSON, `status` Select Open/Resolved,
  `resolution_note`, `resolved_by`, `resolved_at`, `incident` Link Incident CAPA. Quyền: TC R02/R01 read+write, R10
  read; không ai create/delete trên Desk.
- `core.sync.record_conflict(endpoint, key, client_ts, args, error, http_status, ref_doctype, ref_name) -> str`
  idempotent theo `idempotency_key`; gọi `incidents.on_sync_conflict(name)` → `_auto("Sync Conflict", name,
  "Sync Conflict", "Medium", ...)`; gửi thông báo R02 (`_notify`).
- `core.sync.resolve(name, note)` (R02, `whitelist` qua `tracecore.v1.sync.resolve`).

- [ ] Test trước: `test_replay_accepts_session_valid_at_client_ts` (phiên đã Expired lúc phát lại),
  `test_replay_rejects_client_ts_before_session_start`, `test_replay_after_disable` (end_reason Employee Disabled trước
  client_ts → SESSION_INVALID), `test_replay_extends_last_activity`, `test_replay_rejection_creates_conflict_and_nc`
  (409 → Sync Conflict Open + Incident `Sync Conflict` auto), `test_conflict_once_per_key`,
  `test_client_state_redacts_patient_code_and_token`, `test_non_replay_rejection_creates_no_conflict`,
  `test_resolve_requires_r02_and_note`.
- [ ] FAIL → hiện thực → PASS; migrate.
- [ ] Commit `feat(core): phát lại offline theo client_ts, Sync Conflict + NC cho R02 (FR-M9-06.1/.3)`.

### Task 4: Snapshot đọc offline + `v1.sync.status`

**Files:** Create `tracecore/v1/sync.py`, `tracecore/v1/tests/test_sync_api.py`.

**Interfaces:**
- `tracecore.v1.sync.snapshot(station, client_ts, token)` (`@station_session` mọi role trạm, chỉ đọc) theo bước trạm:
  - T1: `{"sets": [{set_id, set_type, set_name, status, department, bom: [{instrument, name, qty}]}]}` — bộ ở trạng
    thái nhận được tại T1 (dùng `step_gate.check(set_unit, "T1")`), `departments`.
  - T4: `{"sets": [{set_id, set_name, method, bom, short_lines, par_blocked, maint_pending}], "pack_types": [{item,
    days}], "ci_batches": [{batch, method, expiry}], "ranges": [...]}` — bộ đã Đạt T3 chu trình hiện hành.
  - T8: `{"packs": [{cycle_id, set_name, status, expiry, department}], "patient_key": "<PEM public key>"}` — gói Đã cấp
    phát cho khoa của nhân viên.
  - Bước khác → `{"ok": true, "offline": false}`.
- `tracecore.v1.sync.status(station)` → `{"open_conflicts": int, "last_conflict": name|None}` cho chip R02.

- [ ] Test trước: `test_snapshot_t1_lists_receivable_sets`, `test_snapshot_t4_only_t3_passed_and_flags`,
  `test_snapshot_t8_only_department_issued_packs_and_key`, `test_snapshot_other_step_offline_false`,
  `test_snapshot_requires_session`.
- [ ] FAIL → hiện thực → PASS. Commit `feat(v1): snapshot đọc offline cho T1/T4/T8 (ADR-003)`.

### Task 5: Ghi offline phía server — T4, T1, T8

**Files:** Modify `tracecore/v1/pack.py:186` + `tracecore/reprocessing/packing.py:369`, `tracecore/v1/receive.py` +
`tracecore/reprocessing/receiving.py`, `tracecore/v1/usage.py:65` + `tracecore/reprocessing/usage.py:208`,
`tracecore/core/step_gate.py:268` (D6), `tracecore/core/crypto.py` (RSA). Tests trong `reprocessing/tests/`
`test_packing_offline.py`, `test_receiving_offline.py`, `test_usage_offline.py`, `core/tests/test_step_gate.py`.

**Interfaces:**
- `pack.generate_cycle_id(..., offline_cycle_id=None, ...)`: có `offline_cycle_id` → bỏ `check_skew` (chỉ chặn
  `client_ts` > giờ server + skew), `code_range.claim(offline_cycle_id, station, packed_at.date())` thay
  `next_cycle_id`; còn lại như online.
- `receive.submit_offline(station, receipt: dict, client_ts, token)` (`@station_session(*RECEIVE_ROLES)`,
  `@idempotent`); `receipt = {"deliverer_raw"|("department","deliverer_name"), "items": [{"set_id", "lines":
  [{"instrument","confirmed"}], "confirm_all", "note", "ack_incomplete"}]}` → chạy `open_receipt` → `scan_set`
  → `confirm_line(finalize=1)` → `submit` trong một savepoint với `client_ts` gốc, bỏ `check_skew`; lỗi bất kỳ bộ nào
  → hoàn tác cả phiếu, trả Block của bộ đó (thành Sync Conflict).
- `usage.confirm(..., patient_code_enc=None, ...)`: có `patient_code_enc` → `crypto.decrypt_patient_code(enc)`
  (RSA-OAEP SHA-256), không log; key pair sinh lần đầu `crypto.patient_key_pair()` lưu TraceCore Settings.
- `step_gate.record(..., client_ts=...)`: `recorded_at = to_system_time(client_ts)` nếu có; các nơi gọi trong T1/T4/T8
  truyền `client_ts`.

- [ ] Test trước: `test_offline_generate_uses_range_code` (Pack name = mã offline, Code Registry ghi),
  `test_offline_generate_hours_old_client_ts_ok`, `test_offline_generate_future_client_ts_rejected`,
  `test_offline_generate_code_other_day_conflict`, `test_offline_2330_synced_0010_keeps_day` (NFR-L10N-01),
  `test_replay_twice_same_key` (một Pack), `test_submit_offline_receipt_all_sets`,
  `test_submit_offline_rolls_back_on_one_bad_set`, `test_usage_confirm_encrypted_patient_code`,
  `test_usage_enc_not_in_audit_or_error_log`, `test_gate_recorded_at_uses_client_ts`.
- [ ] FAIL → hiện thực → PASS. Commit `feat(reprocessing): T1/T4/T8 nhận giao dịch offline (FR-M2-07.11, FR-M1-06.4)`.

### Task 6: Client — `tcOutbox`, `tcApi.call()`, Service Worker

**Files:** Create `tracecore/public/js/tc_outbox.js` (nối trước `station.js` qua hook `page_js`). Modify
`tracecore/ui/page/station/station.js` (banner, `rpc` → `tcApi.call`, nạp snapshot, cấp dải), `station.html`,
`station.css`, `tracecore/www/sw.js` (precache shell + `station_t*.js` + `tc_outbox.js`; cache snapshot GET),
`tracecore/hooks.py`.

**Interfaces:**
- `tcOutbox` (IndexedDB `tracecore`, store `outbox` keyPath `key`, index `client_ts`; store `snapshot` keyPath
  `station`; store `ranges` keyPath `prefix`):
  `put({key, endpoint, args, client_ts, station, attempts:0, state:"queued"})`, `list()` sắp theo `client_ts`,
  `remove(key)`, `markConflict(key, error)`, `count()`, `saveSnapshot(station, data)`, `snapshot(station)`,
  `nextCode(station, day)` (lấy mã kế từ dải, đánh dấu đã dùng), `rangeLeft(station, day)`.
- `tcApi.call(station, method, args, {queueable})`: online → `station.rpc` như cũ; lỗi mạng/timeout và
  `queueable` → `tcOutbox.put` và trả `{"ok": true, "queued": true, "key"}`. Mọi mục có sẵn `X-Idempotency-Key`,
  `client_ts` ban đầu.
- `tcApi.replay(station)`: tuần tự theo `client_ts`, header `X-TC-Replay: 1`, cùng key; 2xx → `remove`; `ok:false`
  4xx / 403 → `remove` + ghi nhật ký cục bộ "Xung đột – đã chuyển R02"; 5xx/mạng → dừng. Kích hoạt: sự kiện `online`,
  timer 15 s, sau đăng nhập. Khóa một lần chạy (`navigator.locks` nếu có, cờ nếu không).
- Banner foot rail: "Offline – {n} giao dịch chờ" / "Đang đồng bộ {i}/{n}" / "Đã đồng bộ"; nút "Hàng đợi" mở danh
  sách (thời gian, loại, trạng thái Chờ/Đang gửi/Xung đột).
- Snapshot làm mới khi đăng nhập và mỗi 10 phút online; `code_range.allocate` ở trạm T4 khi đăng nhập và khi
  `rangeLeft < 20 %`.

- [ ] Kiểm thủ công + e2e ở Task 8 (JS không có unit test framework trong repo). Lint `pre-commit run --all-files`.
- [ ] Commit `feat(ui): outbox IndexedDB và phát lại theo client_ts cho trạm (FEAT-009)`.

### Task 7: Màn T1, T4, T8 khi offline

**Files:** Modify `tracecore/public/js/station_t1.js`, `station_t4.js`, `station_t8.js`, `translations/vi.csv`.

- T1 offline: quét thẻ người giao (lưu raw, hiện "Xác minh khi đồng bộ") hoặc chọn khoa + tên; quét Set ID kiểm theo
  snapshot (không có → alert-error "Bộ không có trong dữ liệu offline"); BOM từ snapshot; Ghi sổ → một mục
  `tracecore.v1.receive.submit_offline` (D3). Ảnh bất thường ẩn khi offline.
- T4 offline: bộ trong snapshot T4; `par_blocked` / `maint_pending` → alert-error chặn (cần mạng); CI batch theo
  snapshot; Cycle ID = `tcOutbox.nextCode`; hết mã → alert-error "Hết dải mã offline"; kết quả hiện HRI mono + "Nhãn
  sẽ in khi có mạng" (D1); mục `tracecore.v1.pack.generate_cycle_id` có `offline_cycle_id`.
- T8 offline: quét gói theo snapshot (Đã dùng / Hết hạn / không có → alert-error theo FR-M2-18 với lý do "theo dữ liệu
  offline"); mã BN mã hóa bằng `patient_key` (D2) trước khi `put`; không có `crypto.subtle` → chặn nhập offline.
- T2/T3/T5/T6/T7 giữ màn chặn offline hiện có, sửa chữ "offline work comes with FEAT-009" thành "This station needs a
  network connection."
- [ ] Commit `feat(ui): T1/T4/T8 làm việc offline (UC-05/08/13 E3)`.

### Task 8: E2E offline + hoàn tất

**Files:** Create `tests_e2e/test_station_offline.py`.

- [ ] `test_t4_offline_pack_then_sync` (kiosk 1366×768): đăng nhập, `set_offline(True)`, đóng gói 2 bộ → banner "2
  giao dịch chờ", HRI dạng `CY-YYMMDD-T` ; `set_offline(False)` → banner "Đã đồng bộ", hai Pack có trên server.
- [ ] `test_t8_offline_usage_sync_and_conflict` (PDA 412×915): gói A hợp lệ, gói B bị thu hồi trên server khi PDA
  offline → sau sync A Đã dùng, B thành Sync Conflict Open + NC.
- [ ] `test_t1_offline_receipt_sync`.
- [ ] Full suite `bench --site test_f041 run-tests --app tracecore --coverage` (so lỗi có sẵn: 9 test_receipt_import +
  6 test_inventory_api), `diff-cover coverage.xml --compare-branch=develop --fail-under=70`, `pre-commit run
  --all-files`, e2e offline + smoke; migrate `tracecore-f041.local`; `bench build --app tracecore`.
- [ ] Merge `feat/FEAT-009-offline-outbox` vào develop local (không push); cập nhật memory tiến độ.

## Xong khi

Mọi test trên PASS, full suite không thêm lỗi so với develop, coverage changed-code ≥ 70 %, pre-commit sạch, e2e offline
PASS, A-40 ghi đủ.
