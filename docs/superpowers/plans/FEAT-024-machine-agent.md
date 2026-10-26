# FEAT-024 — Dữ liệu máy tự động qua station agent

**Đầu vào:** implementation-plan §3 FEAT-024 (FR-M2-24 full; EI-SW-001, NFR-INT-01; UC-06 bước 4, UC-09 A3; SCR-06,
SCR-09), ADR-007, Amendment **A-39** (architecture Revision History, 2026-10-26).

**Nhánh:** `feat/FEAT-024-machine-agent` (từ develop local). Không PR; merge vào develop local, không push.

## Task 1 — Server: nhận dữ liệu chu trình (FR-M2-24, EI-SW-001)

- `tracecore.reprocessing.machine_data.ingest(station, equipment, cycle)`:
  - máy `is_connected`, cùng khu với trạm agent (`MACHINE_NOT_CONNECTED`, `MACHINE_NOT_AT_STATION`);
  - khớp theo `load_id` (chính xác) hoặc khoảng ±30 phút quanh giờ bắt đầu (mờ → `needs_review`);
    không khớp → `MACHINE_CYCLE_UNMATCHED`;
  - tham số theo `Program Parameter` (ngoài dải → `needs_review`), thiếu → `data_complete = 0` + danh sách thiếu;
  - mẻ tiệt khuẩn đủ dữ liệu → `Cycle Complete`, kết quả máy → `cycle_result` (`result_source = Auto`);
  - không ghi đè dữ liệu nhập tay đã đủ (`MACHINE_DATA_EXISTS`); cùng `cycle_ref` → trả kết quả cũ.
- RPC `tracecore.v1.load.ingest_machine_data` (TC Agent, đúng trạm, `@idempotent`).
- Test: `reprocessing/tests/test_machine_data.py`.

## Task 2 — Agent: driver và vòng quét (ADR-007)

- `tracecore_agent/drivers/`: `base.CycleData`, `Driver`; `csv_generic` (thư mục, glob, ánh xạ cột, định dạng giờ,
  múi giờ, cột tham số `param.<tên>`); `api_stub`.
- `config`: đọc các mục `[machine:<TB-####>]`.
- `machines.MachinePoller`: SQLite `machine_cycles` (đã gửi / chờ khớp), gửi lại chu trình chưa khớp tới 24 giờ.
- `client.ingest_machine_data`; `cli serve` quét 60 giây một lần; lệnh `machines` quét một lượt.
- Test: `tracecore_agent/tests/test_drivers.py`, `test_machines.py` (pytest, stub server).

## Task 3 — Kiosk

- T2 / T5: chữ nguồn dữ liệu "Tự động (station agent)" khi `data_source = Auto`, kèm "Cần xem xét".

## Xong khi

Test Frappe và pytest agent pass, full suite không thêm lỗi so với develop, pre-commit sạch, migrate hai site.
