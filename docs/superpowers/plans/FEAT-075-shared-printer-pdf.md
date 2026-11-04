# FEAT-075 Một máy in nhãn chung, in PDF qua hộp thoại In — kế hoạch

> Nguồn: Amendment A-114 (`docs/architecture.md`), FR-M2-08, FR-M2-08.1, FR-M2-08.2, FR-M2-08.3, FR-M2-08.8, FR-M1-05.3, FR-M1-05.4, FR-M10-01.5, EI-HW-002, EI-HW-003, EI-HW-007, EI-HW-008, NFR-AVAIL-04, BRU-REP-011 (thu hẹp), BRU-ID-005. Người dùng duyệt A-114 ngày 04/11/2026.
> Nhánh: `feat/FEAT-075-shared-printer-pdf` trong `apps/tracecore`, tạo từ `develop` sau khi nhánh `docs/A-114-in-pdf-may-in-chung` được merge.

## Hiện trạng (khảo sát code ngày 04/11/2026)

- **T2, T5, T4:** nhãn đã ra PDF do máy chủ dựng (`core/label_pdf.py`, wkhtmltopdf), nhưng trình duyệt **tải file** (`station_error.js` `tcSavePdf` :9-19). Nút In chỉ hiện khi job `Queued`. Trạm không có `Printer` riêng thì job `Waiting` với `NO_PRINTER_AT_STATION` (T2/T5, `object_printer`). Gói T4 không có máy in đúng phương pháp thì job `Waiting` với `NO_PRINTER_FOR_METHOD` (`select_printer`), chờ quét cuộn (`set_roll` → `_release_waiting_jobs`).
- **Thẻ bộ Set ID, nhãn QR đối tượng (Desk):** dựng ZPL, gửi qua TCP từ máy chủ (`print_server.enqueue_server_dispatch*`, cron `dispatch_pending` mỗi phút). Người dùng phải chọn máy in có `host`.
- **Nhãn chất thải `CT-`:** `waste/collection.py` `_queue_label` tạo job `Queued` có ZPL nhưng **không có đường nào gửi đi**, nên thực tế chưa bao giờ in được.
- **Station Agent:** không JS nào gửi ZPL tới `127.0.0.1:8765/print`; agent chỉ còn đọc cân (`tc_weigh_line.js`).
- **Giấy tờ A4:** biên nhận chất thải, đồ vải, phiếu bàn giao đã mở `/printview?…&trigger_print=1` (hộp thoại In). Phiếu cấp phát T7 (`issuing.print_url`) chưa có `trigger_print`. Phiếu kiểm đếm mở PDF ở tab mới. Sổ tiệt khuẩn xuất file qua RQ.
- **Không có nhãn đồ vải** (đã bỏ khỏi A-114).
- Site `yhct` hiện có đúng một `Printer` `PRN-001` gắn TR-004.

## Câu hỏi mở — phải chốt trước khi code

- **Q1. Khổ nhãn chung.** Một máy, một cuộn thì mọi nhãn nên cùng một khổ. Hiện tại khổ đang khác nhau:

  | Nhãn | Khổ hiện tại |
  | --- | --- |
  | Mẫu ZPL gói | 60 × 40 mm (A-109) |
  | Mẫu ZPL nhãn đối tượng | 50 × 30 mm (A-05) |
  | PDF lô rửa / mẻ | 80 × 45 mm (`label_pdf.PAGE_*`) |
  | PDF gói | rộng 100 mm, cao ≥ 60 mm (`PACK_PAGE_*`) |

  **Đề xuất:** một khổ cấu hình được, `TraceCore Settings.label_width_mm` / `label_height_mm`, mặc định 60 × 40 mm. Mọi PDF nhãn dùng khổ này; nội dung co theo khổ. Nếu chọn hướng này thì A-114 (d) phải sửa câu "khổ trang PDF bằng khổ nhãn của mẫu".

## Acceptance criteria (EARS)

- **AC-1** (FR-M2-08.2): Khi R10 chọn máy in nhãn chung trong TraceCore Settings, hệ thống phải lưu lựa chọn. Khi đó mọi Print Job mới không có máy in riêng của trạm phải ghi máy in chung.
- **AC-2** (FR-M2-08.1, A-114 a): Khi lô rửa, mẻ hoặc gói hoàn tất tại trạm không khai máy in, hệ thống phải tạo Print Job `Queued` và trả PDF khi gọi `label_pdf`. Hệ thống không được trả `NO_PRINTER_AT_STATION` hay `NO_PRINTER_FOR_METHOD`.
- **AC-3** (BRU-REP-011 thu hẹp, FR-M2-08.3): Khi in nhãn gói Plasma trong lúc máy in chung khai đang lắp nhãn hấp, hệ thống phải không chặn. Mẫu nhãn vẫn theo phương pháp của gói. Tiêu hao nhãn trừ theo `label_type_loaded` nếu có khai, không khai thì không trừ.
- **AC-4** (FR-M2-08, EI-HW-002): Khi người dùng bấm In (nhãn hoặc giấy tờ), trang phải mở hộp thoại In của trình duyệt với PDF và không tải file về máy.
- **AC-5** (FR-M2-08.8, EI-HW-008, FR-M1-05.4):
  - Nếu máy chủ không dựng được PDF, hệ thống phải trả `LABEL_PDF_FAILED`, giữ mã và Print Job, để nút In lại.
  - Nếu trình duyệt không mở được hộp thoại In, trang phải hiện cảnh báo inline kèm nút Mở PDF ở tab mới.
- **AC-6** (A-114 g): Khi PDF được đưa ra hộp thoại In, Print Job phải có `status = Printed`, `output_mode = Browser` và `attempts` tăng 1.
- **AC-7** (FR-M1-05.3, FR-M1-05.4):
  - Khi in thẻ cho nhiều bộ, hệ thống phải trả một PDF nhiều trang.
  - In lại thẻ vẫn bắt buộc lý do, và số lần in đếm từ Print Job.
  - Không xuất được PDF thì Set ID vẫn giữ.
- **AC-8** (FR-M10-01.5): Khi lượt thu gom chất thải được ghi sổ tại trạm, màn trạm phải có nút In nhãn cho các túi/thùng `CT-` của lượt đó và trả một PDF nhiều trang.
- **AC-9** (A-114 d): Khi R10 in nhãn QR đối tượng (máy, trạm, kệ, cuộn, thẻ nhân viên) trên Desk, hệ thống phải trả PDF, không bắt chọn máy in, không gửi ZPL.
- **AC-10** (A-114 f): Hệ thống phải không còn job cron `print_server.dispatch_pending` và không gửi ZPL qua TCP.
- **AC-11** (A-114 c): Khi chạy patch, mọi Print Job `Waiting` phải chuyển `Queued`, sau đó in được bằng PDF.
- **AC-12** (FR-M2-08.5, FR-M2-08.6, BRU-ID-005): In lại nhãn gói ở T4 vẫn cần lý do, trong 10 phút, và tăng `label_print_count`. Quá 10 phút thì vẫn `REPRINT_WINDOW_EXPIRED`.
- **AC-13** (A-114 e): Khi bấm In phiếu cấp phát ở T7, trang phải mở hộp thoại In (`trigger_print=1`) như các biên nhận khác.
- **AC-14:** Mọi chuỗi mới đi qua `_()` / `__()` và có trong `translations/vi.csv`.

## Tasks (TDD: viết test `FrappeTestCase` trước, thấy fail, rồi mới code)

1. **Dữ liệu** (FR-M2-08.2; AC-1)
   - `TraceCore Settings`: thêm section "In ấn" với `label_printer` (Link Printer). Nếu Q1 chọn đề xuất thì thêm cả `label_width_mm`, `label_height_mm`.
   - `Printer.station`: bỏ `reqd`. `_validate_station` chỉ kiểm khi có giá trị.
   - `Print Job.station`: bỏ `reqd`, vì Desk in bằng máy chung có thể không có trạm.
   - `Print Job.output_mode`: thêm `Browser`.
   - `Print Job.validate`: bỏ ràng buộc "`Queued` phải có `payload`". Job PDF không cần ZPL.
   - Test: `tracecore/doctype/printer/test_printer.py`, test Print Job.
2. **`core.print` chọn máy in** (AC-1, AC-2, AC-3; BRU-REP-011)
   - Hàm mới `label_printer(station=None)`: lấy máy của trạm trước (dữ liệu cũ), nếu không có thì lấy `TraceCore Settings.label_printer`, không có nữa thì trả None.
   - `object_printer(station)`: gọi `label_printer`.
   - `select_printer(station, method)`: không lọc theo phương pháp nữa; giữ chữ ký để không vỡ nơi gọi. Docstring ghi A-114.
   - `create_job`: job mới luôn `Queued`. `Waiting` chỉ còn hợp lệ cho dữ liệu cũ.
   - `OUTPUT_MODES` thêm `Browser`.
   - Hàm mới `mark_browser_output(job)` gọi `ack(job, "Printed", "Browser")`.
   - `_can_output_file` nhận thêm `Printed`/`Browser` để In lại.
   - `set_roll`: chỉ cập nhật loại nhãn và audit, `released_jobs = []`.
   - Test: sửa `core/tests/test_print.py`. Viết test mới cho AC-3 với marker `@bru("BRU-REP-011")`.
3. **`core.label_pdf` khổ chung** (Q1)
   - PDF lô rửa, mẻ, gói và nhãn đối tượng dùng một khổ.
   - Hàm mới `object_pdf(label_object, code, title, subtitle)` dùng QR PNG (`core.qr`).
   - Hàm mới `set_tag_pdf(unit, kind)` dùng DataMatrix GS1 (`core.gs1.encode_datamatrix_png`).
   - `merge` giữ nguyên.
   - Test: `core/tests/test_label_pdf.py`.
4. **T2, T5** (AC-2, AC-6)
   - `washing._queue_label`, `sterilizing._queue_label`: dùng `label_printer` và luôn tạo `Queued`.
   - `label_pdf`: bỏ chặn `NO_PRINTER_AT_STATION`, gọi `mark_browser_output`.
   - Test: `reprocessing/tests/test_washing_start.py`, `test_sterilizing_complete.py`, `v1/tests/test_wash_api.py`, `test_load_api.py`.
5. **T4** (AC-2, AC-3, AC-12)
   - `packing.get_context`, `_generate`, `reprint`: lấy máy in qua `label_printer`.
   - `_check_label_output`: bỏ `NO_PRINTER_FOR_METHOD`.
   - `pack_label.queue_label`: không còn tạo `Waiting` vì thiếu máy in. `LABEL_TEMPLATE_MISSING` và `LABEL_RENDER_FAILED` vẫn chỉ là cảnh báo, PDF vẫn dựng được.
   - `waiting_labels_pdf`: giữ để phát lại gói đóng offline.
   - Quét cuộn ở T4 vẫn cập nhật loại nhãn nhưng không phát hành nhãn.
   - Test: `reprocessing/tests/test_packing.py`, `v1/tests/test_pack_api.py`.
6. **Thẻ bộ Set ID** (AC-7; FR-M1-05.3, FR-M1-05.4)
   - RPC mới `tracecore.v1.set_unit.tags_pdf(units, kinds, reprint_reason=None)`, roles như `print_tags`. Trả `pdf_b64`, `filename`, `print_jobs`.
   - `set_tags.queue_prints`: tạo job `Queued` với máy in chung và không enqueue gửi TCP.
   - `printer_block` / `PRINTER_NOT_NETWORK`: không dùng nữa.
   - `TAG_PRINT_PENDING`: chỉ chặn khi còn job `Queued` chưa in.
   - `create_batch`, `print_tags`, `reprint_tag`: bỏ tham số máy in, trả PDF.
   - `tc_set_unit.js`: bỏ ô chọn máy in, gọi hộp thoại In.
   - Test: `instrument/tests/test_set_tag_printing.py`, `v1/tests/test_set_unit_api.py`.
7. **Nhãn QR đối tượng** (AC-9)
   - `tracecore.v1.print.object_label` nhận một hoặc nhiều mã, trả PDF và không cần `printer`. Bỏ cảnh báo `PRINTER_AGENT_ONLY` và bỏ enqueue gửi TCP.
   - `tc_codes.js`: hộp thoại bỏ trường máy in. In hàng loạt gộp thành một PDF.
   - Test: `v1/tests/test_codes_api.py`.
8. **Nhãn chất thải** (AC-8; FR-M10-01.5)
   - `collection._queue_label`: dùng `label_printer` và luôn `Queued`.
   - RPC mới `tracecore.v1.waste.label_pdf(collection)`: PDF nhiều trang cho các thùng của lượt thu gom.
   - `station_waste.js`: nút In nhãn (`tcLabelButton`) trên thẻ kết quả.
   - Test: `waste/tests/test_collection.py`, test RPC.
9. **Trình in dùng chung ở trình duyệt** (AC-4, AC-5)
   - `tcPrintPdf(b64, filename)` thay `tcSavePdf`: tạo Blob URL, nạp vào iframe ẩn, gọi `contentWindow.print()`.
   - Lỗi (iframe không tải được, `print` ném lỗi, hết thời gian chờ) thì trả cờ để màn hiện `alert` inline kèm nút Mở PDF (`window.open(blobUrl)`).
   - Bản cho Desk nằm trong `tracecore.bundle.js`.
   - Thay các nơi gọi: `tcPrintLabelPdf`, `tc_outbox.js` (In n nhãn chờ), T4 sau quét cuộn.
   - Bỏ nhánh "chưa có máy in" ở `printNoteHtml` của T2/T5/T4 và `printerHtml` T4: nút In luôn hiện khi có job.
   - Test asset: `tracecore/tests/test_station_behavior.py`.
10. **Tắt đường ZPL** (AC-10)
    - Bỏ cron `print_server.dispatch_pending` khỏi `hooks.py`.
    - Không gọi `enqueue_server_dispatch*` nữa. Giữ module `print_server` để test cũ chạy cho tới khi dọn ở task 13.
    - `v1.print.test_label` (agent) và nút In thử trên form Printer: trả PDF nhãn thử.
    - Test: `core/tests/test_print_server.py` (bỏ test cron), `v1/tests/test_agent_api.py`.
11. **Giấy tờ A4** (AC-13; EI-HW-007)
    - `issuing.print_url`: thêm `trigger_print=1`.
    - Các biên nhận khác đã dùng `trigger_print`.
    - Phiếu kiểm đếm, sổ tiệt khuẩn: giữ như hiện nay (PDF ở tab mới hoặc file xuất). Người dùng in từ trình xem PDF.
12. **Patch và mã lỗi** (AC-11)
    - Patch `a114_release_waiting_print_jobs`: `Waiting` → `Queued`.
    - Nếu Q1 chọn đề xuất thì patch điền `label_printer`: đúng một Printer đang dùng thì chọn máy đó.
    - `NO_PRINTER_AT_STATION`, `NO_PRINTER_FOR_METHOD`, `PRINTER_NOT_NETWORK`, `PRINTER_AGENT_ONLY` vẫn giữ trong `core.errors` để đọc log cũ, nhưng không còn nơi phát sinh.
    - Cập nhật `setup/survey.py` (`NO_ACTIVE_PRINTER`, `PRINTER_WITHOUT_HOST`): chỉ cảnh báo khi chưa khai máy in chung.
13. **Dọn và tài liệu**
    - `setup/devdata.py`: đặt `label_printer`.
    - Bản dịch `vi.csv`.
    - Hướng dẫn triển khai máy trạm: Chrome `--kiosk-printing`, đặt máy in nhãn làm mặc định, khổ giấy và lề 0 trong driver. Ghi vào tài liệu triển khai hiện có, chỉ viết, không chạy.
    - Cập nhật `HUONG-DAN-NHAP-MA-T1-T8.md` phần in nhãn.
14. **Kiểm tra trước khi báo xong**
    - Chạy test module liên quan và toàn app trên `test_site`; đọc dòng `OK`/`FAILED` trong log, không tin exit code.
    - `diff-cover` ≥ 70 %.
    - `pre-commit run --all-files`.
    - Không chạy E2E trừ khi người dùng bảo.

## Thứ tự

1 → 2 → 3 → (4, 5 song song về logic, nhưng làm tuần tự vì cùng chạm `core.print`) → 9 → 6 → 7 → 8 → 10 → 11 → 12 → 13 → 14.

## Rủi ro

- Không có cách đo người dùng đã bấm In hay Hủy trong hộp thoại, nên `Printed` chỉ có nghĩa là đã mở hộp thoại In (A-114 g).
- Chrome kiosk chặn `print()` từ iframe khi trang chưa có thao tác của người dùng. Vì vậy chỉ gọi in ngay trong handler của nút bấm, không tự in sau khi tải.
- Ra PDF đúng khổ nhưng driver máy in có thể co giãn hoặc thêm lề. Phải thử trên máy in thật ở UAT (rủi ro đã ghi trong A-114).
