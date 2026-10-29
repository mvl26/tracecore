# FEAT-034 Lô giặt theo kg, trừ hóa chất và chi phí/kg — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** R07 tạo lô giặt theo kg trên trạm đồ vải: chọn máy giặt Sẵn sàng, chương trình, cờ nhiễm, kg (≤ tải máy), hóa chất; kết thúc giặt thì ghi bước sấy và kết quả Đạt/Không đạt; khi hoàn tất hệ thống trừ hóa chất theo định mức chương trình × kg và tính chi phí/kg (điện, nước, hóa chất, nhân công) hiển thị ngay.

**Architecture:** Module `Linen` (M3) thêm `Laundry Batch` (+ child `Laundry Batch Chemical`) và dịch vụ `tracecore/linen/laundry.py`; RPC mỏng `tracecore.v1.laundry.*` theo khuôn `v1.linen` / `v1.wash` (`station_session` + `@idempotent`). Màn trạm là screen mới `LaundryBatch` (`public/js/station_laundry.js`) trong trạm đồ vải `LIN` đã có. M3 không import M5/M6/M7: trừ kho và chi phí đi qua hook `tracecore_after_laundry_complete` (như `tracecore_after_wash_complete`); `inventory.consume` (FEAT-042) và `costing` đăng ký hook.

**Tech Stack:** Frappe v15, Python 3.11, JS thuần trong Page `station`. Không chạy E2E trừ khi được bảo.

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-034; `docs/srs.md` FR-M3-03 (.1–.4), FR-M3-04 (.1–.2); `docs/use-cases.md` UC-17; `docs/ux-foundations.md` SCR-17; `docs/architecture.md` §5.3 M3 (Laundry Batch, WF-04), §5.3.3 (`LG-`).

FR/BRU đáp ứng: FR-M3-03, FR-M3-03.1–.4, FR-M3-04, FR-M3-04.1–.2; BRU-LIN-001, BRU-LIN-003, BRU-INV-002, BRU-EQP-002.

**Nhánh:** `feat/FEAT-034-laundry-batch` cắt từ `develop` (bbf2f31). Số amendment dự kiến: **A-50**.

## Quyết định cần duyệt

**[Chốt]** = tài liệu thiếu hoặc mâu thuẫn, cần người duyệt. **[Xác nhận]** = lựa chọn thiết kế trong phạm vi tài liệu. Phương án ghi ở đây là phương án sẽ làm nếu được duyệt.

| # | Loại | Câu hỏi | Phương án trong plan | Căn cứ |
| :- | :- | :- | :- | :- |
| D1 | [Xác nhận] | Trạm cho màn lô giặt | Dùng trạm đồ vải `LIN` đã có (A-49 L1, `navigation.py` ghi "sau này lô giặt"); thêm screen `LaundryBatch` cạnh `LinenCollect`, chuyển bằng thanh tab ở đầu màn. Không thêm giá trị bước mới. Không đi qua `step_gate`, không đổi trạng thái Set Unit. | A-49; SCR-17 (STN) |
| D2 | [Xác nhận] | DocType và mã | `Laundry Batch` submittable, naming `LG-.YY.MM.DD.-.##` (đã có trong architecture §5.3.3), child `Laundry Batch Chemical` {item, qty, batch_no}. Trạng thái `Running / Passed / Failed` dùng chung quy ước WF-04 với Wash Batch. | architecture §5.3, §5.3.3 |
| D3 | [Chốt] | Tải máy theo kg | `Equipment.capacity` là Data (chuỗi tự do), không so sánh được. Thêm trường số `capacity_kg` (Float, chỉ máy giặt/sấy) vào `Equipment`. Trống = không giới hạn và hiện cảnh báo "chưa khai tải máy", không chặn. | FR-M3-03.3 |
| D4 | [Chốt] | "Hóa chất khử khuẩn" (FR-M3-03.2) | Thêm Custom Field `Item.tc_is_disinfectant` (Check, chỉ hiện với nhóm Chemical). Lô Nhiễm mà chương trình < 71 °C chỉ được tạo khi có ít nhất một hóa chất khử khuẩn (từ dòng đã chọn hoặc định mức chương trình). Ngưỡng 71 là hằng số trong `laundry.py`. | FR-M3-03.2; BRU-LIN-003 |
| D5 | [Xác nhận] | Chặn trộn nhiễm/không nhiễm | `Laundry Batch` có một cờ `contaminated`. RPC `start` nhận `loads: [{kg, contaminated}]`; có cả hai loại cờ thì chặn `LAUNDRY_MIXED`; kg lô = tổng. Chỉ một cờ → lưu cờ đó. | FR-M3-03.1; BRU-LIN-003 |
| D6 | [Chốt] | Định mức hóa chất theo kg | `Program Consumable` chỉ có `qty_per_load`, `qty_per_pack`. Thêm `qty_per_kg` (Float) vào child này. Lô giặt trừ `qty_per_kg × kg + qty_per_load`. Dòng hóa chất người dùng nhập (item, qty) ghi đè định mức theo item; qty 0 dùng định mức. Lô hóa chất do FEFO tự chọn (FEAT-042), không chọn tay. | FR-M3-04; BRU-INV-002 |
| D7 | [Chốt] | Khi nào trừ kho | Trừ cả khi Đạt và Không đạt (hóa chất đã dùng thật), khác lô rửa (chỉ Đạt). Hook `tracecore_after_laundry_complete` ctx `{batch, equipment, program, kg, chemicals, result}`; `inventory.consume.on_laundry_complete` gọi `consume_for("Laundry Batch", …)` idempotent. Thiếu tồn thì xử lý như A-46 (trừ phần có, ghi phần thiếu, báo R09). | FR-M3-04; A-46 |
| D8 | [Xác nhận] | Chi phí/kg | Hook `costing.from_laundry.on_laundry_complete` tính: điện = `kwh_per_cycle` × giá Electricity; nước = `water_l_per_cycle` × giá Tap Water; hóa chất = Σ qty × giá Item; nhân công = `duration_min`/60 × giá Labor; theo bảng giá đã duyệt tại ngày hoàn tất (`rates.rate_for`). Thiếu giá thì bỏ khoản đó, ghi `cost_note` liệt kê khoản thiếu (FR-M7-05.2), vẫn hoàn tất. `cost_per_kg = cost_total / kg`. Khoản sấy chưa tính (chương trình sấy không có định mức). | FR-M3-04; FR-M7-03 |
| D9 | [Xác nhận] | Bước sấy | Không thêm DocType: trường `dryer`, `dry_temp_c`, `dry_minutes` trên `Laundry Batch`, nhập khi `complete` cùng kết quả kiểm tra `clean_ok`, `dry_ok`. Đạt = cả hai Đạt. Máy sấy phải là `Dryer` Sẵn sàng. | UC-17 bước 4–5 |
| D10 | [Xác nhận] | Giặt lại và thuê ngoài | A1: `redo_of` Link Laundry Batch, chỉ cho lô `Failed`. A2: `batch_type = Outsourced` với `vendor` (Data) và `price_per_kg`; không cần máy/chương trình, `cost_total = kg × price_per_kg`, không trừ kho. | UC-17 A1, A2 |
| D11 | [Xác nhận] | RPC | `tracecore.v1.laundry.context` (GET: máy giặt/sấy Sẵn sàng, chương trình, định mức), `start` (POST `@idempotent`, tạo lô Running), `complete` (POST `@idempotent`, ghi sấy + kết quả, ghi sổ). Lệch so với bảng plan (`start/complete`): thêm `context` để màn đọc danh mục. | implementation-plan |
| D12 | [Xác nhận] | Báo cáo chi phí/kg theo tháng | Script Report `Laundry Cost per Kg` (tháng, số lô, kg, chi phí, chi phí/kg, số lô thiếu giá). | FR-M3-04.1 (Should) |
| D13 | [Xác nhận] | Quyền | `Laundry Batch`: R07 RWS; R05 RW (KTV, secondary actor); R02 RA; R01, R09, R10 R. Không offline (như FEAT-033). | CLAUDE.md |
| D14 | [Chốt] | Ngoài phạm vi | Thông báo/sự cố khi lô Không đạt (wash có `on_wash_failed`; UC-17 không nêu); đối chiếu thu – trả đồ vải (FEAT-035); điện sấy; dashboard (FEAT-006). | UC-17 |

## File structure

- Tạo: `tracecore/linen/doctype/{laundry_batch,laundry_batch_chemical}/`, `tracecore/linen/laundry.py`, `tracecore/linen/report/laundry_cost_per_kg/`
- Tạo: `tracecore/v1/laundry.py`, `tracecore/costing/from_laundry.py`
- Tạo: `tracecore/public/js/station_laundry.js`
- Tạo tests: `tracecore/linen/tests/test_laundry.py`, `tracecore/v1/tests/test_laundry_api.py`, `tracecore/inventory/tests/test_consume_laundry.py`, `tracecore/costing/tests/test_from_laundry.py`
- Sửa: `Equipment` (+`capacity_kg`), `Program Consumable` (+`qty_per_kg`), `fixtures/custom_field.json` (`Item.tc_is_disinfectant`), `inventory/consume.py`, `hooks.py`, `core/errors.py` + `core/tests/test_errors.py`, `station.js`, `tests/factories.py`, `permission_matrix.csv` + `custom_docperm.json`, `v1/navigation.py`, `translations/vi.csv`, `docs/architecture.md` (A-50), `docs/rtm.md`.

## Tasks

- [ ] **Task 0 — Amendment A-50 và tài liệu** (D3, D4, D6, D8): Revision History, ghi chú ở §5.3 (Laundry Batch, `capacity_kg`, `qty_per_kg`, `tc_is_disinfectant`).
- [ ] **Task 1 — Trường mới** (D3, D4, D6): `Equipment.capacity_kg`, `Program Consumable.qty_per_kg`, `Item.tc_is_disinfectant`; test hiển thị/validate.
- [ ] **Task 2 — Laundry Batch + dịch vụ `laundry.py`** (FR-M3-03.1–.4; BRU-LIN-001/003, BRU-EQP-002): test trước. Quy tắc: máy không Sẵn sàng/không phải máy giặt, quá tải, trộn nhiễm, < 71 °C không khử khuẩn; thuê ngoài; giặt lại.
- [ ] **Task 3 — Hoàn tất + hook** (FR-M3-03, D9): kết quả Đạt/Không đạt, sấy, ghi sổ, `tracecore_after_laundry_complete`.
- [ ] **Task 4 — Trừ hóa chất** (FR-M3-04; BRU-INV-002; D6, D7): `inventory.consume.on_laundry_complete`, idempotent, thiếu tồn theo A-46.
- [ ] **Task 5 — Chi phí/kg** (FR-M3-04, .2; D8): `costing/from_laundry.py`, thiếu giá/định mức vẫn hoàn tất kèm cảnh báo.
- [ ] **Task 6 — RPC `v1.laundry.*`** (D11, D13): `context`, `start`, `complete`; mã lỗi HTTP trong `core/errors.py` và test bảng mã; quyền và `navigation`.
- [ ] **Task 7 — UI trạm** (SCR-17; D1): `LaundryBatch` trong trạm `LIN`: tab, ô chọn máy/chương trình đầu trang, kg, cờ nhiễm, hóa chất, hai bước Bắt đầu và Hoàn tất, hiển thị chi phí/kg, 4 trạng thái loading/empty/error/offline, alert-error inline, nút ≥ 48 px.
- [ ] **Task 8 — Báo cáo + dịch + kiểm tra** (D12): Script Report, `vi.csv` (theo quy tắc ngữ cảnh DocType), lint, coverage ≥ 70 %, `rtm.md`, ghi chú hiện thực.

## Acceptance criteria (EARS) và test

| AC | Nội dung | Test |
| :- | :- | :- |
| AC-1 | Khi R07 tạo lô với máy giặt Sẵn sàng, chương trình, kg, cờ nhiễm, hệ thống tạo Laundry Batch `Running` (FR-M3-03) | `@bru("BRU-LIN-001")` |
| AC-2 | Nếu lô chứa cả đồ nhiễm và không nhiễm thì từ chối (FR-M3-03.1) | `@bru("BRU-LIN-003")` |
| AC-3 | Nếu lô Nhiễm, chương trình < 71 °C và không có hóa chất khử khuẩn thì từ chối (FR-M3-03.2) | `@bru("BRU-LIN-003")` |
| AC-4 | Nếu kg vượt tải máy thì từ chối (FR-M3-03.3) | `@bru("BRU-LIN-001")` |
| AC-5 | Khi máy ở trạng thái Khóa thì không chọn được (FR-M3-03.4) | `@bru("BRU-EQP-002")` |
| AC-6 | Khi hoàn tất, trừ hóa chất theo định mức × kg, idempotent (FR-M3-04) | `@bru("BRU-INV-002")` |
| AC-7 | Khi hoàn tất, hiển thị chi phí và chi phí/kg; thiếu giá/định mức thì cảnh báo và vẫn hoàn tất (FR-M3-04, .2) | `@bru("BRU-LIN-001")` |
| AC-8 | Lô Không đạt cho tạo lô giặt lại liên kết lô cũ (UC-17 A1) | `@bru("BRU-LIN-001")` |
| AC-9 | Báo cáo chi phí/kg theo tháng (FR-M3-04.1) | test report |

## Ghi chú hiện thực

**Kết quả (2026-10-29):** full suite 2838 test, 9 đỏ (7 fail, 2 error). Một lỗi do FEAT này (launcher thiếu bản dịch "Laundry Cost per Kg") đã sửa và chạy lại pass. 8 đỏ còn lại có sẵn trên develop, không thuộc FEAT này: `test_set_templates` (2 fail + 1 error `one_active_template`), `test_render_tag...` và `test_preview_png...` (nhóm nhãn), `test_imports_api.test_import_needs_create_permission_of_the_catalog`, `test_shifts.test_week_schedule...` (error), `test_station_page.test_vi_translations_do_not_override_other_apps` ('Audit Trail').
- Test mới: 26 (`test_laundry`) + 8 (`test_consume_laundry`) + 8 (`test_from_laundry`) + 6 (`test_laundry_access`) + 6 (`test_laundry_cost_report`) + 16 (`test_laundry_api`) + 24 (`test_laundry_station_assets`, chạy cả JS bằng Node).
- Coverage dòng đổi phía Frappe: 98,3 % (297/302), tính từ `coverage.xml` vì `diff-cover` chưa cài trong env.
- `pre-commit run` sạch.

**Khác với plan:**
- Quyền: ma trận SEC đã có sẵn dòng `DT-LAUNDRY` (R05 không có quyền); giữ nguyên, chỉ đổi R02 từ `RWS` sang `RWSA` (hủy/sửa đổi) và bỏ ghi chú "future". D13 trong bảng trên (R05 RW) không áp dụng.
- Trạm: thêm lớp `LinenStation` bọc hai màn `LinenCollect` và `LaundryBatch`, chuyển bằng thanh tab ở đầu màn; không thêm giá trị bước. Màn đang chờ máy chủ thì bỏ qua lần bấm tab (kết quả trả về sẽ vẽ đè lên màn khác).
- RPC `tracecore.v1.laundry.*` được thêm vào danh sách tiền tố gắn token phiên thẻ của `station.js` (thiếu dòng này thì máy chủ từ chối).
- `Process Program` trước đây bắt mỗi dòng tiêu hao có định mức theo lô hoặc theo gói; nay chấp nhận cả định mức theo kg (câu lỗi đổi, `vi.csv` đổi theo).
- Hoàn tất lô thuê ngoài: `laundry.complete` tự đặt `cost_total = kg x giá/kg`; hook costing và consume bỏ qua lô thuê ngoài.
- `Laundry Batch` ghi sổ (submit) khi hoàn tất; lô đang chạy là bản nháp (`docstatus = 0`, `status = Running`).

**Chưa làm / lưu ý:**
- Chưa thử tay màn kiosk trên trình duyệt (Desk cần OTP); chưa migrate site dev `tracecore-dev.local`.
- Chi phí sấy chưa tính (chương trình sấy chưa có định mức điện/nước).
- Chưa tạo sự cố/thông báo khi lô giặt Không đạt (UC-17 không nêu; wash có `on_wash_failed`).
- Máy giặt/sấy phải khai `capacity_kg` thì mới chặn quá tải; trống = không giới hạn (không cảnh báo trên màn).
- Hóa chất khử khuẩn cần tick `Item.tc_is_disinfectant` trên Desk; Item cũ mặc định không phải.
- Đơn vị tính "Nos" bắt số nguyên: định mức theo kg lẻ (vd 0,5 x 7 kg) sẽ bị ERPNext từ chối khi trừ kho; `inventory.consume` ghi lỗi và báo R09, lô vẫn hoàn tất (xem A-46).
- Lô giặt chưa liên kết với `Linen Collection` (spec FR-M3-03 không yêu cầu); kg do người vận hành nhập.
