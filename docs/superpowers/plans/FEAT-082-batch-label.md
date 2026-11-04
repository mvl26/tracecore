# FEAT-082 Nhãn mã vạch cho lô vật tư/chỉ thị — kế hoạch

> Nguồn: Amendment A-118 (`docs/architecture.md`), FR-M6-09; bổ sung A-112 (`core.lots.lot_code`), A-114 (PDF, một máy in nhãn chung), A-116 (khổ 50 × 30 mm). Người dùng chốt 04/11/2026: in nhãn mã vạch cho từng lô.
> Nhánh: `feat/FEAT-082-batch-label` trong `apps/tracecore`, tạo từ `develop` sau khi nhánh `docs/A-118-lot-barcode-label` được duyệt và merge.

## Hiện trạng

- Mọi ô lô ở trạm nhận chuỗi quét trùng tên `Batch` nguyên văn, hoặc AI (10) của mã GS1 (`core/lots.py` `lot_code`). Chưa có đường in nhãn mã vạch cho `Batch`.
- Nhãn QR đối tượng đã chạy qua `core.print.OBJECT_LABELS`, `core.label_pdf.object_pdf`, RPC `tracecore.v1.print.object_label` và hộp thoại `tracecore.codes.print_dialog` (`public/js/tc_codes.js`); `object_code_problem` kiểm định dạng mã theo loại đối tượng.

## Acceptance criteria (EARS)

- **AC-1** (FR-M6-09): Khi người dùng in nhãn của một `Batch` còn hạn, chưa vô hiệu, hệ thống phải trả PDF khổ nhãn chung có QR giải ra đúng tên lô, kèm tên lô, tên vật tư và hạn dùng `dd/mm/yyyy`.
- **AC-2** (FR-M6-09): Nếu `Batch` không tồn tại, đã vô hiệu hoặc đã hết hạn, thì hệ thống phải từ chối với `alert-error` nêu kết quả, lý do, hành động và không tạo `Print Job`.
- **AC-3** (FR-M6-09): Khi quét QR của nhãn ở ô lô chỉ thị, hệ thống phải nhận đúng lô như khi gõ tên lô (`lots.lot_code` trả đúng tên lô).
- **AC-4** (FR-M6-09): Danh sách `Batch` phải có hành động hàng loạt "In nhãn QR" in một PDF nhiều trang, lô không in được liệt kê kèm lý do.
- **AC-5** (A-118 d): Mỗi lần in phải ghi `Print Job` với `label_object = Batch Label`, `ref_name` = tên lô; không đổi trạng thái nghiệp vụ.

## Tasks (TDD: viết test `FrappeTestCase` trước, thấy fail, rồi code)

1. **Đối tượng nhãn `Batch Label`** (AC-1, AC-2, AC-5)
   - [ ] Test: `test_batch_code_is_printable`, `test_unknown_or_disabled_batch_is_refused`, `test_expired_batch_is_refused`, `test_pdf_qr_decodes_to_the_batch_name`, `test_print_job_is_written`. Thấy fail.
   - [ ] Thêm `Batch Label` vào `OBJECT_LABELS`; `object_code_problem` nhận tên Batch hợp lệ; `label_pdf.object_pdf` dựng nhãn lô (tên lô, vật tư, hạn); chuỗi dịch vào `vi.csv`.
2. **Quét lại nhãn** (AC-3)
   - [ ] Test `lots.lot_code(<tên lô>)` giữ nguyên với tên có ký tự `-`, số, chữ hoa.
3. **UI Desk** (AC-1, AC-4)
   - [ ] Nút "In nhãn QR" trên form Batch và hành động hàng loạt ở danh sách, dùng `tracecore.codes.print_dialog`/`add_print_button` có sẵn (`tc_codes.js`, hook `doctype_js`/`doctype_list_js`).
4. **Hoàn tất:** test các module trên + `test_print`, `test_label_pdf`, `test_codes_api`; `pre-commit`; coverage changed-code ≥ 70 %; không chạy E2E, không tạo PR; ghi rõ cần in thử trên cuộn 50 × 30 thật.
