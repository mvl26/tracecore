# FEAT-055 Vật tư KSNK theo lô — kế hoạch

> Nguồn: ticket quản lý vật tư KSNK theo tên + lô + hạn (liên quan #1866, #1865, #1845), Amendment A-112 (`docs/architecture.md`), FR-M6-02.4, FR-M6-03, FR-M6-03.5..10, FR-M2-03.10, FR-M2-09.10, FR-M6-07, FR-M6-08, BRU-INV-004, BRU-REP-018. Người dùng chốt 11 điểm trong chat ngày 03/11/2026 (A-112 D1–D11). #1845 không thuộc FEAT này (A-112 D15).
> Nhánh: `feat/FEAT-055-consumable-lots` (sau FEAT-054, dùng lại `Run Consumable` và `core.run_consumables`). Phần chọn lô và chỉ thị trừ đúng lô do một session khác bắt đầu, được gộp vào nhánh này.

## Acceptance criteria (EARS)

- AC-1 (FR-M6-03.6): Khi trạm lấy vật tư của chương trình, mỗi vật tư kèm tối đa 5 lô còn hạn, còn tồn, chưa tắt ở kho của bệnh viện của máy, hết hạn trước; không gửi lô thì dòng lấy lô đầu tiên; lô gõ, quét (tên lô hoặc mã GS1 có AI 10) hoặc chọn được lưu vào dòng cùng hạn dùng.
- AC-2 (FR-M6-03.7, BRU-INV-004): Lô không có trong kho, đã tắt, hết hạn, của vật tư khác hoặc chỉ còn ở kho của bệnh viện khác bị từ chối `CONSUMABLE_LOT_INVALID` (422); lô hết tồn, sắp hết hạn vẫn nhận (màn trạm cảnh báo).
- AC-3 (FR-M6-03, FR-M6-03.8): Lô rửa Đạt, mẻ giải phóng, test đầu ngày ghi kết quả thì kho trừ đúng lô của dòng; lô thiếu tồn chỉ trừ phần có, báo thiếu, không lấy lô khác; chỉ thị trừ theo `Pack.ci_batch` và lô của kết quả chỉ thị; CI/BI theo định mức chương trình không trừ.
- AC-4 (FR-M6-03.5): Dòng `Run Consumable` lưu `batch`, `expiry_date`.
- AC-5 (FR-M6-03.10): Test đầu ngày: không gõ lô thì lấy lô dòng Gói test; lô trùng Batch thì liên kết, hạn theo Batch, hết hạn bị chặn; lô ngoài kho giữ làm ghi chú. Kết quả chỉ thị: lô trong kho kiểm đúng nhóm chỉ thị và còn hạn, ngoài kho giữ làm ghi chú. Patch liên kết lô cũ trùng Batch.
- AC-6 (FR-M2-03.10, FR-M2-09.10, FR-M6-03.9, BRU-REP-018): R02 hủy lô rửa (chưa bộ nào qua T3, không Không đạt) / mẻ (gói chưa nhập kho, cấp phát, dùng, không Không đạt) có lý do: phiếu xuất hủy, Cost Sheet `Cancelled`, cổng T2/T5 về Chưa qua `step_gate.revert`, chu trình và bộ đếm bảo dưỡng trừ lại, gói về Đã đóng gói; quá mốc → `RUN_CANCEL_BLOCKED` (409) kèm bộ/gói; vai trò khác → 403; còn phiếu Nháp → từ chối.
- AC-7 (FR-M6-02.4): Form Item hiện chương trình đang dùng vật tư kèm máy, công đoạn, loại test, vai trò, định mức.
- AC-8 (FR-M6-07): `Consumable Usage` cho định mức, thực dùng, chênh lệch theo ngày/tháng, máy, công đoạn, loại test, vật tư, vai trò; bỏ nguồn đã hủy.
- AC-9 (FR-M6-08): `Consumable Lot Trace` từ một Batch ra mọi lô rửa, mẻ, test đầu ngày, phiếu xuất đã dùng lô, mẻ có số gói và link Pack Trace.
- AC-10 (tiêu chí ticket): test Bowie-Dick và mẻ tiệt khuẩn chọn đúng lô, không chọn được lô hết hạn, hoàn tất thì tồn đúng lô giảm đúng số thực dùng; truy vết từ lô ra các nguồn đó (test tích hợp `FrappeTestCase`, không E2E).

## Tasks (TDD)

1. Dữ liệu: `Run Consumable.batch/expiry_date`; `Daily Test.batch`, `Load Indicator Result.batch`; `Wash Batch`, `Sterilization Load`: `cancel_reason`, `cancelled_by`; `Cost Sheet.status` thêm `Cancelled`; patch `link_consumable_lots_a112`.
2. `core.lots` (`fefo`, `check`, `lot_code`), `run_consumables.company_of` (AC-1, AC-2). Test `core/tests/test_lots.py`.
3. `inventory.consume`: dòng trừ ghim lô của dòng, chỉ thị theo lô (AC-3). Test `inventory/tests/test_consume_lots.py`.
4. T2, T5, test đầu ngày, kết quả chỉ thị dùng lô; JS `station_consumables.js` (AC-1, AC-5). Test `reprocessing/tests/test_indicator_lots.py`, `test_consume_lots.py`, `tests/test_station_consumables_assets.py`.
5. Hủy: `step_gate.revert`, `reprocessing.run_cancel`, RPC `v1.wash.cancel`, `v1.load.cancel`, hook hủy (M6, M7, M1), nút Desk (AC-6). Test `reprocessing/tests/test_run_cancel.py`.
6. `inventory.usage`, RPC `v1.inventory.item_usage`, khối Item, `Consumable Usage`, `Consumable Lot Trace`, launcher (AC-7..9). Test `inventory/tests/test_consumable_reports.py`.
7. Bản dịch `vi.csv`, test toàn bộ, coverage changed-code ≥ 70 %, `pre-commit`.
