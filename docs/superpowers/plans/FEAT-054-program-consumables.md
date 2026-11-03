# FEAT-054 Vật tư theo chương trình — kế hoạch

> Nguồn: ticket vật tư theo chương trình (liên quan #1865, #1847), Amendment A-111 (`docs/architecture.md`), FR-M5-02.6..8, FR-M2-03.9, FR-M2-09.9, FR-M5-05.5, FR-M6-03, FR-M6-03.5, BRU-INV-003. Người dùng chốt D1–D4 trong chat ngày 03/11/2026: trừ theo thực dùng, test đầu ngày trừ kho, CI/BI chỉ nhắc, mẫu bằng nút sao chép.
> Nhánh: `feat/FEAT-054-program-consumables` (tách từ FEAT-053 vì dùng chung khối Chương trình ở T2/T5).

## Acceptance criteria (EARS)

- AC-1 (FR-M5-02.6): Khi R10 khai vật tư chương trình, hệ thống phải lưu vai trò và cờ Bắt buộc; chương trình test gắn được loại test đầu ngày đúng loại máy.
- AC-2 (FR-M5-02.7): Khi áp vật tư sang chương trình cùng loại, bảng vật tư của chương trình đích phải giống nguồn; chương trình khác loại chương trình hoặc khác loại máy bị từ chối.
- AC-3 (FR-M5-02.8): Chương trình có vật tư bắt buộc định mức 0 có `norm_status = Missing`; báo cáo liệt kê chương trình không có vật tư, vật tư bắt buộc thiếu số, chương trình test chưa gắn loại test.
- AC-4 (FR-M2-03.9, FR-M2-09.9, FR-M5-05.5, BRU-INV-003): Chương trình có vật tư bắt buộc thì Hoàn thành nạp / Bắt đầu test thiếu xác nhận bị từ chối `CONSUMABLES_NOT_CONFIRMED`; số âm hoặc vật tư lạ bị từ chối `CONSUMABLE_INVALID`.
- AC-5 (FR-M6-03): Lô rửa Đạt, mẻ giải phóng, test đầu ngày ghi kết quả trừ kho theo số thực dùng; CI/BI không bị trừ.
- AC-6 (FR-M6-03.5): Dòng `Run Consumable` lưu định mức, thực dùng, người xác nhận, lô đã xuất.
- AC-7: Chọn chương trình Test Bowie-Dick hoặc test chân không ở T5 (test đầu ngày) hiện đúng vật tư; xác nhận xong, ghi kết quả thì trừ kho.

## Tasks (TDD)

1. Dữ liệu: `Program Consumable.role`, `is_required`; `Process Program.daily_test_type`; child `Run Consumable`; bảng `consumables` trên Wash Batch, Sterilization Load, Daily Test; `Daily Test.program`.
2. `core.run_consumables`: `lines_of`, `payload`, `rows`, `issue_lines`, `record_lots` (AC-4, AC-6). Test `core/tests/test_run_consumables.py`.
3. `norms.norm_status` (AC-3), báo cáo `Program Consumable Gaps`, `programs.copy_consumables` + RPC (AC-2).
4. T2 `washing.start`, T5 `sterilizing.complete`, test `daily_test.start_run`/`record` + hook (AC-4, AC-7). Test `reprocessing/tests/test_run_consumables_station.py`.
5. `inventory.consume`: dòng trừ từ `Run Consumable`, nguồn Daily Test, bỏ CI/BI, ghi lô (AC-5, AC-6). Test `inventory/tests/test_consume_actual.py`.
6. UI T2, T5, test đầu ngày, Desk Process Program; bản dịch.
7. Test, coverage changed-code ≥ 70 %, `pre-commit`.
