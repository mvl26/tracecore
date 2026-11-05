# FEAT-088 QR truy xuất trên phiếu cấp phát — kế hoạch

> Nguồn: Amendment A-124 (`docs/architecture.md`), FR-M2-15.1, FR-M2-19, UC-12, UC-14. Người dùng yêu cầu ngày 05/11/2026: "Trạm cấp phát ở phần phiếu cấp phát cần phải có mã QR để truy xuất toàn bộ quá trình xử lý dụng cụ từ khi tiếp nhận ở khu đồ bẩn đến khi cấp phát. Mỗi bộ dụng cụ cấp phát cho khoa đều gắn với 1 mã này".
> Người dùng chốt: một QR cho cả phiếu; xem được trên Desk (R01/R02) và view khoa (R08, chỉ chuỗi của khoa mình).
> Nhánh: `feat/FEAT-088-issue-note-qr`.

## Acceptance criteria (EARS)

- **AC-1** (FR-M2-19, A-124 b): Khi tra cứu với tiêu chí `issue_note`, `trace.query` phải trả chuỗi của đúng các gói trong phiếu đó (giao với các tiêu chí khác nếu có); phiếu đã hủy không trả gì.
- **AC-2** (FR-M2-19): RPC `tracecore.v1.trace.query` và báo cáo `Pack Trace` nhận tham số/bộ lọc `issue_note`.
- **AC-3** (FR-M2-19, A-124 c): R08 tra theo phiếu chỉ thấy chuỗi của khoa mình (luật `_scope` sẵn có).
- **AC-4** (FR-M2-15.1, A-124 a): Print Format `TC Issue Note` in một QR (PNG base64 sinh tại server) có payload `<site>/app/query-report/Pack Trace?issue_note=<số phiếu>` (đã mã hóa URL), kèm số phiếu Courier New và dòng hướng dẫn quét.
- **AC-5**: Chuỗi mới qua `_()` / `__()` và có trong `translations/vi.csv`.

### Bổ sung A-125 (người dùng dùng máy quét mã vạch, không dùng điện thoại; nhánh `feat/FEAT-088-issue-note-qr-scan`)

- **AC-6** (A-125 a, thay AC-4 về payload): QR trên phiếu chứa đúng số phiếu (mã trần); dưới QR in số phiếu Courier New và dòng "Quét vào ô Phiếu cấp phát ở màn Tra cứu".
- **AC-7** (A-125 b): `trace.query(issue_note=…)` nhận chuỗi máy quét gõ vào: bỏ khoảng trắng/CR/LF/tiền tố AIM; chuỗi là đường dẫn có `issue_note=` (phiếu in theo A-124) thì lấy số phiếu trong đó.
- **AC-8** (A-125 b): Báo cáo `Pack Trace` có ô "Phiếu cấp phát" đứng đầu bộ lọc và nhận con trỏ khi mở báo cáo.

## Tasks (TDD)

1. `trace._candidates` + `trace.query(issue_note=…)` (AC-1, AC-3). Test `reprocessing/tests/test_trace.py`.
2. `v1.trace.query` + report `pack_trace` (`CRITERIA`, bộ lọc JS) (AC-2). Test cùng file.
3. `ui.issue_print`: `trace_url`, `trace_qr` trong ngữ cảnh in; template in QR (AC-4). Test `reprocessing/doctype/issue_note/test_issue_note.py`.
4. Bản dịch, lint, test module, coverage changed-code ≥ 70 %.
5. (A-125) `ui.issue_print.trace_qr` mã hóa số phiếu; template thêm số phiếu + hướng dẫn quét (AC-6). Test `test_issue_note.py`.
6. (A-125) `trace.issue_note_code` làm sạch chuỗi quét / tách từ đường dẫn (AC-7); `pack_trace.js` đưa ô Phiếu cấp phát lên đầu và focus khi mở (AC-8). Test `test_trace.py` (+ kiểm JS bằng đọc file).
