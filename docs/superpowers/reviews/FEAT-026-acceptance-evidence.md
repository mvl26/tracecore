# FEAT-026 T7 Cấp phát — bằng chứng nghiệm thu

Plan: `docs/superpowers/plans/FEAT-026-t7-issue.md`. Amendment: architecture A-17 (C1–C13; C4–C7 tạm, chờ chủ đầu tư duyệt).

| Yêu cầu | Hành vi | Test | E2E SCR-12 / SCR-36 (`tests_e2e/test_station_t7.py`) |
| :- | :- | :- | :- |
| FR-M2-15 | Chọn khoa, quét nhiều gói, người nhận quét thẻ và ký, xác nhận → phiếu ghi sổ, Pack `Issued`, Set Unit `At Department` (qua `step_gate.issue_to_department`), tồn kho vô khuẩn giảm, tồn khoa tăng | `reprocessing/tests/test_issuing.py::TestSubmit::test_submit_issues_packs_and_moves_stock`, `v1/tests/test_issue_api.py::TestFlow::test_full_flow_issues_two_packs_to_department`, `core/tests/test_step_gate_storage.py` | `test_t7_issue_two_packs_signed_by_card_moves_stock` |
| EI-UI-008 | Ký bằng thẻ (`Card`) hoặc chữ ký cảm ứng (`Touch`, PNG ≤ 200 KB) | `TestSign` | `test_t7_touch_signature_and_unconfigured_par_warning` |
| FR-M2-15.1 | Print Format `TC Issue Note` (số phiếu, khoa, gói, người nhận, chữ ký); email chờ OQ-21, chưa làm | `reprocessing/doctype/issue_note/test_issue_note.py::TestIssueNotePrint`, `test_submit_returns_print_url` | nút In sau khi xác nhận |
| FR-M2-15.2 | Người nhận khác khoa → cảnh báo, tiếp tục khi có lý do | `TestSign::test_recipient_other_department_needs_reason` | `test_t7_over_par_other_department_recipient_needs_reason_and_r02_pin` |
| FR-M2-16 | So tồn khoa + số cấp với min/max theo loại bộ (Par Level `Department Stock`, hook `tracecore_issue_par_check`) | `par/tests/test_stock.py`, `TestContext` | bảng "Tồn khoa và cơ số" trên màn |
| FR-M2-16.1 | Vượt tối đa → R02 duyệt tại màn bằng thẻ + PIN (proof FEAT-019) | `TestSubmit::test_over_max_requires_r02_card_pin`, `test_over_par_needs_r02_card_and_pin` | `test_t7_over_par_...` |
| FR-M2-16.2 | Tồn khoa < tối thiểu → gợi ý cấp bổ sung | `test_stock.py::test_suggests_supply_when_stock_below_min` | khối "Gợi ý cấp bổ sung" |
| FR-M2-16.3 | Khoa cấp cứu vượt ≤ % cho phép → không cần duyệt, ghi Audit | `test_emergency_over_within_percent_logs`, `test_stock.py` | — |
| FR-M2-16.4 | Khoa chưa cấu hình cơ số → cho cấp, cảnh báo, ghi Audit | `test_unconfigured_par_allows_and_logs` | `test_t7_touch_signature_and_unconfigured_par_warning` |
| FR-M2-00.1/.2, UC-12 E1 | Chỉ nhận gói Trong kho vô khuẩn, chưa quá hạn; từ chối kèm lý do, ghi Audit `Reject`; kiểm lại khi ghi sổ | `TestAddPack`, `test_submit_rechecks_pack_status`, `TestRejections` | `test_t7_pack_not_in_stock_is_blocked_with_inline_red_alert` |
| UC-12 A2, FR-M2-13.4 | Gói hạn xa hơn gói FEFO cần ghi chú | `test_fefo_requires_note_for_later_pack`, `test_fefo_order_needs_no_note` | `test_t7_fefo_later_pack_needs_note` |
| FR-M9-14, design.md STN/PDA | Ô quét trên cùng có focus; loading/empty/error/offline; nút ≥ 48 px, chữ ≥ 16 px; khổ PDA 412 px | `tests/test_station_page.py` (T7) | `test_t7_scan_box_on_top_and_department_buttons_are_large`, `test_t7_pda_viewport_fits_without_horizontal_scroll`, `test_t7_offline_shows_offline_state` |

BRU: BRU-FLOW-002, BRU-FLOW-003, BRU-PAR-005 (marker `@bru`).

## Kết quả chạy (23/10/2026, bench `~/tracecore-f026`, site `test_f026`, chạy theo `--module`)

| Module | Kết quả |
| :- | :- |
| `reprocessing.tests.test_issuing` | 32 test OK |
| `v1.tests.test_issue_api` | 16 test OK |
| `par.tests.test_stock` | 8 test OK |
| `core.tests.test_step_gate_storage` | 10 test OK |
| `reprocessing.doctype.issue_note.test_issue_note` | 10 test OK |
| `tests.test_station_page` | 18 test OK |
| `tests.test_devdata` | 49 test OK |
| `core.tests.test_errors` | 8 test OK |
| `reprocessing.tests.test_storage` | 27 test OK |

`diff-cover` (coverage của các module trên, `run-tests --app tracecore --coverage`) so với `github/develop`: **96 %** (427 dòng, thiếu 13). `pre-commit run` sạch trên các file đổi.

## Chưa có / giới hạn

- **Proof R02 (C6):** `station_auth.consume_approver_proof` và RPC `v1.station.verify_approver` thuộc nhánh FEAT-019, chưa có trên `develop`. Test patch `consume_approver_proof`; sau khi 019 merge thì bỏ patch (`test_issuing.py`, `test_issue_api.py`) và e2e mới chạy được bước duyệt R02.
- **E2E Playwright T7:** đã viết (`tests_e2e/test_station_t7.py`, dữ liệu `devdata.ensure_t7_*`, `e2e_prepare.sh` bước 12) nhưng chưa chạy vì máy host thiếu RAM; chạy lại `scripts/e2e_prepare.sh` trước mỗi lần chạy cả file.
- Chưa làm: email phiếu (OQ-21), offline PDA (FEAT-009), báo cáo tồn khoa so cơ số FR-M8-02.2, hoàn trả gói (FEAT-027), permission query R08 theo khoa cho Issue Note, dọn phiếu nháp bỏ dở.
- Mã `DEPARTMENT_NOT_FOUND` (404) có thể trùng nghĩa `DEPARTMENT_INVALID` của FEAT-019: thống nhất khi rebase sau 019.
