# FEAT-046 Cost Sheet mẻ và giá thành bộ — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Khi mẻ tiệt khuẩn được giải phóng (hoặc kết luận Không đạt) và khi lô rửa hoàn tất, hệ thống tự lập Cost Sheet: chi phí mẻ theo từng khoản, chia cho các gói, cộng chi phí lô rửa, lắp ráp, bao gói và khấu hao dụng cụ thành giá thành gói/bộ theo chu trình; R01/R09 tính lại với phiên bản giá khác có ghi chú; báo cáo giá thành theo loại bộ, khoa, phương pháp, tháng, so với tháng trước, xuất Excel/CSV.

**Architecture:** Module M7 `tracecore/costing/sheet.py` (không import M1–M6/M8: đọc DocType qua `frappe.get_all`, nhận sự kiện qua hook `tracecore_after_load_release`, `tracecore_after_load_failed`, `tracecore_after_wash_complete`). Listener xếp job RQ sau commit (`frappe.enqueue(..., enqueue_after_commit=True)`), lỗi tính không làm hỏng giải phóng mẻ. Đơn giá lấy từ `costing.rates` (FEAT-045) theo ngày nghiệp vụ.

**Tech Stack:** Frappe v15, ERPNext Stock Entry, RQ, Script Report.

**Spec:** `docs/srs.md` FR-M7-05/.1/.2, FR-M7-06/.1/.2, FR-M7-03.1/.2, FR-M7-04.1, FR-M5-01.2, EI-SW-006; `docs/use-cases.md` UC-29; `docs/architecture.md` §5.3.1 DT-COSTSHEET, ERD, §6 (release → build_cost_sheet), ADR-009; `docs/implementation-plan.md` FEAT-046; `tracecore/fixtures/permission_matrix.csv` DT-COSTSHEET.

## Quyết định (chủ dự án giao toàn quyền 29/10/2026; ghi vào Amendment A-53)

- **D1 DocType:** `Cost Sheet` (DT-COSTSHEET, module Costing, naming `GT-.YYYY.-.#####`, không submittable vì UC-29 "Workflow —"; chỉ `costing.sheet` ghi; không xóa). Child `Cost Sheet Line` = từng khoản chi phí của mẻ/lô; child mới `Cost Sheet Pack` = giá thành từng gói (cùng DT-COSTSHEET). Quyền theo permission_matrix: R01 đọc, R02 đọc, R09 đọc + ghi (tính lại), R10 đọc.
- **D2 Nguồn:** `source_doctype` = Sterilization Load hoặc Wash Batch (OQ-26: chi phí lô rửa thuộc FEAT-046). Một Cost Sheet chính cho mỗi nguồn (idempotent theo nguồn); tính lại tạo Cost Sheet mới `is_recalculation=1`, không đổi Cost Sheet chính.
- **D3 Khoản chi phí của mẻ/lô:** Khấu hao máy = `Equipment.depreciation_per_load` (FR-M5-01.2); Điện = `kwh_per_cycle` × giá Electricity; Nước = `water_l_per_cycle` × giá Tap Water; Hơi = `steam_kg_per_cycle` × giá Steam; Hóa chất và chỉ thị = dòng Stock Entry ghi sổ có `tc_source_*` = nguồn (FEAT-042), không có thì theo định mức `Program Consumable` (qty_per_load + qty_per_pack × số gói), × giá Item; Nhân công = `duration_min` / 60 × giá Labor (giờ); Bảo trì phân bổ = tổng tiền/ngày của Cost Entry đã ghi sổ phân bổ cho máy (`entry.allocated_to` ngày mẻ) ÷ số mẻ/lô của máy trong ngày đó.
- **D4 Ngày giá:** ngày giải phóng (`released_at`), không có thì ngày kết thúc / bắt đầu; lô rửa theo `ended_at`. Giá đã chụp vào Cost Sheet, đổi bảng giá sau không tính lại (FR-M7-03.1, FR-M7-04.1).
- **D5 Chưa định giá (FR-M7-05.2):** thiếu phiên bản giá hoặc thiếu giá một khoản có số lượng > 0 → khoản đó 0 đ, Cost Sheet `status = Unpriced`, `missing_rates` liệt kê, thông báo R09 sự kiện `COST_SHEET_UNPRICED`.
- **D6 Mẻ Không đạt (FR-M7-05.1):** vẫn lập Cost Sheet, `is_quality_cost = 1`, không chia gói (gói đã Hủy).
- **D7 Chia gói:** theo số gói, làm tròn VND, gói cuối nhận phần dư. Chia theo thể tích (OQ-20 còn mở, chưa có trường thể tích) không làm.
- **D8 Giá thành gói (FR-M7-06):** = phần chia mẻ + phần lô rửa (Cost Sheet của Wash Batch gần nhất có bộ này, bắt đầu trước mẻ, ÷ số bộ của lô) + lắp ráp (`Instrument Set Type.assembly_minutes` / 60 × giá Labor) + bao gói (`rates.pack_norms` của loại gói × giá Item) + khấu hao dụng cụ (Σ `Instrument.value` × qty của BOM phiên bản gói ÷ `Set Unit.max_cycles`). Bộ mượn: không khấu hao dụng cụ; chưa có trường phí mượn nên phí mượn = 0 (ghi gap). Các trạm khác chưa có phút chuẩn trong dữ liệu → không cộng (ghi gap).
- **D9 Ghi kết quả:** `Pack.cost_total` (trường mới, chỉ đọc, M7 ghi bằng `db.set_value`), `Wash Batch.cost_total` (trường có sẵn). Giá thành bộ theo chu trình = `Pack.cost_total` (một gói = một chu trình); không thêm trường vào Set Unit.
- **D10 Tính lại (UC-29 A1, FR-M7-03.2):** RPC `tracecore.v1.costing.recalculate(source_doctype, source_name, rate_version, note)` cho R01/R09; phiên bản phải đã duyệt; ghi chú bắt buộc; Audit Log; không ghi đè `Pack.cost_total`.
- **D11 Báo cáo:** Script Report `Set Cost Report` (module Costing): lọc kỳ, nhóm theo Loại bộ / Khoa / Phương pháp / Cycle ID; cột số gói, tổng, bình quân/gói, bình quân tháng trước, % thay đổi; xuất Excel/CSV bằng nút Export chuẩn của Frappe (EI-SW-006). Lối vào từ launcher nhóm Chi phí.

## Global Constraints

- Frappe/ERPNext v15; luật R1 (M7 không import module nghiệp vụ khác; đọc DocType theo tên, nhận sự kiện qua hook).
- Mọi chuỗi qua `_()`, bản dịch `vi.csv`; VND không lẻ.
- Không chặn giải phóng mẻ: listener chỉ xếp job; job lỗi ghi Error Log.

## Review Focus

1. Giải phóng mẻ rồi giao dịch bị hoàn tác → không có job tính (enqueue sau commit) (Task 3 `test_release_hook_enqueues_after_commit`).
2. Hook gọi hai lần / job chạy lại → đúng một Cost Sheet chính (Task 2 `test_build_is_idempotent`).
3. Tổng phần chia các gói = chi phí mẻ đúng tới đồng (Task 2 `test_split_by_pack_count_sums_exactly`).
4. Thiếu giá một khoản → Unpriced, khoản đó 0, không ném lỗi (Task 2 `test_missing_rate_marks_unpriced_and_notifies_r09`).
5. Tính lại với phiên bản Nháp / không ghi chú → từ chối; tính lại không đổi `Pack.cost_total` (Task 4).

---

### Task 1: Amendment A-53 + DocType
Files: `docs/architecture.md` (Revision History A-53; §5.3.3 thêm `GT-` Cost Sheet), `tracecore/costing/doctype/cost_sheet/`, `cost_sheet_line/`, `cost_sheet_pack/`, `tracecore/reprocessing/doctype/pack/pack.json` (`cost_total`), test `tracecore/costing/tests/test_cost_sheet_doctype.py` (đặt tên GT-, không xóa, quyền R09/R02).

### Task 2: `costing.sheet.build`
Files: `tracecore/costing/sheet.py`, test `tracecore/costing/tests/test_sheet.py`.
Interfaces: `build(source_doctype, source_name, rate_version=None, note=None, recalculation=False) -> str` (tên Cost Sheet); `COMPONENTS`.
Tests: các khoản D3 với số cụ thể (khấu hao 20.000, điện 3,5 kWh × 3.000, nước 20 L × giá, hóa chất theo Stock Entry), chia gói khớp tổng, giá thành gói D8 (lô rửa, lắp ráp, bao gói, khấu hao dụng cụ, bộ mượn = 0), mẻ Không đạt, Unpriced, idempotent, bảo trì phân bổ.

### Task 3: Hook + job
Files: `tracecore/costing/sheet.py` (`on_load_release`, `on_load_failed`, `on_wash_complete`, `run_job`), `tracecore/hooks.py`, `tracecore/core/notification/__init__.py` (EVENTS `COST_SHEET_UNPRICED`), test.

### Task 4: RPC tính lại
Files: `tracecore/v1/costing.py` (`recalculate`), test `tracecore/v1/tests/test_costing_api.py` (hoặc test hiện có).

### Task 5: Báo cáo + launcher
Files: `tracecore/costing/report/set_cost_report/`, `tracecore/v1/navigation.py`, `vi.csv`, test.

### Task 6: Hoàn tất
Full suite, diff-cover ≥ 70 %, pre-commit, RTM FR-M7-05/06, review cả nhánh, sửa, merge develop local, push nhánh.
