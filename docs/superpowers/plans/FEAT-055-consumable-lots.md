# FEAT-055 Vật tư KSNK theo lô — kế hoạch

> Nguồn: ticket quản lý vật tư KSNK theo tên + lô + hạn (liên quan #1866, #1865, #1845), Amendment A-112 (`docs/architecture.md`), FR-M6-02.4, FR-M6-03.5..10, FR-M2-03.10, FR-M2-09.10, FR-M6-07, FR-M6-08, BRU-INV-004, BRU-REP-018. Người dùng chốt 11 điểm trong chat ngày 03/11/2026 (A-112 D1–D11). #1845 không thuộc FEAT này (A-112 D15).
> Nhánh: `feat/FEAT-055-consumable-lots` (sau FEAT-054, dùng lại `Run Consumable` và `core.run_consumables`).

## Acceptance criteria (EARS)

- AC-1 (FR-M6-03.6): Khi trạm liệt kê vật tư của chương trình ở T2, T5 hoặc test đầu ngày, mỗi dòng vật tư có lô được điền sẵn lô còn hạn có tồn hết hạn sớm nhất ở kho của bệnh viện của máy; quét mã lô (tên Batch, `batch_id` hoặc GS1 AI 10) hoặc chọn trong danh sách thì đổi được lô; hạn dùng tự điền.
- AC-2 (FR-M6-03.7, BRU-INV-004): Lô hết hạn, khác vật tư hoặc khác bệnh viện bị từ chối `CONSUMABLE_LOT_INVALID` cả khi chọn và khi Hoàn thành nạp / Bắt đầu test; lô hết hạn trong 30 ngày hoặc tồn nhỏ hơn số thực dùng thì cảnh báo, vẫn làm tiếp.
- AC-3 (FR-M6-03.8): Hoàn tất lô/mẻ/test thì Material Issue trừ đúng lô đã chọn đúng số thực dùng; lô thiếu tồn thì trừ đến hết, phần thiếu báo `CONSUMPTION_SHORT`, không lấy lô khác. Dòng không có lô vẫn FEFO như trước.
- AC-4 (FR-M6-03.5): Dòng `Run Consumable` lưu `batch`, `expiry_date`, `lot_warning`, cùng các trường của A-111.
- AC-5 (FR-M6-03.10): `Daily Test.lot` và `Load Indicator Result.lot` là Link Batch, hạn tự điền; patch chuyển lô chữ khớp đúng một Batch, còn lại chép sang `lot_note`.
- AC-6 (FR-M2-03.10, FR-M2-09.10, FR-M6-03.9, BRU-REP-018): R02 hủy lô rửa (chưa bộ nào qua bước kế tiếp, không phải Không đạt) hoặc mẻ tiệt khuẩn (chưa gói nào nhập kho T6/cấp phát, không phải Không đạt) với lý do: phiếu xuất của nguồn bị hủy, Cost Sheet `Cancelled`, bộ/gói về bước trước qua `core.step_gate`, Audit Log; quá mốc thì `RUN_CANCEL_BLOCKED`; vai trò khác bị từ chối; còn phiếu Nháp thì chặn.
- AC-7 (FR-M6-02.4): Form Item hiện chương trình đang dùng vật tư kèm máy, công đoạn, loại test, vai trò, định mức.
- AC-8 (FR-M6-07): `Consumable Usage` cho định mức, thực dùng, chênh lệch theo ngày/tháng, máy, công đoạn, loại test, vật tư, vai trò; bỏ nguồn đã hủy.
- AC-9 (FR-M6-08): `Consumable Lot Trace` từ một Batch ra mọi lô rửa, mẻ, test đầu ngày, kết quả chỉ thị, phiếu xuất đã dùng lô, mẻ có số gói và link Pack Trace.
- AC-10 (tiêu chí ticket): chạy một test Bowie-Dick và một mẻ tiệt khuẩn: chọn đúng lô, không chọn được lô hết hạn, hoàn tất thì tồn đúng lô đó giảm đúng số thực dùng; truy vết từ lô ra hai nguồn đó.

## Tasks (TDD)

1. Dữ liệu: `Run Consumable.batch/expiry_date/lot_warning`; `Daily Test.lot`, `Load Indicator Result.lot` → Link Batch + `lot_note`; `Wash Batch`, `Sterilization Load`: `cancel_reason`, `cancelled_by`; `Cost Sheet.status` thêm `Cancelled`; patch chuyển lô cũ (AC-5); patch mã lỗi (D16).
2. `core.consumable_lots`: `candidates`, `resolve`, `check` (AC-1, AC-2). Test `core/tests/test_consumable_lots.py`.
3. `core.run_consumables`: payload/rows nhận `batch`, kiểm D2 lúc Hoàn thành nạp / Bắt đầu test, nhiều dòng cùng vật tư; `issue_lines` ghim lô; `inventory.consume.pick_lots` không lấy lô khác khi đã ghim (AC-3, AC-4). Test `inventory/tests/test_consume_lots.py`.
4. RPC `v1.consumables.lots/resolve_lot`; T2, T5, test đầu ngày, kết quả chỉ thị dùng lô (AC-1, AC-5). Test `reprocessing/tests/test_lot_pick_station.py`.
5. Hủy: `v1.wash.cancel`, `v1.load.cancel`, chuyển trạng thái trong `core.step_gate`, hook hủy → M6 hủy phiếu, M7 Cost Sheet (AC-6). Test `reprocessing/tests/test_run_cancel.py`.
6. Khối Item, `Consumable Usage`, `Consumable Lot Trace`, link workspace kho (AC-7..9). Test `inventory/tests/test_consumable_reports.py`.
7. UI trạm (`station_consumables.js`), Desk nút hủy, bản dịch `vi.csv`.
8. Test toàn bộ, coverage changed-code ≥ 70 %, `pre-commit`; kiểm AC-10 bằng test tích hợp `FrappeTestCase` (không E2E).
