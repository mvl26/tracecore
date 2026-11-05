# FEAT-089 Ô quét tự gửi khi máy quét gõ xong mã — kế hoạch

> Nguồn: Amendment A-126 (`docs/architecture.md`), EI-UI-002. Người dùng yêu cầu ngày 05/11/2026 (kèm ảnh màn T1): "Khi quét mã vạch đầy đủ sẽ tự động luôn, không cần ấn quét nữa". Máy quét tại viện không gửi phím Enter.
> Nhánh: `feat/FEAT-089-scan-auto-submit`.

## Acceptance criteria (EARS)

- **AC-1** (A-126 a): Khi các ký tự vào một ô quét cách nhau ≤ 50 ms và đủ ≥ 4 ký tự liên tiếp (hoặc một lần nhập thêm ≥ 4 ký tự), rồi không có ký tự mới trong 120 ms, hệ thống phải gửi form của ô đó đúng một lần như bấm Quét.
- **AC-2** (A-126 c): Khi người dùng gõ tay (khoảng cách > 50 ms), hệ thống phải không tự gửi.
- **AC-3** (A-126 c): Xóa ký tự hoặc ô đã trống lúc hết 120 ms thì không gửi (máy quét có Enter đã gửi trước).
- **AC-4** (A-126 b): Áp cho mọi ô `tc-scan-input` của Page `station` (ô quét chính, ô thẻ, ô lô chỉ thị T4); `tc_scan_burst.js` nạp đầu `page_js`.

## Tasks (TDD)

1. `public/js/tc_scan_burst.js`: lớp `TcScanBurst` (đồng hồ và hẹn giờ truyền vào được để test) (AC-1..AC-3). Test JS trong `tracecore/tests/test_station_behavior.py`.
2. `station.js`: listener `input` ủy quyền trên root cho `.tc-scan-input`, mỗi ô một `TcScanBurst`, xong thì `form.requestSubmit()`; `hooks.page_js` thêm file (AC-4). Test đọc nguồn/hook.
3. Lint, test, merge develop, cập nhật site dev.
