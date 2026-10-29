# FEAT-043 Kiểm kê và cảnh báo tồn dưới tối thiểu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** R06 lập phiếu kiểm kê (ERPNext `Stock Reconciliation`) với số thực tế theo lô, hệ thống hiện chênh lệch theo lô, yêu cầu lý do khi lệch > 10 %, chỉ R02/R09 được duyệt (ghi sổ), khóa xuất nhập thủ công của kho trong lúc phiếu còn mở và cho in phiếu. Hằng ngày hệ thống cảnh báo vật tư dưới tồn tối thiểu của kho và lô sắp hết hạn trong 30 ngày (dashboard + email cho R09), liệt kê vật tư chưa cấu hình tồn tối thiểu, và tạo đề nghị mua (`Material Request`) trong một chạm từ cảnh báo.

**Architecture:** Module `Inventory` (M6) thêm dịch vụ `tracecore/inventory/count.py` (luật phiếu kiểm kê, khóa kho) và `tracecore/inventory/alerts.py` (tính cảnh báo, job hằng ngày, đề nghị mua), Script Report `Stock Alerts`, Print Format `TC Stock Count Sheet`; RPC mới `tracecore.v1.stock.alerts` / `create_purchase_request` cạnh `v1.stock` (FEAT-042). Không DocType mới (architecture §5.3: Stock Count **thay bằng** ERPNext Stock Reconciliation). Cảnh báo đi qua `core.notification.emit` (FEAT-010). Không import chéo module.

**Tech Stack:** Frappe v15 / ERPNext v15, Python 3.11, JS thuần trong Script Report. Không chạy E2E trừ khi được bảo.

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-043; `docs/srs.md` FR-M6-05 (.1, .2), FR-M6-06 (.1–.3); `docs/use-cases.md` UC-26; `docs/ux-foundations.md` SCR-26; `docs/architecture.md` §5.3 (Stock Count → Stock Reconciliation), WF-09.

FR/BRU đáp ứng: FR-M6-05, FR-M6-05.1, FR-M6-05.2, FR-M6-06, FR-M6-06.1–.3.

**Nhánh:** `feat/FEAT-043-stock-count` cắt từ `develop` (616cf1a). Số amendment: **A-52** (A-50 là FEAT-034; A-51 chừa cho FEAT-035).

## Quyết định cần duyệt

**[Chốt]** = tài liệu thiếu hoặc mâu thuẫn, cần người duyệt. **[Xác nhận]** = lựa chọn thiết kế trong phạm vi tài liệu.

| # | Loại | Câu hỏi | Phương án trong plan | Căn cứ |
| :- | :- | :- | :- | :- |
| C1 | [Xác nhận] | Phiếu kiểm kê | Dùng ERPNext `Stock Reconciliation` (architecture §5.3 "Thay"); không tạo DocType `Stock Count`. Chênh lệch theo lô có sẵn ở từng dòng (`current_qty`, `qty`, `quantity_difference`). Kiểm kê một phần (UC-26 A1) = chỉ liệt kê các vật tư cần kiểm. | architecture §5.3 |
| C2 | [Chốt] | "Phê duyệt R02/R09" | Không dùng Frappe Workflow (CLAUDE.md: Workflow chỉ để hiển thị). Phân quyền: R06 tạo/sửa bản nháp, chỉ R02 và R09 có quyền ghi sổ (`submit`) và hủy. Ghi sổ chính là phê duyệt. R06 muốn ghi sổ phải nhờ R02/R09. | FR-M6-05.1; CLAUDE.md |
| C3 | [Chốt] | Lý do khi lệch lớn (UC-26 E1) | Thêm Custom Field `Stock Reconciliation Item.tc_variance_reason` (Data). Dòng có tồn hệ thống > 0 và \|chênh lệch\| > 10 % tồn hệ thống bắt buộc có lý do khi lưu; thiếu thì chặn. Dòng tồn hệ thống 0 (lô mới thấy) không áp dụng. | UC-26 E1 |
| C4 | [Chốt] | Khóa xuất nhập khi phiếu mở (FR-M6-05.2) | "Mở" = `Stock Reconciliation` còn Nháp có dòng thuộc kho đó. Khi đó chặn tạo/ghi sổ `Stock Entry` **thủ công** (không có `tc_source_doctype`, hoặc `tc_source_doctype = Manual Issue`) có kho nguồn/đích trùng. **Không chặn** Stock Entry tiêu hao tự động của lô rửa/mẻ/lô giặt (FEAT-042): chặn sẽ làm mất khoản trừ vì tiêu hao chỉ chạy một lần. Hạn chế ghi rõ: nên kiểm kê khi không có lô đang hoàn tất; ERPNext tính chênh lệch lúc ghi sổ. | FR-M6-05.2; A-46 |
| C5 | [Xác nhận] | Một kho một phiếu mở | Không cho tạo phiếu kiểm kê thứ hai khi kho đã có phiếu Nháp (UC-26 tiền điều kiện). | UC-26 |
| C6 | [Xác nhận] | Lô không tồn tại (E2) | ERPNext đã chặn Link `Batch` không có và lô không thuộc vật tư; giữ nguyên, thêm test. | UC-26 E2 |
| C7 | [Chốt] | "Tồn tối thiểu" của kho | Dùng bảng `reorder_levels` của `Item` (FEAT-041: `warehouse`, `warehouse_reorder_level`) làm tồn tối thiểu theo kho; cảnh báo khi `Bin.actual_qty` < mức đó. `warehouse_reorder_qty` là số lượng đề nghị mua, trống thì bằng phần thiếu. | FR-M6-06; FEAT-041 |
| C8 | [Xác nhận] | Vật tư chưa có tồn tối thiểu (FR-M6-06.3) | Vật tư nhóm CSSD (`tc_item_group_cssd` có giá trị) chưa có dòng tồn tối thiểu nào: không cảnh báo tồn, đưa vào danh sách "Thiếu cấu hình" trong báo cáo. | FR-M6-06.3 |
| C9 | [Xác nhận] | Lô sắp hết hạn (FR-M6-06.1) | Lô có `expiry_date` trong 30 ngày tới (hoặc đã quá hạn) và còn tồn > 0, vật tư nhóm CSSD. | FR-M6-06.1 |
| C10 | [Chốt] | "Dashboard" | FEAT-006 (dashboard theo vai trò) chưa làm. FEAT-043 cung cấp Script Report `Stock Alerts` (ba loại: Dưới tồn tối thiểu, Sắp hết hạn, Thiếu cấu hình) thay dashboard; FEAT-006 sẽ nhúng lại. | FEAT-006 chưa có |
| C11 | [Xác nhận] | Email | Job `inventory.alerts.run_daily` (cron 06:00) gửi `core.notification.emit` hai sự kiện mới: `STOCK_BELOW_MIN` và `BATCH_EXPIRING`, mặc định email cho R09, mỗi cặp (vật tư, kho)/lô một thông báo mỗi ngày còn vi phạm. Đối tượng liên kết là `Item` / `Batch`. | FR-M6-06 |
| C12 | [Xác nhận] | Đề nghị mua một chạm (FR-M6-06.2) | RPC `tracecore.v1.stock.create_purchase_request(item, warehouse)` (POST `@idempotent`, R09/R02) tạo `Material Request` loại Purchase **Nháp** một dòng; đã có Nháp mở cho cặp đó thì trả lại, không tạo thêm. Nút "Tạo đề nghị mua" trên từng dòng báo cáo. | FR-M6-06.2 |
| C13 | [Xác nhận] | In phiếu (FR-M6-05) | Print Format `TC Stock Count Sheet` (A4) cho `Stock Reconciliation`: kho, ngày, từng dòng vật tư/lô, tồn hệ thống, thực tế, chênh lệch, lý do, ô ký R06 và duyệt R02/R09. | FR-M6-05 |
| C14 | [Chốt] | Ngoài phạm vi | Dự báo tiêu hao 3 tháng (UC-26 A2); quét mã lô nhập số thực tế trên PDA (UC-26 bước 2 nói "quét mã lô": Desk có ô quét ERPNext sẵn có); Frappe Workflow WF-09. | FR-M6-05 (Should) |

## File structure

- Tạo: `tracecore/inventory/count.py`, `tracecore/inventory/alerts.py`, `tracecore/inventory/report/stock_alerts/`, `tracecore/inventory/print_format/tc_stock_count_sheet/`
- Tạo tests: `tracecore/inventory/tests/test_count.py`, `test_alerts.py`, `test_stock_alerts_report.py`, `tracecore/v1/tests/test_purchase_request_api.py`
- Sửa: `fixtures/custom_field.json` (`tc_variance_reason`), `inventory/permissions.py` (Stock Reconciliation, Material Request), `hooks.py` (doc_events, scheduler), `core/notification/__init__.py` (hai sự kiện), `v1/stock.py`, `core/errors.py` + `core/tests/test_errors.py`, `v1/navigation.py`, `translations/vi.csv`, `docs/architecture.md` (A-52), `docs/rtm.md`.

## Tasks

- [ ] **Task 0 — Amendment A-52 và tài liệu** (C1–C14).
- [ ] **Task 1 — Phiếu kiểm kê** (FR-M6-05, .1; C2, C3, C5, C6): quyền (R06 tạo, R02/R09 ghi sổ), lý do khi lệch > 10 %, một kho một phiếu mở.
- [ ] **Task 2 — Khóa kho khi phiếu mở** (FR-M6-05.2; C4).
- [ ] **Task 3 — Cảnh báo tồn và hạn** (FR-M6-06, .1, .3; C7–C9): `below_minimum`, `expiring_batches`, `unconfigured_items`.
- [ ] **Task 4 — Job hằng ngày và thông báo** (FR-M6-06; C11): hai sự kiện, cron, không gửi cho vật tư thiếu cấu hình.
- [ ] **Task 5 — Đề nghị mua một chạm** (FR-M6-06.2; C12): service + RPC + mã lỗi.
- [ ] **Task 6 — Script Report `Stock Alerts`** (SCR-26; C10) và nút tạo đề nghị mua.
- [ ] **Task 7 — Print Format, menu, dịch, kiểm tra** (C13): lint, coverage, `rtm.md`, ghi chú hiện thực.

## Acceptance criteria (EARS) và test

| AC | Nội dung | Test |
| :- | :- | :- |
| AC-1 | Khi R06 lập phiếu kiểm kê, hệ thống hiện chênh lệch theo lô (FR-M6-05) | `@bru("BRU-INV-002")` không áp dụng; test `test_count.py` |
| AC-2 | Chỉ R02/R09 ghi sổ được phiếu kiểm kê (FR-M6-05.1) | test quyền |
| AC-3 | Khi phiếu kiểm kê của kho còn mở, chặn Stock Entry thủ công của kho đó, không chặn tiêu hao tự động (FR-M6-05.2) | test khóa |
| AC-4 | Chênh lệch > 10 % phải có lý do (UC-26 E1) | test lý do |
| AC-5 | Vật tư dưới tồn tối thiểu của kho được cảnh báo (FR-M6-06) | test `below_minimum` + thông báo |
| AC-6 | Lô hết hạn trong 30 ngày được cảnh báo (FR-M6-06.1) | test `expiring_batches` |
| AC-7 | Tạo đề nghị mua một chạm, không tạo trùng (FR-M6-06.2) | test RPC |
| AC-8 | Vật tư chưa có tồn tối thiểu không cảnh báo tồn, ghi vào thiếu cấu hình (FR-M6-06.3) | test `unconfigured_items` |
| AC-9 | In được phiếu kiểm kê (FR-M6-05) | test Print Format |

## Ghi chú hiện thực

**Kết quả (2026-10-29):** xem số liệu full suite, coverage ở cuối mục này (điền sau khi chạy xong).

**Review độc lập (sub-agent, chỉ đọc) và đã sửa:**
- Phiếu kiểm kê Nháp bị bỏ quên khóa kho mãi: Frappe không cho hủy bản Nháp, plan lại gỡ quyền xóa. Thêm cờ `tc_abandoned` (phiếu bỏ dở không khóa kho, không ghi sổ được, vẫn lưu hồ sơ).
- Script Report bị từ chối với R09/R02/R06: Frappe đòi quyền `report` trên `ref_doctype`; đổi từ `Item` sang `Stock Reconciliation` (R10 bỏ khỏi báo cáo vì không có `report`), R01 thêm quyền đọc `Warehouse` vì cột Link. Thêm test chạy `frappe.desk.query_report.run` dưới từng vai trò.
- Đề nghị mua trùng khi bản đã ghi sổ chưa đặt đủ hàng: chặn tạo thêm; R09 xóa được bản Nháp nhập nhầm.
- Nút tạo đề nghị mua chỉ hiện với R09/R02; nhãn loại cảnh báo được dịch; câu thông báo lô đọc "còn ... trong kho" thay vì "left".

**Khác với plan / hạn chế đã biết:**
- Ma trận SEC cho R05 và R07 quyền lập (RW) phiếu kiểm kê; giữ nguyên, chỉ R02/R09 ghi sổ.
- Khóa kho chỉ phủ `Stock Entry` thủ công (không phủ Purchase Receipt, Delivery Note, nhập xuất qua Material Request) và so khớp tên kho chính xác (không xét kho cha); tiêu hao tự động của FEAT-042 vẫn chạy khi kho đang kiểm kê.
- Hai yêu cầu tạo đề nghị mua đồng thời, khác khóa idempotent, có thể cùng tạo một bản Nháp mỗi bên (không có khóa DB theo cặp vật tư/kho).
- `below_minimum` dùng `Bin.actual_qty` (gồm cả lô quá hạn còn tồn, không xét kho nhóm); `unconfigured_items` chỉ xét vật tư không có mức ở bất kỳ kho nào.
- Dòng kiểm kê dùng Serial and Batch Bundle (thay vì `use_serial_batch_fields`) chưa có test.
- Lô sắp hết hạn tổng hợp qua nhiều kho nhưng chỉ ghi kho của lô đầu tiên.
- Chưa thử tay trên trình duyệt (Desk cần OTP); chưa migrate site dev `tracecore-dev.local`.
