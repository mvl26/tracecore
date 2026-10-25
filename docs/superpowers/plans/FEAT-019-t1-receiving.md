# FEAT-019 T1 Tiếp nhận — Implementation Plan

> **Cho agent thực thi:** dùng superpowers:executing-plans (làm tại chỗ, một session). Bước dùng checkbox `- [ ]`.

**Goal:** Màn T1 tiếp nhận nhiều bộ nối tiếp (quét thẻ người giao + Set ID, danh sách BOM có ảnh, xác nhận thành phần, ghi chú bất thường, ghi sổ phiếu) với `v1.receive.*`, ghim BOM và ghi cổng T1.

**Architecture:** DocType `Dirty Receipt` (+ child `Dirty Receipt Item`, `Dirty Receipt Confirm Line`) ở module Reprocessing; dịch vụ `tracecore/reprocessing/receiving.py` (M2) gọi `core.step_gate` (duy nhất đổi trạng thái Set Unit) và lấy BOM/ảnh qua hook mới `tracecore_receipt_context` do M1 khai báo (không import chéo). RPC mỏng `tracecore/v1/receive.py` theo khuôn `v1/wash.py` (`station_session` → `@idempotent` → `run_at_step`). UI: `public/js/station_t1.js` (class `T1Receiving`) nối sau `station.js` qua `page_js`.

**Tech Stack:** Frappe v15, Python 3.11, FrappeTestCase, Playwright for Python.

**Spec:** `docs/srs.md` FR-M2-01(.1–.7), FR-M2-02(.1–.2), FR-M2-23(.1–.7), FR-M2-25 (T1); `docs/use-cases.md` UC-05; `docs/ux-foundations.md` SCR-05/SCR-34; `docs/implementation-plan.md` dòng FEAT-019; amendment A-30..A-34 trong `docs/architecture.md`.

## Global Constraints

- Chỉ `core.step_gate` đổi trạng thái/vòng đời Set Unit (`start_cycle`, `record`); không `set_value('Set Unit', …)`.
- `start_cycle(set_unit, on=client_time.to_system_time(client_time.parse_client_ts(client_ts)))` — `on` là giờ hệ thống `Asia/Ho_Chi_Minh` không múi giờ.
- RPC `tracecore.v1.receive.<action>`; ghi dùng `@idempotent` + `X-Idempotency-Key`; `client_ts` ISO 8601 có offset; từ chối nghiệp vụ = `BlockedError` → `{"ok": false, "error": {...}}` + Audit `Reject`.
- Không import chéo M1–M10; M2 gọi M1 qua `core.extension.run`.
- Mọi chuỗi qua `_()`/`__()`, bản dịch `translations/vi.csv`; chỉ token `--tc-*`; chữ ≥ 16 px, nút ≥ 48 px (chính 56 px) trên STN/PDA; lỗi chặn là `alert-error` inline (kết quả → lý do → hành động); ô quét luôn trên cùng và focus; đủ 4 trạng thái loading/empty/error/offline.
- Dirty Receipt không xóa, không hủy chứng từ (như Wash Batch); số amendment dùng dải A-30..A-34.

## Review Focus

- Quét trùng một bộ trong phiếu (không thêm dòng, báo trùng) → Task 4.
- Mã quét tới khi kiosk đang chờ máy chủ (`busy`) bị bỏ mất / mất focus ô quét → Task 9 (hàng đợi mã quét).
- Bộ bị kiosk khác lấy mất giữa lúc quét và ghi sổ → ghi sổ bỏ bộ đó (rejected) thay vì kẹt phiếu → Task 6.
- Tiếp nhận 00:00–06:59 giờ Việt Nam phải ghim đúng phiên bản BOM theo giờ hệ thống → Task 6.
- Người giao không có thẻ / thẻ khóa / khoa trống → Task 3.

## Danh sách AC (suy ra từ SRS vì dòng FEAT không có EARS riêng)

| AC | EARS rút gọn | FR / BRU |
| --- | --- | --- |
| AC-01 | Khi quét thẻ người giao, hệ thống suy ra khoa từ thẻ, mở phiếu, ghi người nhận, trạm, giờ | FR-M2-01; BRU-REP-012 |
| AC-02 | Trong phiếu chỉ nhận mã bộ và mã thẻ; mã không tồn tại → "Mã không hợp lệ" + Audit | FR-M2-01.1, .5; BRU-ID-006 |
| AC-03 | Quét bộ kế tiếp không cần thao tác thêm; phiếu hiện số bộ đã nhận và số bộ có ghi chú | FR-M2-01.2 |
| AC-04 | Bộ quét trùng trong phiếu: cảnh báo, không thêm dòng | FR-M2-01.6 |
| AC-05 | Không có thẻ: chọn khoa + ghi tên tay, đánh dấu R02 cấp thẻ | FR-M2-01.7 |
| AC-06 | Chỉ nhận bộ `New`, `At Department`, `Awaiting Receipt`; khác → từ chối kèm lý do, trạm hiện tại, Audit | FR-M2-02, .1; BRU-FLOW-002/003 |
| AC-07 | R02 (PIN proof) + lý do tiếp nhận cưỡng bức; tạo NC qua hook | FR-M2-02.2 |
| AC-08 | Hiện BOM đúng phiên bản áp dụng, tên, số lượng, ảnh dụng cụ, ảnh bộ; thiếu ảnh → khung "Chưa có ảnh" | FR-M2-23, .7; FR-M1-01.6 |
| AC-09 | Xác nhận tất cả một chạm; ghi chú bất thường chỉ cần văn bản (+ ảnh tùy chọn), không lưu số lượng thực nhận | FR-M2-23.1, .2; BRU-REP-012 |
| AC-10 | Nhắc khi còn dòng chưa tick và không có ghi chú; sửa được tới khi ghi sổ | FR-M2-23.5, .6 |
| AC-11 | Ghi sổ: `start_cycle(on=giờ hệ thống)` ghim BOM, bộ → Chờ rửa (`Processing`), cổng T1 Đạt, cờ Cần xem xét nếu có ghi chú | FR-M2-01.4, FR-M2-23.3/.4, FR-M2-25; BRU-FLOW-004 |
| AC-12 | Cycle ID hiệu lực chưa dùng bị hủy với lý do Trả không sử dụng | FR-M2-01.3; BRU-REP-001, BRU-ID-003 |
| AC-13 | Mọi RPC ghi idempotent; replay không ghi hai lần | NFR-AVAIL-02 |
| AC-14 | UI STN 1366×768 và PDA 412×915: 4 trạng thái, ô quét trên cùng có focus, lỗi inline | FR-M9-14; SCR-05, SCR-34 |

## File Structure

- Create: `reprocessing/doctype/dirty_receipt{,_item,_confirm_line}/`, `reprocessing/receiving.py`, `v1/receive.py`, `public/js/station_t1.js`, tests tương ứng, `tests_e2e/test_station_t1.py`.
- Modify: `core/step_gate.py` (`STATION_STATUSES["T1"]`), `core/errors.py`, `instrument/bom.py` (+`receipt_context`), `reprocessing/packing.py` (+`void_returned_unused`), `hooks.py`, `v1/_common.py`, `ui/page/station/station.{js,css}`, `fixtures/permission_matrix.csv`, `fixtures/custom_docperm.json`, `translations/vi.csv`, `setup/devdata.py`, `scripts/e2e_prepare.sh`, `tests/test_e2e_prepare_guard.py`, `tests/factories.py`, `tests_e2e/conftest.py`, docs.

---

### Task 1: Amendment A-30..A-34 + nền step_gate/errors

**Files:** `docs/architecture.md`, `docs/rtm.md`, `core/step_gate.py`, `core/errors.py`, `core/tests/test_step_gate.py`, `core/tests/test_errors.py`.

**Interfaces:** Produces `step_gate.STATION_STATUSES["T1"] == ("New", "At Department", "Awaiting Receipt")`; mã lỗi mới ở `errors.HTTP_STATUS`: 404 `RECEIPT_NOT_FOUND`, `DELIVERER_NOT_FOUND`; 422 `DELIVERER_NO_DEPARTMENT`, `DELIVERER_NAME_REQUIRED`, `RECEIPT_EMPTY`, `CONFIRM_INCOMPLETE`, `PHOTO_INVALID`; 409 `RECEIPT_CLOSED`, `ITEM_NOT_CONFIRMED`, `FORCE_NOT_ALLOWED`.

- [ ] Ghi Revision History A-30..A-34 (FR/BRU/AC liên quan) trước khi code.
- [ ] Test (fail): `step_gate.check(set, "T1")` chặn `Sterile` với `STATUS_INVALID_FOR_STATION`, cho qua `New/At Department/Awaiting Receipt`; `test_errors` kiểm bảng mã mới.
- [ ] Cài đặt, chạy `test_step_gate`, `test_errors`; commit.

### Task 2: DocType Dirty Receipt + quyền

**Files:** 3 thư mục DocType, `fixtures/permission_matrix.csv` (dòng `DT-RECEIPT` đổi `Receipt` → `Dirty Receipt`), `fixtures/custom_docperm.json`, `hooks.py` (`doc_events` audit), test DocType.

**Interfaces:** `Dirty Receipt` (naming `RC-.YYYY.-.#####`, submittable): `department`, `deliverer`, `deliverer_name`, `needs_card`, `receiver`, `station`, `opened_at`, `received_at`, `abandoned`, `set_count`, `flagged_count`, `items`, `confirm_lines`. Cờ dịch vụ `doc.flags.tc_receiving`; trường dịch vụ bị khóa khi sửa từ Desk; `before_cancel` ném lỗi; không xóa.

- [ ] Test (fail): không tạo được khi thiếu cờ; không hủy/xóa; quyền khớp ma trận (`assert_permission_matrix`).
- [ ] Cài đặt DocType, regenerate fixture bằng `write_fixture`, `bench migrate`; test pass; commit.

### Task 3: Hook BOM T1 + mở phiếu (thẻ / nhập tay / tiếp tục / hủy)

**Files:** `instrument/bom.py` (`receipt_context(ctx) -> dict`), `hooks.py` (`tracecore_receipt_context`), `reprocessing/receiving.py`, `reprocessing/tests/test_receiving_open.py`, `instrument/tests/test_receipt_context.py`.

**Interfaces:** `receipt_context({"set_unit","set_type","on"}) -> {"bom_version", "bom": [line], "tray_images": [url]}`; `receiving.open_receipt(raw, station, employee, user, client_ts, department=None, deliverer_name=None) -> dict`, `receiving.resume(station, employee) -> dict | None`, `receiving.discard(receipt, station, employee)`.

- [ ] Test (fail): thẻ hợp lệ → khoa của Employee (AC-01, `BRU-REP-012`); mã lạ → `SCAN_INVALID` (AC-02, `BRU-ID-006`); thẻ khóa/không có → `DELIVERER_NOT_FOUND`; Employee không khoa → `DELIVERER_NO_DEPARTMENT`; nhập tay thiếu tên → `DELIVERER_NAME_REQUIRED`, đủ → `needs_card=1` (AC-05); `resume` trả phiếu nháp gần nhất; mở thẻ mới hủy nháp cũ cùng người/trạm.
- [ ] Cài đặt; pass; commit.

### Task 4: scan_set (kiểm trạng thái, trùng, BOM, cưỡng bức)

**Files:** `receiving.py`, `reprocessing/tests/test_receiving_scan.py`.

**Interfaces:** `receiving.scan_set(receipt, raw, station, client_ts, force_reason=None, session=None, reviewer_proof=None) -> {"item": item, "duplicate": bool, "receipt": summary}`; hook sau cưỡng bức `tracecore_after_force_receive` (rỗng).

- [ ] Test (fail): bộ `New`/`At Department`/`Awaiting Receipt` được nhận; `Sterile` bị `STATUS_INVALID_FOR_STATION` có trạm hiện tại (AC-06, `BRU-FLOW-002`, `BRU-FLOW-003`); trùng → `duplicate=True` không thêm dòng (AC-04); mã thẻ khi đã có người giao / mã khác loại → `SCAN_INVALID`; BOM trả đúng phiên bản theo `on` giờ hệ thống; cưỡng bức cần R02 + proof + lý do (`REASON_REQUIRED`, `R02_CONFIRM_REQUIRED`), `Disposed`/`End of Life` → `FORCE_NOT_ALLOWED` (AC-07).
- [ ] Cài đặt; pass; commit.

### Task 5: confirm_line + attach_photo

**Files:** `receiving.py`, `reprocessing/tests/test_receiving_confirm.py`.

**Interfaces:** `receiving.confirm_line(receipt, set_id, station, lines=None, confirm_all=False, note=None, finalize=False, ack_incomplete=False) -> item`; `receiving.attach_photo(receipt, set_id, station, file_name, content_base64) -> item` (JPEG/PNG/WebP ≤ 5 MiB, kiểm nội dung; sai → `PHOTO_INVALID`).

- [ ] Test (fail): `confirm_all` đánh dấu mọi dòng (AC-09); ghi chú không lưu số lượng thực nhận; `finalize` khi còn dòng chưa tick và không ghi chú → `CONFIRM_INCOMPLETE` trừ khi `ack_incomplete` (AC-10); sửa lại được khi chưa ghi sổ; phiếu đã đóng → `RECEIPT_CLOSED`.
- [ ] Cài đặt; pass; commit.

### Task 6: submit (ghim BOM, cổng T1, hủy Cycle ID)

**Files:** `receiving.py`, `reprocessing/packing.py` (`void_returned_unused(cycle_id, note) -> None`), `reprocessing/tests/test_receiving_submit.py`.

**Interfaces:** `receiving.submit(receipt, station, client_ts) -> {"receipt", "sets", "flagged", "rejected": [{set_id, code, reason}]}`; dùng `step_gate.start_cycle(set, on=to_system_time(item.received_at UTC), client_ts=…)` rồi `step_gate.record(set, "T1", "Pass", "Dirty Receipt", receipt, station, client_ts)`.

- [ ] Test (fail): bộ → `Processing`, `current_cycle_no+1`, `Step Gate Result` T1 `Pass` (AC-11, `BRU-FLOW-004`); `client_ts` 2026-10-23T23:30:00Z (06:30 giờ VN hôm sau) ghim phiên bản hiệu lực ngày VN; bộ có ghi chú → `needs_review`; chưa finalize → `ITEM_NOT_CONFIRMED`; bộ bị lấy giữa chừng → vào `rejected`, còn lại vẫn ghi; rỗng → `RECEIPT_EMPTY`; Pack `Issued` chưa dùng → `Void`/`Returned Unused`, mã `Disabled` (AC-12, `BRU-REP-001`, `BRU-ID-003`); lỗi giữa chừng hoàn tác savepoint.
- [ ] Cài đặt; pass; commit.

### Task 7: RPC `v1.receive.*`

**Files:** `v1/receive.py`, `v1/_common.py` (`RECEIVE_ROLES = ("TC R03","TC R02","System Manager")`), `v1/tests/test_receive_api.py`.

**Interfaces:** `open(station, raw=None, department=None, deliverer_name=None, restart=False, client_ts=None, token=None)`, `scan_set(receipt, raw, station, force_reason=None, reviewer_proof=None, …)`, `confirm_line(receipt, set_id, station, lines=None, confirm_all=0, note=None, finalize=0, ack_incomplete=0, …)`, `submit(receipt, station, …)`, `discard(receipt, station, …)`, `attach_photo(receipt, set_id, file_name, content, station, …)`.

- [ ] Test (fail): phiên trạm đúng trạm T1 (sai bước → `STATION_WRONG_STEP`), vai trò, mã HTTP theo `Block`, replay idempotent không ghi hai lần (AC-13), tham số sai → 400, Audit `Reject` khi mã lạ.
- [ ] Cài đặt; pass; commit.

### Task 8: Dữ liệu demo + e2e_prepare

**Files:** `setup/devdata.py` (`ensure_t1_e2e_user`, `ensure_t1_demo`), `tests/factories.py` (`make_employee(card, department)`), `scripts/e2e_prepare.sh`, `tests/test_e2e_prepare_guard.py`, `tests/test_devdata.py`.

**Interfaces:** `ensure_t1_demo() -> {"deliverer_card","department","sets","set_sterile","set_unknown_card?","set_dept"}` idempotent.

- [ ] Test (fail) trên devdata + bench giả của guard (thêm nhánh `ensure_t1_*`); cài đặt; pass; commit.

### Task 9: UI `station_t1.js`

**Files:** `public/js/station_t1.js`, `ui/page/station/station.js` (chọn `T1Receiving` khi `station.step === "T1"`, `tracecore.v1.receive.` mang token), `station.css`, `hooks.py` `page_js`, `translations/vi.csv`, `tests/test_station_page.py`.

- [ ] Test (fail) tĩnh: script có trong `page_js`, `station.js` chứa `T1Receiving` và `tracecore.v1.receive.`, `clearSession() {`, hàng đợi mã quét; `test_vi_translations_cover_source_strings` pass.
- [ ] Cài đặt UI: pha 1 quét thẻ (hoặc nút "Người giao không có thẻ"), pha 2 quét nhiều bộ + BOM có ảnh + Xác nhận tất cả + ghi chú + chụp ảnh + Xác nhận bộ, nút Ghi sổ phiếu; hàng đợi mã quét khi `busy`; `station.focus(true)` sau mỗi thao tác; cưỡng bức R02 (lý do + PIN); `npx eslint`/prettier sạch.

### Task 10: E2E Playwright

**Files:** `tests_e2e/test_station_t1.py`, `tests_e2e/conftest.py` (`t1_demo`, `t1_page`, `t1_pda_page`).

- [ ] Test luồng STN: quét thẻ người giao → quét nhiều Set ID liên tiếp → Xác nhận tất cả → ghi chú bất thường ở một bộ → Ghi sổ; kiểm trạng thái Set Unit qua API; test PDA 412×915 không tràn ngang, ô quét trên cùng có focus; chạy `scripts/e2e_prepare.sh` ngay trước, chạy cả file đúng thứ tự.

### Task 11: Xác minh và tài liệu

- [ ] `docs/rtm.md` (FEAT-019 → test), `run-tests` toàn app, coverage + `diff-cover`, `pre-commit run --all-files`, sinh lại fixture quyền, bảng AC → bằng chứng trong báo cáo.
