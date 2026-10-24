# FEAT-026 T7 Cấp phát — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (hoặc subagent-driven-development). Steps dùng checkbox `- [ ]`.

**Goal:** KTV cấp phát (R06) tại trạm T7 (kiosk SCR-12) hoặc PDA (SCR-36) chọn khoa, thấy tồn khoa và cơ số của khoa, quét nhiều gói đang *Trong kho vô khuẩn* vào một phiếu cấp phát, quét thẻ người nhận, ký điện tử (thẻ hoặc chữ ký cảm ứng), ghi sổ phiếu → Pack *Đã cấp phát*, Set Unit *Tại khoa*, tồn kho vô khuẩn giảm, tồn khoa tăng; vượt cơ số tối đa cần R02 duyệt bằng thẻ + PIN tại chỗ (khoa cấp cứu vượt ≤ % cho phép thì tự cho và ghi log); in phiếu cấp phát.

**Architecture:** Dịch vụ M2 ở `tracecore/reprocessing/issuing.py`; DocType `Issue Note` (submittable) + child `Issue Note Pack` (module Reprocessing, architecture §5.3 DT-ISSUE). Set Unit đổi trạng thái chỉ qua hàm mới `core.step_gate.issue_to_department`. Kiểm cơ số khoa ở M8 (`tracecore.par.check.issue_par`) gọi qua hook `tracecore_issue_par_check` (`core.extension.run`, không import M2↔M8, ADR-001). RPC mỏng `tracecore/v1/issue.py` (`@station_session`, `@idempotent` cho RPC ghi). UI là phần T7 của Page `station` (`public/js/station_t7.js`, nạp bằng `page_js`), cùng file cho kiosk 1366×768 và PDA 412×915 (ADR-002). Print Format `TC Issue Note`.

**Spec:** implementation-plan §3 (FEAT-026); srs FR-M2-15(.1–.2), FR-M2-16(.1–.4), FR-M8-02 (một phần: áp dụng cơ số khoa khi cấp), FR-M2-00.1/.2, EI-UI-007/008; use-cases UC-12 (main, A1, A2, E1–E3); architecture §5.3 (Issue Note), §5.3.3 (`IS-.YYYY.-.#####`), ADR-001/003/005; ux-foundations SCR-12, SCR-36; permission_matrix DT-ISSUE.

FR/BRU đáp ứng: FR-M2-15, FR-M2-15.1 (in; email chờ OQ-21), FR-M2-15.2, FR-M2-16, FR-M2-16.1–.4, FR-M8-02 (partial), FR-M2-00.1/.2; BRU-FLOW-002, BRU-FLOW-003, BRU-PAR-005.

**Nhánh:** `feat/FEAT-026-t7-issue` (tách từ `develop` mới nhất), làm trong bench riêng `~/tracecore-f026/apps/tracecore` (site test `test_f026`, redis 13026/11026).

## Quyết định

Mã C1–C13. "[Tạm]" = chờ chủ đầu tư duyệt; "[Xác nhận]" = dev lead xác nhận theo tài liệu. Ghi vào architecture Revision History là amendment kế tiếp (đánh số khi lên `develop`).

| # | Loại | Nội dung | Căn cứ |
| :- | :- | :- | :- |
| C1 | [Xác nhận] | `Issue Note` (Reprocessing, `is_submittable`, tên `IS-.YYYY.-.#####`): `department` (Link Department, bắt buộc), `station`, `issued_by_user`, `issued_by` (Employee của phiên trạm), `recipient` (Employee), `recipient_name`, `recipient_department`, `dept_mismatch_reason`, `sign_method` (`Card`/`Touch`), `signature` (Signature), `signed_at`, `packs` (Table `Issue Note Pack`), `pack_count`, `par_result` (JSON chỉ đọc), `approved_by` (User R02), `approved_at`, `issued_at`, `client_ts`. Nháp (`docstatus 0`) giữ danh sách gói đang quét; ghi sổ khi xác nhận. **Không hủy, không xóa** (hoàn trả gói thuộc FEAT-027): `before_cancel` chặn | architecture §5.3, §5.3.3; CLAUDE.md |
| C2 | [Xác nhận] | `Issue Note Pack` (child): `pack` (Link Pack), `set_unit`, `set_type`, `set_name`, `expiry`, `fefo_note` | DT-ISSUE |
| C3 | [Xác nhận] | Ghi sổ phiếu, mỗi gói trong một transaction: Pack `In Sterile Stock` → `Issued`, `location` xóa (gói rời kệ); Set Unit `Sterile` → `At Department` bằng hàm mới `step_gate.issue_to_department` (chỉ từ `Sterile`); Audit Log qua hook DocType. Khóa Set Unit rồi Pack như `storage._lock_pack` | FR-M2-15, ADR-005, BRU-FLOW-003 |
| C4 | [Tạm] | "Tồn kho vô khuẩn" = số Pack `In Sterile Stock` (FEAT-025, suy ra); "tồn khoa" của (khoa, loại bộ) = số Pack `Issued` nằm trong `Issue Note` đã ghi sổ của khoa đó. Không dùng Stock Entry ERPNext cho gói (gói không phải Item tồn kho); FEAT-027 chuyển gói sang `Used` thì tồn khoa tự giảm. Không thêm trường Pack | FR-M2-15 "trừ tồn kho vô khuẩn và cộng tồn khoa" |
| C5 | [Tạm] | Cơ số khoa: hook `tracecore_issue_par_check` → `par.check.issue_par(ctx)` với `ctx = {department, set_type, stock, adding}`, đọc `Par Level` loại `Department Stock` đang hiệu lực. Trả `state`: `ok`; `over` (stock + adding > max, cần R02); `over_allowed` (khoa cấp cứu, stock + adding ≤ ⌊max × (1 + over_percent/100)⌋, không cần duyệt, ghi Audit `ParOverAllowed` khi ghi sổ); `unconfigured` (cho cấp, cảnh báo "chưa cấu hình cơ số", ghi Audit khi ghi sổ); kèm `suggest` = max(0, min − stock − adding) khi tồn khoa < min (gợi ý cấp bổ sung). Không có hook nào trả về → coi như `unconfigured` | FR-M2-16, .1–.4, FR-M8-02, BRU-PAR-005 |
| C6 | [Tạm] | R02 duyệt vượt cơ số **tại màn cấp phát** (UC-12 A1): R02 quét thẻ + nhập PIN trên chính kiosk R06 qua `v1.station.verify_approver` (FEAT-019 A-15) để lấy proof dùng một lần gắn với phiên R06; `v1.issue.submit(approver_proof)` → `issuing` gọi `station_auth.consume_approver_proof(session, proof)` và tự kiểm role TC R02. Chưa có trên `develop` (nằm ở nhánh FEAT-019): test patch `consume_approver_proof`, sau khi 019 merge thì bỏ patch. Thiếu/sai proof → `PAR_APPROVAL_REQUIRED` (409) kèm `items` loại bộ vượt | UC-12 A1, FR-M2-16.1 |
| C7 | [Tạm] | Người nhận luôn được xác định bằng **quét thẻ nhân viên** (UC-12 tiền điều kiện). Chữ ký điện tử: `Card` (lần quét thẻ là chữ ký) hoặc `Touch` (ảnh chữ ký vẽ trên màn, PNG data URL ≤ 200 KB, lưu trường Signature). Thẻ không hợp lệ → `RECIPIENT_INVALID` (422). Người nhận thuộc khoa khác (`Employee.department` ≠ khoa nhận) → `RECIPIENT_DEPT_MISMATCH` (409, cảnh báo) cho tới khi gửi lại kèm lý do (UC-12 E2) | FR-M2-15, FR-M2-15.2, EI-UI-008 |
| C8 | [Xác nhận] | FEFO khi thêm gói: `storage.fefo_check`; còn gói cùng loại bộ hạn gần hơn → `FEFO_NOTE_REQUIRED` (409) kèm gói gợi ý; gửi lại kèm ghi chú (khoa chỉ định Set ID, UC-12 A2) thì nhận và lưu `fefo_note` | FR-M2-13.4, UC-12 A2, A-10 D6 |
| C9 | [Xác nhận] | Thứ tự kiểm khi thêm gói: trạm T7 → mã là gói (`SCAN_INVALID`) → gói tồn tại (`PACK_NOT_FOUND`) → `In Sterile Stock` (`PACK_NOT_IN_STOCK`, FR-M2-00.1) → hạn ≥ hôm nay (`PACK_EXPIRED`, UC-12 E1) → không nằm ở phiếu nháp khác (`PACK_IN_OTHER_ISSUE`, 409) → Set Unit `Sterile` (`STATUS_INVALID_FOR_STATION`) → FEFO. Quét lặp gói đã có trong phiếu: không lỗi, trả phiếu hiện tại. Mọi từ chối ghi Audit `Reject` (`run_at_step`, FR-M2-00.2). Gói được kiểm lại toàn bộ khi ghi sổ | FR-M2-00.1/.2, BRU-FLOW-002 |
| C10 | [Xác nhận] | Print Format `TC Issue Note` (Jinja, module Reprocessing, A4 dọc): số phiếu, khoa, thời điểm, người cấp, người nhận, cách ký và ảnh chữ ký, bảng gói (Cycle ID, Set ID, tên bộ, hạn), dòng duyệt R02 nếu có. `submit` trả `print_url`. **Gửi email cho khoa (FR-M2-15.1) chờ OQ-21** — không làm ở FEAT-026 | FR-M2-15.1, OQ-21 |
| C11 | [Xác nhận] | Quyền DocType theo `permission_matrix.csv` DT-ISSUE (đã có). RPC trạm: `TC R06` + System Manager (`STORAGE_ROLES`), qua `@station_session` (A-08). Tên RPC giữ `v1.issue.create/add_pack/sign/submit` và thêm đọc `v1.issue.departments`, `v1.issue.context`, ghi `v1.issue.remove_pack` (bỏ gói quét nhầm khỏi phiếu nháp) | implementation-plan §3, A-08 |
| C12 | [Xác nhận] | Mã HTTP mới (ADR-003): 422 `RECIPIENT_INVALID`, `SIGNATURE_INVALID`; 404 `ISSUE_NOT_FOUND`, `DEPARTMENT_NOT_FOUND`; 409 `PACK_IN_OTHER_ISSUE`, `FEFO_NOTE_REQUIRED`, `RECIPIENT_DEPT_MISMATCH`, `ISSUE_NOT_DRAFT`, `ISSUE_EMPTY`, `ISSUE_NOT_SIGNED`, `PAR_APPROVAL_REQUIRED` | ADR-003 |
| C13 | [Xác nhận] | Ngoài phạm vi: hàng đợi offline PDA (FEAT-009; màn T7 báo offline, không ghi), email phiếu (OQ-21), báo cáo tồn khoa so cơ số FR-M8-02.2 (A-11 G3, làm sau khi có tồn khoa), hoàn trả/hủy phiếu (FEAT-027), cấp đồ vải (FEAT-035), SCR-44..46 | implementation-plan §3 |

## File

- Tạo: `tracecore/reprocessing/doctype/issue_note/{issue_note.json,issue_note.py,test_issue_note.py,__init__.py}`, `tracecore/reprocessing/doctype/issue_note_pack/{issue_note_pack.json,issue_note_pack.py,__init__.py}`, `tracecore/reprocessing/issuing.py`, `tracecore/reprocessing/tests/test_issuing.py`, `tracecore/v1/issue.py`, `tracecore/v1/tests/test_issue_api.py`, `tracecore/reprocessing/print_format/tc_issue_note/{tc_issue_note.json,tc_issue_note.html,__init__.py}`, `tracecore/public/js/station_t7.js`, `tests_e2e/test_station_t7.py`.
- Sửa: `core/step_gate.py` (+`issue_to_department`), `core/tests/test_step_gate_storage.py`, `core/errors.py`, `par/check.py` (+`issue_par`), `par/tests/test_check.py`, `hooks.py` (doc_events, `tracecore_issue_par_check`, `page_js`), `ui/page/station/station.js` (giao T7), `station.css` (khối T7, khổ PDA), `tests/test_station_page.py`, `tests/factories.py` (+`make_stocked_pack`, `make_recipient`), `translations/vi.csv`, `docs/architecture.md` (amendment), `docs/rtm.md`, `scripts/e2e_prepare.sh` + `setup/devdata.py` (dữ liệu T7).

## Tasks

Mọi task: test trước (thấy FAIL), code, PASS, commit Conventional Commits. Bản dịch `vi.csv` cập nhật cùng task. Mỗi BRU có test gắn `@bru`.

- [ ] **T0 Amendment** `architecture.md` Revision History (C1–C13) + ghi chú ở §5.3.1 (M2). Không thêm DocType ngoài §5.3 (Issue Note đã có), không thêm/bớt FR/BRU.
- [ ] **T1 `step_gate.issue_to_department`** (FR-M2-15, BRU-FLOW-003, ADR-005): `Sterile` → `At Department`, giữ `active_cycle_id`; trạng thái khác → lỗi, không ghi. Test `core/tests/test_step_gate_storage.py` (`@bru("BRU-FLOW-003")`).
- [ ] **T2 DocType Issue Note + Issue Note Pack** (C1, C2, C11; FR-M2-15): naming `IS-.YYYY.-.#####`, quyền theo ma trận DT-ISSUE, chặn hủy/xóa, Audit hook. Test `reprocessing/doctype/issue_note/test_issue_note.py`.
- [ ] **T3 `par.check.issue_par` + hook** (C5; FR-M2-16, .1–.4, FR-M8-02; BRU-PAR-005): ok / over / over_allowed (cấp cứu ≤ %) / unconfigured / suggest. Test `par/tests/test_check.py` (`@bru("BRU-PAR-005")`).
- [ ] **T4 `reprocessing/issuing.py` — tạo phiếu, thêm/bỏ gói, tồn khoa** (C3, C4, C8, C9; FR-M2-15, FR-M2-16, FR-M2-00.1/.2; BRU-FLOW-002): `create`, `add_pack`, `remove_pack`, `context` (tồn khoa + cơ số theo loại bộ), `departments`. Test `reprocessing/tests/test_issuing.py` (`@bru("BRU-FLOW-002")`).
- [ ] **T5 `issuing.sign` + `issuing.submit`** (C3, C5, C6, C7; FR-M2-15, .2, FR-M2-16.1, .3, .4; BRU-PAR-005, BRU-FLOW-003): thẻ người nhận, lệch khoa có lý do, Card/Touch, duyệt R02 thẻ + PIN, ghi sổ đổi Pack/Set Unit, Audit `ParOverAllowed`/`ParUnconfigured`. Test `reprocessing/tests/test_issuing.py`.
- [ ] **T6 RPC `v1.issue.*`** (C11, C12; mọi FR trên): mã HTTP, `@idempotent`, `@station_session`, `print_url`. Test `v1/tests/test_issue_api.py`.
- [ ] **T7 Print Format `TC Issue Note`** (C10; FR-M2-15.1): render HTML có số phiếu, khoa, gói, người nhận, chữ ký. Test trong `test_issue_note.py`.
- [ ] **T8 UI SCR-12 / SCR-36** `station_t7.js` (+CSS): ô quét trên cùng có focus; chọn khoa → bảng tồn khoa/cơ số; quét gói → danh sách phiếu; FEFO cần ghi chú; quét thẻ người nhận; ký Thẻ / Cảm ứng (canvas); vượt cơ số → khối duyệt R02 (thẻ + PIN); Xác nhận → in phiếu; 4 trạng thái loading/empty/error/offline; alert-error inline; nút ≥ 48/56 px; khổ PDA 412 px. Test `tests/test_station_page.py`.
- [ ] **T9 E2E** `tests_e2e/test_station_t7.py` (kiosk 1366×768 và PDA 412×915) + dữ liệu `e2e_prepare.sh`/`devdata`.
- [ ] **T10 Kết thúc**: `pre-commit run --all-files`, `run-tests --module …` từng module đổi, coverage + `diff-cover --fail-under=70`, cập nhật `rtm.md`, bằng chứng nghiệm thu `docs/superpowers/reviews/FEAT-026-acceptance-evidence.md`, push, PR vào `main`.

## Acceptance criteria → test

| AC (EARS) | Test |
| :- | :- |
| FR-M2-15: quét nhiều gói + thẻ người nhận → một phiếu cho một khoa, ký, Pack Đã cấp phát, Set Unit Tại khoa, tồn kho giảm, tồn khoa tăng | `test_issuing.test_submit_issues_packs_and_moves_stock`, `test_issue_api.test_full_flow` |
| FR-M2-15.1: phiếu đã ký in được | `test_issue_note.test_print_format_renders`, `test_issue_api.test_submit_returns_print_url` |
| FR-M2-15.2: người nhận khác khoa → cảnh báo (tiếp tục có lý do) | `test_issuing.test_recipient_other_department_needs_reason` |
| FR-M2-16: so tồn khoa + số cấp với min/max theo loại bộ | `test_check.test_issue_par_*`, `test_issuing.test_context_shows_stock_and_par` |
| FR-M2-16.1: vượt max → cảnh báo + R02 duyệt tại màn | `test_issuing.test_over_max_requires_r02_card_pin` |
| FR-M2-16.2: tồn < min → gợi ý cấp bổ sung | `test_check.test_issue_par_suggests_below_min` |
| FR-M2-16.3: khoa cấp cứu vượt ≤ % → không cần duyệt, ghi log | `test_issuing.test_emergency_over_within_percent_logs` |
| FR-M2-16.4: chưa cấu hình → cho cấp, cảnh báo | `test_issuing.test_unconfigured_par_allows_and_logs` |
| FR-M2-00.1/.2: chỉ nhận gói Trong kho; sai → lỗi kèm lý do + audit | `test_issuing.test_add_pack_rejects_*`, `test_issue_api.test_reject_is_audited` |
| UC-12 E1: gói quá hạn bị chặn | `test_issuing.test_add_pack_rejects_expired` |
| UC-12 A2: FEFO cần ghi chú | `test_issuing.test_fefo_requires_note` |
