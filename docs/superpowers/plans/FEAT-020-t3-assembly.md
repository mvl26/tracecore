# FEAT-020 T3 Kiểm tra – lắp ráp theo BOM — Implementation Plan

> **Nhánh:** `feat/FEAT-020-t3-assembly` (từ `origin/feat/FEAT-016-set-id-batch`). **Bench:** `~/benches/tracecore-f041`, site dev `tracecore-f041.local` (cổng 8300), site test `test_f041`. **Amendment:** A-35.

**Goal:** R04 quét Set ID ở trạm T3 (SCR-07, STN 1366×768) thấy BOM phiên bản áp dụng kèm ảnh từng dụng cụ và ảnh bộ đã xếp, tick/nhập số lượng thực tế từng dòng (hoặc quét mã GIAI dụng cụ để tự tick), ghi hỏng/thay từ kho dự phòng, đính ảnh; dòng thiếu chưa có R02 xác nhận (thẻ + PIN + lý do) thì cổng T3 không Đạt nên Đóng gói (T4) bị khóa; R02 xác nhận thì mở khóa và nhãn T4 in dòng THIẾU; bộ hỏng nặng rẽ nhánh Sửa chữa/Thanh lý; cảnh báo cam theo Par Level (chỉ đọc); thiếu thì đánh cờ NC chờ Incident CAPA (FEAT-030). Cổng T3 vẫn chỉ do `core.step_gate` ghi (ADR-005).

**Architecture:** M2 `reprocessing` thêm `assembly.py` (dịch vụ: `open`, `line`, `confirm_shortage`, `submit`) và thay stub DocType `Assembly Record` bằng chứng từ đầy đủ với child `Assembly Line`. RPC `tracecore.v1.assembly.*` (`@station_session` → `@idempotent`) bọc dịch vụ, theo khuôn `v1.pack`/`v1.wash`. M2 không import M1/M8: BOM, ảnh, cơ số lấy qua hook mới `tracecore_assembly_context` (M1 `bom.pack_context`, M8 `par.check.pack_context`); mã dụng cụ GIAI đọc `Instrument` theo tên DocType. Màn trạm `station_t3.js` (`T3Assembly`) cùng khuôn `T6Storage`/`T2Wash`.

**FR/BRU/AC:** FR-M2-05, .1, .2, .3, .4; FR-M2-06, .1, .2, .3; FR-M2-00.5; FR-M2-25 (cổng T3, thay stub FEAT-018); FR-M1-02.2, FR-M1-02.4 (A-06 I17); FR-M1-01.6 (ảnh tại T3). BRU-FLOW-002 (chặn ngược chiều), BRU-FLOW-003 (ngoại lệ rẽ nhánh), BRU-FLOW-004 (cổng), BRU-REP-003 (thiếu cần R02 PIN), BRU-PAR-003 (cảnh báo sớm). `implementation-plan.md` §3 không có AC EARS cho FEAT-020: AC = mệnh đề EARS của FR và luồng UC-07 (bảng AC ở cuối file).

## Quyết định thiết kế (Amendment A-35; mã T1–T14)

| Mã | Trạng thái | Quyết định |
| --- | --- | --- |
| T1 | [Xác nhận] | **Thay stub, giữ tương thích.** `Assembly Record` giữ `set_unit`, `cycle_no`, `result` (`Pass`/`Fail`), `notes`, tên `AS-.YYYY.-.#####`, submittable, không hủy/xóa; thêm trường kiểm đếm và child `Assembly Line` (`lines`). T4 (`packing._assembly`), `Pack.assembly`, `step_gate`, `par.check` không đổi giao diện. Stub cũ ghi sổ không có dòng vẫn hợp lệ **chỉ khi** chu trình không ghim BOM có dòng (dữ liệu có trước FEAT-020). |
| T2 | [Xác nhận] | **Bản nháp là phiên kiểm đếm.** `assembly.open` tạo (hoặc mở lại) bản nháp `docstatus 0` cho (bộ, chu trình hiện hành) với đủ dòng BOM chưa đếm; mọi thao tác dòng ghi vào bản nháp; `submit` ghi sổ. Nhờ vậy R02 đổi thẻ ở trạm (PIN) không làm mất việc đếm. Một bản nháp mỗi (bộ, chu trình). |
| T3 | [Xác nhận] | **Dòng kiểm đếm.** `Assembly Line`: `instrument`, `instrument_name`, `bom_qty`, `counted` (đã tick/nhập), `actual_qty` (số dụng cụ dùng được trong khay sau khi thay), `damaged_qty`, `replaced_qty` ≤ `damaged_qty`, `replacement_instrument` (Link Instrument, mặc định cùng mã), `disposition` (`Repair`/`Dispose`, bắt buộc khi `damaged_qty` > 0), `line_status` (`Enough`/`Short`/`Over`, server tính: FR-M2-05.1), `missing_qty`, `photo`, `note`. Mọi số do server tính lại, không tin client. |
| T4 | [Xác nhận] | **Thiếu → cổng T3 không Đạt.** Dòng `Short` mà chưa R02 xác nhận: `submit` bị từ chối `SHORTAGE_UNCONFIRMED` (409), nên cổng T3 vẫn Chưa và T4 từ chối `GATE_PREV_NOT_PASSED` (FR-M2-06 khóa Đóng gói bằng chính cổng, không thêm cờ). R02 xác nhận (`confirm_shortage`) rồi `submit` → T3 Đạt, T4 mở. |
| T5 | [Tạm — chờ chủ đầu tư] | **Xác nhận thiếu bằng phiên R02.** `confirm_shortage` chạy dưới phiên thẻ của R02 (role `TC R02`/System Manager) tại trạm T3 và tiêu thụ PIN proof (`station.verify_pin` → `consume_session_pin_proof`), như FEAT-021 Q7; kèm lý do 1–500 ký tự. Sai PIN 3 lần khóa 5 phút do `station_auth.verify_pin` (FR-M2-06.3, FEAT-003). R02 cần Station Competency ở trạm T3. |
| T6 | [Tạm — chờ chủ đầu tư] | **NC khi thiếu / dụng cụ lạ.** `Incident CAPA` chưa có (FEAT-030). Theo khuôn FEAT-021 Q22: cờ `nc_pending` trên bản nháp (đặt khi bản nháp có dòng thiếu hoặc dụng cụ lạ, bỏ khi hết), Audit Log `AssemblyShortage`/`AssemblyForeignInstrument`, hook `tracecore_assembly_nc` (ctx `{assembly, set_unit, kind, items}`) cho FEAT-030 tạo Incident thật. FR-M2-06.2 đạt một phần tới FEAT-030. |
| T7 | [Xác nhận] | **Rẽ nhánh hỏng nặng (FR-M2-00.5).** `submit(branch=Repair\|Disposal, branch_reason)`: kết quả `Fail` → `step_gate.record(T3, Fail)` (bộ sang Xử lý lại, các cổng sau về Chưa); `branch` + lý do lưu trên chứng từ; Audit `AssemblyBranch`; hook `tracecore_after_assembly` mang `branch`. Set Unit **không** có trạng thái Sửa chữa/Thanh lý và thao tác Thanh lý chưa được FEAT-032 chốt (A-13 G14): FEAT-020 không đổi `Set Unit.status` ngoài cổng, không gọi `dispose`. **Còn mở** — nêu trong báo cáo. |
| T8 | [Xác nhận] | **Cơ số chỉ đọc.** Ngữ cảnh T3 có `par` (`par.check.evaluate`) và từng dòng BOM kèm trạng thái `warn`/`blocked` của dụng cụ; T3 chỉ cảnh báo cam, không chặn (T4 chặn, FEAT-032). |
| T9 | [Xác nhận] | **Quét mã dụng cụ (FR-M1-02.2/.4).** Cờ `TraceCore Settings.enable_instrument_giai` tắt → ô quét từ chối mã dụng cụ `FEATURE_DISABLED` (409). Bật: mã GIAI thuộc dụng cụ trong BOM → dòng đó `counted`, `actual_qty` +1 (không vượt `bom_qty`; quét thừa báo cảnh báo); mã không thuộc BOM → **cảnh báo Dụng cụ lạ** (ok, không chặn), ghi `foreign_instruments`, `nc_pending`, hook NC. |
| T10 | [Xác nhận] | **Ghi chú bất thường từ tiếp nhận (FR-M2-05).** `Dirty Receipt` chưa có (FEAT-019). Ngữ cảnh có khóa `receipt_notes` (list) do hook `tracecore_assembly_context` đóng góp; FEAT-020 trả list rỗng. Đạt một phần tới FEAT-019. |
| T11 | [Xác nhận] | **Kho dự phòng.** Thay thế chỉ ghi mã dụng cụ thay (`replacement_instrument`, `replaced_qty`); không trừ kho/không tạo Stock Entry (không FR nào định nghĩa kho dự phòng; để FEAT-042). |
| T12 | [Xác nhận] | **Nhãn THIẾU (FR-M2-06.1) và T4.** `pack_label.label_context` đặt `warning` = `THIẾU: <tên dụng cụ>` khi chứng từ T3 của gói có thiếu đã xác nhận (mẫu nhãn đã có ô `warning`). `packing.generate`/`get_context` không yêu cầu tick các dòng đã được R02 xác nhận thiếu; `Pack.instruments_confirmed` không ghi dòng đó. T4 JS hiển thị dòng đó "Thiếu – R02 đã xác nhận". |
| T13 | [Xác nhận] | **Phiên và quyền.** RPC `assembly.open/line/submit`: `TC R04`, `TC R02`, System Manager; `confirm_shortage`: `TC R02`, System Manager. Tất cả chạy ở trạm bước T3 (`run_at_step`). Quyền DocType Assembly Record giữ ma trận hiện có (không đổi `custom_docperm.json`). |
| T14 | [Xác nhận] | **Mã HTTP mới** (`core.errors.HTTP_STATUS`): 422 `LINES_NOT_COUNTED`, `QTY_INVALID`, `BRANCH_INVALID`, `PHOTO_INVALID`; 404 `ASSEMBLY_NOT_FOUND`; 409 `SHORTAGE_UNCONFIRMED`, `NO_SHORTAGE`, `ASSEMBLY_CLOSED`. Tái dùng `SCAN_INVALID`, `SET_NOT_FOUND`, `STATION_WRONG_STEP`, `STATUS_INVALID_FOR_STATION`, `GATE_PREV_NOT_PASSED`, `STEP_ALREADY_PASSED`, `BOM_INCOMPLETE`, `REASON_REQUIRED`, `R02_CONFIRM_REQUIRED`, `FEATURE_DISABLED`, `INSTRUMENT_NOT_FOUND`. |

**Ngoài phạm vi:** NC/Incident CAPA thật (FEAT-030); thanh lý thật và duyệt (FEAT-032); Dirty Receipt (FEAT-019); trừ kho dự phòng (FEAT-042); in phiếu kiểm đếm theo số liệu thực tế (phiếu PDF theo BOM của FEAT-015 giữ nguyên); offline (FEAT-009); PDA.

## Cấu trúc file

- Tạo: `reprocessing/doctype/assembly_line/{__init__.py,assembly_line.json,assembly_line.py}`, `reprocessing/assembly.py`, `v1/assembly.py`, `public/js/station_t3.js`, tests `reprocessing/tests/test_assembly.py`, `v1/tests/test_assembly_api.py`, `tests_e2e/test_station_t3.py`.
- Sửa: `assembly_record.{json,py}` + test, `core/step_gate.py` (`STATION_STATUSES["T3"]`), `core/errors.py` (+ test), `hooks.py` (hook mới, `page_js`), `reprocessing/packing.py` + `pack_label.py` (T12), `public/js/station_t4.js` (dòng thiếu đã xác nhận), `ui/page/station/station.{js,css}`, `tests/factories.py` (`make_assembly_record` dựng dòng từ BOM), `setup/devdata.py`, `scripts/e2e_prepare.sh`, `tests/test_e2e_prepare_guard.py`, `tests_e2e/conftest.py`, `translations/vi.csv`, `docs/{architecture,implementation-plan,rtm}.md`.

## Tasks

### Task 1: Tài liệu — amendment A-35 và kế hoạch
- Ghi A-35 (Revision History, §5.3.1 dòng Assembly Record) trước khi code. FR/AC: toàn bộ. Commit `docs(assembly): kế hoạch FEAT-020 và amendment A-35`.

### Task 2: `Assembly Line` và `Assembly Record` đầy đủ
- FR/BRU/AC: FR-M2-05.1 (AC-2), FR-M2-05.2 (AC-3), FR-M2-06 (AC-6), BRU-REP-003, BRU-FLOW-004.
- Test trước (`test_assembly_record.py`): tên/chu trình như stub (giữ); `test_line_status_enough_short_over`; `test_replaced_cannot_exceed_damaged`; `test_damaged_line_needs_disposition`; `test_lines_must_match_pinned_bom` (thiếu/thừa/trùng dòng); `@bru("BRU-REP-003") test_pass_blocked_with_unconfirmed_shortage`; `test_shortage_confirmation_cannot_be_set_by_hand` (cờ `tc_assembly`); `@bru("BRU-FLOW-004") test_submit_records_t3_with_station_and_client_ts`; `test_legacy_record_without_lines_allowed_when_bom_not_pinned`; quyền R04 tạo/ghi/ghi sổ (giữ).
- Hiện thực JSON + controller; `make_assembly_record` (factory) dựng dòng đủ từ BOM. PASS toàn bộ test T4 cũ. Commit `feat(reprocessing): chứng từ lắp ráp T3 đầy đủ với dòng kiểm đếm theo BOM`.

### Task 3: Dịch vụ `assembly` và cổng T3
- FR/BRU/AC: FR-M2-05 (AC-1), .3 (AC-4), .4 (AC-5), FR-M2-06 (AC-6), .1 (AC-7), .2 (AC-8), .3 (AC-9), FR-M2-00.5 (AC-10), FR-M2-25 (AC-11), FR-M1-02.2/.4 (AC-12, AC-13); BRU-FLOW-002/003/004, BRU-REP-003, BRU-PAR-003.
- Test trước (`test_assembly.py`): mở (BOM+ảnh+par+cổng; T2 chưa Đạt → `GATE_PREV_NOT_PASSED`; bộ đã T3 Đạt → `STEP_ALREADY_PASSED`; trạm sai; không BOM → `BOM_INCOMPLETE`; mở lại cùng bản nháp), `line` (nhập số lượng, hỏng+thay, `QTY_INVALID`, quét GIAI tick/không BOM/cờ tắt, `all_ok`), thiếu → cờ NC + hook một lần, `confirm_shortage` (không thiếu → `NO_SHORTAGE`, thiếu lý do, không PIN proof → `R02_CONFIRM_REQUIRED`, proof không phải R02, đúng → mở khóa), `submit` (chưa đếm hết → `LINES_NOT_COUNTED`, thiếu chưa xác nhận → `SHORTAGE_UNCONFIRMED`, đủ → T3 Đạt và T4 mở, rẽ nhánh → T3 Không đạt + Set `Reprocess`, hoàn tác nguyên vẹn khi lỗi), đồng thời hai bản nháp.
- Hiện thực `assembly.py` + `STATION_STATUSES["T3"]` + hook mới. Commit `feat(reprocessing): dịch vụ kiểm đếm T3 (mở, ghi dòng, xác nhận thiếu, ghi sổ)`.

### Task 4: RPC `tracecore.v1.assembly.*`
- FR/AC: AC-14 (idempotent, `client_ts`), AC-6/7/9 qua RPC. Test trước (`test_assembly_api.py`): phiên thẻ, quyền (R04 không `confirm_shortage`), mã HTTP, replay cùng khóa không nhân đôi, định dạng tham số 400, Audit `Reject`. `core.errors` + test bảng mã. Commit `feat(v1): RPC assembly.open/line/confirm_shortage/submit`.

### Task 5: T4 tương thích (thiếu đã xác nhận) và nhãn THIẾU
- FR/AC: FR-M2-06.1 (AC-7). Test trước trong `test_packing.py`/`test_pack_api.py`: bộ có thiếu đã xác nhận đóng gói được không cần tick dòng thiếu; `Pack.instruments_confirmed` không chứa dòng thiếu; nhãn `warning` = `THIẾU: …`; bộ thiếu chưa xác nhận → `GATE_PREV_NOT_PASSED`. Commit `feat(reprocessing): T4 chấp nhận dòng thiếu đã R02 xác nhận và in dòng THIẾU`.

### Task 6: Màn trạm T3 (SCR-07)
- FR/AC: AC-1..AC-13, AC-15 (4 trạng thái, ô quét trên cùng, ≥ 48 px, chữ ≥ 16 px, token `--tc-*`, lỗi chặn inline, trả focus ô quét sau mỗi thao tác, không mất mã quét khi đang chờ máy chủ). `station_t3.js` + CSS + nối `station.js` (`T3Assembly`, `protectedCall` thêm `tracecore.v1.assembly.`) + `page_js` + `vi.csv`. Commit `feat(ui): màn trạm T3 kiểm đếm lắp ráp theo BOM (SCR-07)`.

### Task 7: Dữ liệu demo và e2e
- `devdata.ensure_t3_e2e_user/ensure_t3_demo`, trạm tra cứu chung cho smoke (T3 đã có màn riêng nên smoke FEAT-001 chuyển sang trạm không bước), bước trong `e2e_prepare.sh` và bench giả của `test_e2e_prepare_guard.py`; `tests_e2e/test_station_t3.py` (luồng nhiều bước theo `e2e-lighter-policy`: quét Set ID → xác nhận/ghi thiếu từng dòng → R02 PIN → submit; khóa Đóng gói khi thiếu) và fixtures. Commit `test(e2e): luồng T3 kiểm đếm, thiếu, R02 PIN`.

### Task 8: Hoàn tất
- `rtm.md`/`implementation-plan.md` (FEAT-020 đã làm, ghi phần còn mở), toàn bộ test, coverage `diff-cover`, `pre-commit`, e2e `test_station_t3.py` rồi `test_station_t4.py`. Commit `docs(assembly): RTM và trạng thái FEAT-020`.

## Bảng AC (điền ở Task 8)

| AC | Mệnh đề (FR) | Bằng chứng |
| --- | --- | --- |
| AC-1 | FR-M2-05: BOM áp dụng + ảnh từng dụng cụ + ảnh bộ + ghi chú tiếp nhận | xem báo cáo cuối |
| AC-2 | FR-M2-05.1: đủ/thiếu/thừa từng dòng | |
| AC-3 | FR-M2-05.2: hỏng + thay + Sửa chữa/Thanh lý | |
| AC-4 | FR-M2-05.3: cảnh báo cam cơ số | |
| AC-5 | FR-M2-05.4: chưa qua lô rửa Đạt thì chặn | |
| AC-6 | FR-M2-06: thiếu chưa xác nhận khóa Đóng gói | |
| AC-7 | FR-M2-06.1: R02 PIN + lý do mở khóa, nhãn THIẾU | |
| AC-8 | FR-M2-06.2: NC khi thiếu (cờ + hook) | |
| AC-9 | FR-M2-06.3: sai PIN 3 lần khóa 5 phút | |
| AC-10 | FR-M2-00.5: rẽ nhánh Sửa chữa/Thanh lý | |
| AC-11 | FR-M2-25: cổng T3 do `step_gate`, Không đạt → xử lý lại | |
| AC-12 | FR-M1-02.2: quét mã dụng cụ tự tick | |
| AC-13 | FR-M1-02.4: dụng cụ lạ cảnh báo + NC | |
| AC-14 | ADR-003: idempotent + `client_ts` | |
| AC-15 | FR-M9-14 / design.md: 4 trạng thái, STN | |

## Ghi chú hiện thực (khác với dự kiến lúc lập kế hoạch)

- **Mã lỗi thêm:** `PHOTO_INVALID` (422) khi ảnh đính không phải File đã tải lên; `INSTRUMENT_NOT_FOUND` (404, có sẵn) dùng cho dòng không thuộc BOM và mã GIAI chưa gán.
- **`ready_to_submit` / `pack_locked`:** server trả `pack_locked` (Đóng gói khóa tới khi cổng T3 Đạt) kèm `pack_lock_reason` (`LINES_NOT_COUNTED`, `SHORTAGE_UNCONFIRMED`, `NOT_RECORDED`, `BRANCH`, `ASSEMBLY_FAILED`) và `ready_to_submit` để kiosk bật nút ghi nhận; kiosk không tự suy ra.
- **Trạm smoke chung:** TR-003 nay có màn T3 riêng nên smoke FEAT-001 (tra cứu Set ID chung) chuyển sang trạm khu sạch không gán bước `TR-090` do `devdata.ensure_smoke_station` tạo trên site dev/test (không thêm vào khung khu-trạm mặc định). `e2e_prepare.sh` mặc định `TC_E2E_STATION=TR-090`; user smoke trở thành `station-tr-090@…`, user `station-t3@…` là user T3.
- **Dữ liệu dev cũ:** `devdata._ensure_set_type` gán khoa demo cho loại bộ demo tạo trước FEAT-015 (cấp Set ID bắt buộc khoa), để `e2e_prepare.sh` chạy được trên site dev cũ.
- **Quyền DocType:** không đổi ma trận `permission_matrix.csv` và `custom_docperm.json` (Assembly Line là bảng con, không có quyền riêng).
