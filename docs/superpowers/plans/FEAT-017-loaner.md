# FEAT-017 — Bộ mượn (loaner)

**Đầu vào:** implementation-plan §3 FEAT-017 (FR-M1-07, FR-M1-08; FR-M1-05.5; UC-04; SCR-04), Amendment **A-38**
(architecture Revision History, 2026-10-26: Set ID GIAI series LN, tự tạo loại bộ mượn, trạng thái `Returned`).

**Nhánh:** `feat/FEAT-017-loaner` (từ develop local). Không PR; merge vào develop local, không push.

## Task 1 — Mô hình

- DocType `Loaner Set` (module Instrument, `MU-.YYYY.-.#####`, submittable, không hủy) + child `Loaner BOM Item`
  (`instrument_name`, `qty`, `instrument` (đọc), `returned_qty`, `damaged_qty`, `note`).
- Trường: `supplier` (Link Supplier), `set_name`, `method` (Steam/Plasma), `gtin`, `pack_type` (Link Item), `department`,
  `received_on`, `expected_return`, `ifu` (Attach), `status` (Draft/Received/Returned), `set_type`, `set_unit` (đọc),
  phần trả (`returned_on`, `returned_by`, `return_note`, `missing_count`, `damaged_count`, `incident`),
  `extension_reason`, `last_reminded_on`. Trường dịch vụ chỉ ghi qua cờ `flags.tc_loaner`.
- `Set Unit.status` thêm `Returned`; `Set Unit.autoname` dùng mã loại `LN` khi `is_loaner`.
- Ma trận quyền: dòng DT-LOANER đổi tên DocType thành `Loaner Set`.

## Task 2 — Nhận bộ mượn (FR-M1-07, FR-M1-05.5; UC-04 bước 1–3)

- `instrument.loaner.receive` (on_submit): kiểm R02, ngày trả ≥ ngày nhận, ≥ 1 dòng BOM, GTIN hợp lệ.
- Dụng cụ `LNI-#####` theo (hãng, tên); loại bộ `LN#####` (dùng lại theo GTIN; BOM khác → phiên bản mới).
- Một Set Unit `is_loaner`, Set ID `<prefix>LN<6 số>`; `status` Received; Print Format `TC Loaner Receipt`.
- Test: `instrument/tests/test_loaner.py::TestReceive`.

## Task 3 — Chặn trước tái xử lý đầy đủ (FR-M1-07.1, FR-M1-08, .08.1, .08.3)

- Không thêm cổng: test chứng minh bộ mượn Mới nhận bị cổng T4 chặn (kèm trạng thái), qua T1–T3 thì đóng gói như bộ
  thường, nhãn có `is_loaner`.

## Task 4 — Trả hãng (FR-M1-07.2, .07.3; UC-04 bước 5–6, E3)

- `instrument.loaner.return_set(name, lines, note)`: R02; bộ phải Vô khuẩn (`LOANER_NOT_REPROCESSED` kèm trạng thái);
  số trả/hỏng hợp lệ từng dòng; `step_gate.return_loaner` → `Returned`; Set ID `Disabled`.
- Hook `tracecore_after_set_status` (M2 `storage.on_set_returned`): gói kho của chu trình hiện hành → Void
  `Returned Unused`, mã `Disabled`.
- Thiếu dụng cụ → hook `tracecore_loaner_returned` (M2 `incidents.on_loaner_returned`) tạo NC Missing Instrument.
- Print Format `TC Loaner Return` liệt kê thiếu/hỏng.

## Task 5 — Gia hạn và quá hạn (UC-04 A2, E1; FR-M1-07.4)

- `extend(name, expected_return, reason)`: R02, lý do bắt buộc, ngày mới ≥ ngày nhận; Audit.
- `remind_overdue` (daily): Received và quá ngày trả → Notification Log R02, mỗi ngày một lần.

## Task 6 — RPC, Desk, dịch

- `tracecore.v1.loaner.receive / return_set / extend` (body `ok: false` khi chặn).
- `loaner_set.js`: nút Ghi sổ (nhận), Lập biên bản trả, Gia hạn, In biên bản; link mở Set Unit.
- `vi.csv` có ngữ cảnh cho từ chung.

## Xong khi

Test module pass, full suite không thêm lỗi so với develop (15 lỗi inventory có sẵn), pre-commit sạch, migrate hai site,
kiểm tay form Loaner Set trên 8300.
