# FEAT-027 T8 Quét sử dụng Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** R08 quét Cycle ID tại khoa, nhập mã bệnh nhân/ca mổ/PTV/phòng; hệ thống ghi Usage Record, Pack → `Used`, Set Unit → `Awaiting Receipt`, chặn 100 % mã Đã dùng/Quá hạn/Thu hồi/Hết hiệu lực, che mã bệnh nhân, R01/R02 xem đầy đủ có lý do và audit.

**Architecture:** DocType `Usage Record` (module Reprocessing, submittable, ghi bởi dịch vụ) + dịch vụ `reprocessing/usage.py` + RPC `tracecore.v1.usage.*` qua phiên trạm thẻ (T8, khu Department) + màn SCR-37 là module `station_t8.js` của Page `station`. Đổi trạng thái Set Unit chỉ qua `core.step_gate.use_pack`. Mã bệnh nhân lưu trường `Password`.

**Tech Stack:** Frappe v15, `FrappeTestCase`/`IsolatedTestCase`, Page `station` (JS thuần).

**Spec:** `docs/srs.md` FR-M2-17 (.1–.4), FR-M2-18 (.1–.3); `docs/use-cases.md` UC-13; `docs/architecture.md` §5.3, §5.3.3 (`US-.YYYY.-.#####`), ADR-010 (Amendment A-19 ghi quyết định).

## Global Constraints
- Chỉ `core.step_gate` đổi trạng thái Set Unit; Pack đổi trạng thái qua `storage._save` (cờ `tc_packing`).
- RPC ghi dùng `@station_session` + `@idempotent`, `client_ts` ISO 8601 có offset; mọi từ chối là `BlockedError` → body lỗi + Audit `Reject`.
- Mã bệnh nhân không ghi vào log, Audit hay bất kỳ giá trị nào khác ngoài trường Password; ẩn **4 ký tự giữa** khi hiển thị.
- Chuỗi hiển thị qua `_()`/`__()`, bản dịch ở `translations/vi.csv`. UI: chỉ token `--tc-*`, nút ≥ 48 px (chính 56 px), lỗi chặn là `alert-error` inline.
- Không tích hợp HIS; không làm offline queue (FEAT-009) và thông báo (FEAT-010).

## Review Focus
- Mã Cycle ID đã `Used` quét lại: chặn `PACK_USED`, Audit `Reject`, không đổi gì.
- Quét gói còn trong kho / chưa cấp phát (`In Sterile Stock`, `Released`…): chặn `PACK_NOT_ISSUED`.
- Gói quá hạn (`expiry` < hôm nay) hoặc bộ ở `End of Life`: chặn kèm ngày.
- Khoa người quét khác khoa của gói: cần lý do, ghi `department_reason`.
- Ca cấp cứu: lưu không mã bệnh nhân, nhập bổ sung ≤ 24 h; quá hạn bị chặn.
- Mã bệnh nhân ngắn (≤ 4 ký tự) vẫn che hết; không lộ trong Audit/log.
- Hai lần xác nhận cùng gói (nhấp đôi, mạng chập chờn): một Usage Record (replay cùng khóa idempotent; khóa khác bị chặn `PACK_USED`).

## Tasks

### Task 1: DocType Usage Record + che mã + `step_gate.use_pack`
**Files:** Create `tracecore/reprocessing/doctype/usage_record/{__init__,usage_record.json,usage_record.py,test_usage_record.py}`; Modify `tracecore/core/step_gate.py` (+`use_pack(set_unit)`), `tracecore/core/tests/test_step_gate.py`.
**Interfaces:** Produces `usage_record.mask_patient_code(code: str|None) -> str`; `step_gate.use_pack(set_unit)` (At Department → Awaiting Receipt, bỏ `active_cycle_id`, lỗi nếu trạng thái khác); trường `Usage Record.patient_code_masked` (tính toán, đọc được cho mọi role thấy bản ghi).
- [ ] Test: `mask_patient_code("BN12345678") == "BN****5678"`... (4 giữa), `"AB12" == "****"`, `None → ""`; `use_pack` đúng/sai trạng thái; DocType không tạo được trực tiếp ngoài cờ `tc_usage`.
- [ ] Hiện thực; chạy module test; commit.

### Task 2: Dịch vụ `reprocessing/usage.py` + mã lỗi
**Files:** Create `tracecore/reprocessing/usage.py`, `tracecore/reprocessing/tests/test_usage.py`; Modify `tracecore/core/errors.py`, `core/tests/test_errors.py`.
**Interfaces:** `scan(raw, station, client_ts=None) -> dict` (thẻ gói + `department_warning`); `confirm(cycle_id, station, patient_code, surgery_code, surgeon, room, emergency=False, department_reason=None, client_ts=None) -> dict`; `set_patient_code(usage, patient_code, client_ts=None)`; `reveal_patient_code(usage, reason) -> str`. Mã mới: `PACK_NOT_ISSUED`, `PACK_USED`, `PACK_RECALLED`, `PACK_VOID` (409), `SET_END_OF_LIFE` (409), `PATIENT_CODE_REQUIRED`, `DEPARTMENT_REASON_REQUIRED`, `PATIENT_CODE_DEADLINE` (422), `USAGE_NOT_FOUND` (404). Dùng lại `PACK_NOT_FOUND`, `PACK_EXPIRED`, `REASON_REQUIRED`, `STATION_WRONG_STEP`.
- [ ] Test (BRU-ID-003, BRU-REP-010, BRU-FLOW-003): từng nhánh chặn, xác nhận thành công (Pack `Used`, Set `Awaiting Receipt`, Usage Record `docstatus 1`, mã BN mã hóa — `frappe.db.get_value` không ra bản rõ), nhiều gói một `surgery_code`, cấp cứu 24 h, khoa khác cần lý do, `reveal` ghi Audit `View Patient Code` không chứa mã.
- [ ] Hiện thực; chạy module test; commit.

### Task 3: RPC `tracecore.v1.usage.*`
**Files:** Create `tracecore/v1/usage.py`, `tracecore/v1/tests/test_usage_api.py`; Modify `tracecore/v1/_common.py` (`USAGE_ROLES = ("TC R08", "System Manager")`).
**Interfaces:** `scan(raw, station, client_ts, token)`, `confirm(...)`, `set_patient_code(usage, patient_code, station, client_ts, token)` (POST, `@station_session(*USAGE_ROLES)`, `@idempotent`); `reveal_patient_code(usage, reason)` (POST, phiên Desk R01/R02/System Manager, `@idempotent`).
- [ ] Test: mã HTTP và quyền (R08 ok; R06/R03 bị 403; R08 không gọi được `reveal`), replay idempotent, Audit `Reject` khi bị chặn, trạm sai bước.
- [ ] Hiện thực; chạy module test; commit.

### Task 4: Màn SCR-37 trên Page station
**Files:** Create `tracecore/public/js/station_t8.js`; Modify `tracecore/ui/page/station/station.js` (nối `T8Usage`, token cho `tracecore.v1.usage.`), `tracecore/ui/page/station/station.css`, `tracecore/hooks.py` (`page_js`), `tracecore/v1/navigation.py` (T8 → TC R08, `IMPLEMENTED_STEPS`), `tracecore/translations/vi.csv`; Test `tracecore/tests/test_station_t8_assets.py` (chuỗi qua `__()` có bản dịch, không hex/px cứng, nút ≥ 48 px theo token).
- [ ] Test tài sản (RED) → hiện thực màn: ô quét luôn trên cùng và có focus; thẻ gói → form (mã BN, ca mổ, PTV, phòng, cấp cứu) → xác nhận; lỗi chặn `alert-error` toàn khối (kết quả → lý do → hành động); đủ 4 trạng thái loading/empty/error/offline; commit.

### Task 5: Tài liệu, ma trận quyền, kiểm tra
**Files:** Modify `docs/architecture.md` (Revision A-19, ghi chú §5.3.1 M2, ADR-003 mã lỗi), `docs/srs.md` (hàng revision A-19), `tracecore/fixtures/custom_docperm.json` (sinh lại từ `setup.permissions`), `tracecore/hooks.py`.
- [ ] Sinh lại fixture quyền; `bench migrate` site test; chạy các module mới và module lân cận; `pre-commit run --all-files`; commit; push; mở PR (base = nhánh FEAT-026 tới khi #11 merge).

## Gap ghi nhận
- A2 "Mở không dùng" (UC-13), cổng khoa SCR-13, offline queue (FEAT-009), thông báo (FEAT-010), cảnh báo cấp cứu quá 24 h chưa nhập mã (báo cáo) — ngoài phạm vi, chưa làm.
- Đánh số amendment A-19 do dev lead tự chọn sau A-18; nếu nhánh khác đã dùng thì đánh lại khi merge.
