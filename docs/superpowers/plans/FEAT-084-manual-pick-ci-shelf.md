# FEAT-084 Chọn tay lô chỉ thị ở T4 và kệ ở T6 — kế hoạch

> Nguồn: Amendment A-120 (`docs/architecture.md`), FR-M2-07.2, FR-M2-13, BRU-REP-013. Người dùng yêu cầu ngày 04-05/11/2026 ("lô chỉ thị vẫn chưa hiện ra để chọn tay", "chọn tay mã kệ").
> Nhánh: `feat/FEAT-084-manual-pick-ci-shelf` trong `apps/tracecore`.

## Acceptance criteria (EARS)

- **AC-1** (FR-M2-07.2, BRU-REP-013): Khi T4 mở ngữ cảnh một bộ, hệ thống phải trả `ci.lots` gồm tối đa 10 lô chỉ thị dùng được: Item nhóm Chemical Indicator, đúng phương pháp của bộ, loại 5/6, Item và Batch chưa tắt, có hạn dùng chưa qua hôm nay; hạn gần trước.
- **AC-2** (FR-M2-07.2): Lô sai phương pháp, sai loại, hết hạn, thiếu hạn dùng hoặc đã tắt thì không có trong `ci.lots`.
- **AC-3** (FR-M2-07.2): Khi người dùng chạm một lô trong khối Lô chỉ thị, màn phải xử lý như quét đúng tên lô đó; chưa có lô nào thì hiện câu báo và hành động.
- **AC-4** (FR-M2-13): Khi màn Lưu kho đang mở một gói, panel Chọn tay phải có loại "Kệ" liệt kê kệ đang dùng (tìm theo mã/tên/mô tả, phân trang); chọn một kệ gửi qua `putaway.scan` kèm `entry_mode = Manual` và lý do.
- **AC-5**: `v1.lookup.locations` chỉ đọc, phiên thẻ, vai trò T6; màn khác → `STATION_WRONG_STEP`.
- **AC-6**: Chuỗi mới qua `_()` / `__()` và có trong `translations/vi.csv`.

## Tasks (TDD)

1. `packing.ci_lots(method, on)` + `get_context` trả `ci.lots` (AC-1, AC-2). Test `reprocessing/tests/test_packing_rules.py`.
2. `station_t4.js`: nút chọn lô trong `ciHtml`, action `ci-pick` → `scanIndicator` (AC-3). Test JS ở `tracecore/tests/test_station_behavior.py`.
3. `pick_list.locations(q, start, page_length)` + RPC `v1.lookup.locations` (AC-4, AC-5). Test `v1/tests/test_lookup_api.py`.
4. `station_t6.js` `pickLocation()`; `station_picker.js` loại `location` (AC-4). Test JS.
5. Bản dịch, lint, test module, coverage changed-code ≥ 70 %.
