# FEAT-023 T5b Dỡ mẻ, giải phóng, cách ly chờ BI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Dỡ mẻ tiệt khuẩn: quét QR máy và QR mẻ, ghi kết quả chu trình và chỉ thị (Bowie-Dick, hóa học, sinh học), R02 giải phóng bằng PIN; mẻ có BI sang Cách ly chờ đọc; mẻ Không đạt trả bộ về xử lý lại; mẻ Đạt ghi cổng T5, đưa bộ đủ 5 cổng sang Vô khuẩn và tăng bộ đếm chu trình.

**Architecture:** Mở rộng `Sterilization Load` (FEAT-022) và thêm DocType `Load Indicator Result` (DT-LOADTEST). Dịch vụ `reprocessing/releasing.py` theo khuôn `washing.set_result` (kiểm lại trạm và hai mã quét, savepoint, PIN proof R02 qua `station_auth.consume_session_pin_proof`), RPC `tracecore.v1.release.*`, màn SCR-10 là chế độ "Dỡ mẻ" của màn T5 (`station_t5.js`). Chỉ `core.step_gate` đổi trạng thái/bộ đếm của Set Unit (thêm `count_cycle`).

**Tech Stack:** Frappe v15, `IsolatedTestCase`, Page `station`.

**Spec:** `docs/srs.md` FR-M2-11 (.1–.9), FR-M2-12 (.2), FR-M2-25, FR-M1-06 (.1 bộ đếm), FR-M1-09.2; `docs/use-cases.md` UC-10; `docs/architecture.md` §5.3 (DT-LOAD, DT-LOADTEST), WF-03; Amendment A-20.

## Global Constraints
- RPC ghi của trạm dùng `@station_session` + `@idempotent`, `client_ts` ISO 8601 có offset; từ chối nghiệp vụ là `BlockedError` → body lỗi + Audit `Reject`.
- Giải phóng chỉ R02 (bằng PIN proof của chính phiên), hoặc R01 giải phóng khẩn kèm lý do (FR-M2-11.8); vai trò khác không giải phóng được.
- Không nhập gói vào kho T6 trước khi mẻ Đã giải phóng (FR-M2-11.6, đã chặn ở `storage` bằng trạng thái Pack `Released`).
- Chuỗi qua `_()`/`__()` có bản dịch; UI chỉ token `--tc-*`; lỗi chặn là `alert-error` inline.
- Không làm: NC tự tạo (FEAT-030), lệnh thu hồi (FEAT-029), thông báo (FEAT-010), dữ liệu máy tự động (FEAT-024), tiêu hao/chi phí (FEAT-042/046; chỉ phát hook), cấp trước BI cho cấy ghép tại T7.

## Quyết định (Amendment A-20, tạm — chờ chủ đầu tư)
| # | Quyết định |
| :- | :- |
| D1 | `Load Indicator Result`: một dòng cho mỗi chỉ thị (`bowie_dick`, `chemical_class_5`, `chemical_plasma`, `biological`), theo mẻ hoặc theo gói; BI tạo `Pending` khi đưa vào tủ ủ rồi đọc `Pass`/`Fail` sau. |
| D2 | Mẻ cần giải phóng khi `data_complete` và có `cycle_result` (nhập tay có xác nhận); `needs_review` cần `review_confirmed` của R02. |
| D3 | Chỉ thị bắt buộc theo máy: hơi nước = hóa học 5 + Bowie-Dick (ngày hôm nay, Đạt); plasma = hóa học plasma; cần BI thì thêm sinh học. Mọi chỉ thị cần có kết quả `Pass`, thiếu hoặc `Fail` không giải phóng được. |
| D4 | Mẻ Không đạt (kết quả chu trình Fail hoặc chỉ thị Fail, R02 xác nhận) → mọi gói `Void/Load Failed`, cổng T5 Fail cho mọi bộ (bộ về `Reprocess`), `redo_from` T4 mặc định hoặc T2 (khi T2: ghi thêm cổng T2 Fail). |
| D5 | Cần BI: giải phóng chuyển mẻ sang `Quarantine`, gói `Quarantine`; BI âm tính → hoàn tất giải phóng; BI dương tính → mẻ Không đạt, hook `tracecore_bi_positive`. BI đọc sau giải phóng dương tính → hook, Audit `Override`, gap: lệnh thu hồi là FEAT-029. |
| D6 | Giải phóng Đạt: Pack `Released`, cổng T5 Đạt từng bộ (đủ 5 cổng → Vô khuẩn), `step_gate.count_cycle` (+1 `cycles_used`), hook `tracecore_after_release` (+1 bộ đếm bảo dưỡng) và `tracecore_after_load_release` cho M6/M7 (hook đồng bộ trong cùng transaction); mẻ ghi sổ. |

## Review Focus
- Quét QR máy khác máy của mẻ: chặn `EQUIPMENT_MISMATCH`; chưa đủ hai mã: không mở dỡ.
- Thiếu dữ liệu chu trình / kết quả / chỉ thị: `LOAD_NOT_RELEASABLE` kèm danh sách thiếu, không đổi gì.
- Bấm giải phóng hai lần (nhấp đôi): một lần đếm chu trình, một lần hook bảo dưỡng (cùng `cycle_id`).
- BI dương tính khi gói đã cấp phát: không để lọt, phát hook và ghi Audit.
- Người không phải R02/R01 gọi giải phóng: chặn, không ghi.

## Tasks
### Task 1: `step_gate.count_cycle` và trường mới
**Files:** Modify `tracecore/core/step_gate.py`, `tracecore/core/tests/test_step_gate_storage.py`, `tracecore/reprocessing/doctype/sterilization_load/{sterilization_load.json,sterilization_load.py}`; Create `tracecore/reprocessing/doctype/load_indicator_result/{__init__,load_indicator_result.json,load_indicator_result.py,test_load_indicator_result.py}`.
**Interfaces:** `step_gate.count_cycle(set_unit) -> int` (+1 `cycles_used`, trả giá trị mới); Load thêm `redo_from`, `bi_result`, `release_reason`, `review_confirmed`; DocType `Load Indicator Result` (`load`, `indicator`, `pack`, `result`, `test_date`, `lot`, `incubator`, `read_at`, `read_by`, `recorded_by_user`, `station`).
- [ ] Test (RED) → hiện thực → chạy module → commit.

### Task 2: Dịch vụ `reprocessing/releasing.py`
**Interfaces:** `context(load, equipment_raw, load_raw, station)`, `set_cycle_result(load, result, confirmed, station, equipment_raw, load_raw, client_ts, employee)`, `record_indicator(load, indicator, result, station, pack=None, test_date=None, lot=None, incubator=None, read_at=None, employee=None, client_ts=None)`, `release(load, station, equipment_raw, load_raw, session, pin_proof, review_confirmed=False, emergency_reason=None, client_ts=None)`, `reject(load, station, equipment_raw, load_raw, session, pin_proof, redo_from="T4", reason=None, client_ts=None)`, `bi_result(load, result, station, read_at=None, employee=None, client_ts=None)`. Mã lỗi mới: `LOAD_NOT_RELEASABLE` (409), `INDICATOR_INVALID` (422), `BI_NOT_PENDING` (409).
- [ ] Test (RED) từng nhánh D2–D6 và Review Focus → hiện thực → chạy module → commit.

### Task 3: RPC `tracecore.v1.release.*`
**Files:** Create `tracecore/v1/release.py`, `tracecore/v1/tests/test_release_api.py`; Modify `tracecore/v1/_common.py` (`RELEASE_ROLES`).
- [ ] Test quyền, mã HTTP, idempotent, replay → hiện thực → chạy → commit.

### Task 4: Màn SCR-10 (chế độ Dỡ mẻ của T5)
**Files:** Modify `tracecore/public/js/station_t5.js` (+ CSS nếu cần), `tracecore/translations/vi.csv`; Test `tracecore/tests/test_station_t5b_assets.py`.
- [ ] Test tài sản (RED) → hiện thực → chạy → commit.

### Task 5: Tài liệu, kiểm tra, PR
- [ ] Amendment A-20 (architecture), mã lỗi ADR-003, bản dịch, `pre-commit run --all-files`, push, PR base `feat/FEAT-022-t5-load`.

## Gap ghi nhận
NC tự tạo, lệnh thu hồi, thông báo, dữ liệu máy tự động, chi phí/tiêu hao thật, cấp trước BI cho cấy ghép (FR-M2-12.1), giải phóng khẩn có cảnh báo gửi người khác chỉ ghi Audit.
