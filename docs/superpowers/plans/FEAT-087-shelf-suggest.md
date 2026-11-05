# FEAT-087 Kệ Đề xuất / Trống khi chọn tay kệ ở T6 — kế hoạch

Amendment A-123 (mở rộng A-120 (b)). FR-M2-13, UC-11, SCR-11. Phụ thuộc FEAT-084.

Người dùng yêu cầu ngày 05/11/2026: "Trạm lưu kho vô khuẩn cần hiển thị ở phần chọn tay các mã kệ đề xuất hoặc còn
trống". Chọn phương án cùng ngày: Đề xuất = kệ đang chứa gói cùng loại bộ; Trống = kệ chưa có gói nào (chưa có sức
chứa kệ).

## Task 1 — Server: đếm và xếp kệ (FR-M2-13, A-123 a, b, d)

- Test trước: `tracecore/v1/tests/test_lookup_api.py`
  - `TestLookupLocations.test_open_pack_puts_same_set_type_shelves_then_empty_shelves_first`
  - `TestLookupLocations.test_moving_pack_is_not_counted_on_its_own_shelf`
- `tracecore/reprocessing/pick_list.py` `locations(q, start, page_length, pack=None)`: left join Pack trạng thái Trong
  kho vô khuẩn, bỏ chính gói `pack`; trả `stock`, `same`, `hint` ("suggested" / "empty" / None); order theo Đề xuất,
  Trống, mã.
- `tracecore/v1/lookup.py` `locations(..., pack=None)`.

## Task 2 — Panel Chọn tay (A-123 c)

- Test trước: `tracecore/tests/test_station_behavior.py`
  `TestPickerShelves.test_shelf_list_sends_open_pack_and_marks_suggested_and_empty`.
- `station_picker.js`: loại Kệ gửi `pack` = `screen.openPack()` (T6 đã có); `hintHtml` badge chữ `tc-badge-g`
  "Suggested" / `tc-badge-x` "Empty".
- `translations/vi.csv`: Suggested, Empty, "{0} pack(s) of this set type", "{0} pack(s)".

## AC

- Khi màn Lưu kho đang mở một gói và người dùng mở panel Chọn tay loại Kệ, hệ thống phải liệt kê kệ đang chứa gói
  cùng loại bộ trước, có badge "Đề xuất" và số gói cùng loại.
- Kế tiếp là kệ chưa có gói, có badge "Trống"; sau cùng là kệ khác kèm số gói đang có.
- Gói đang trong kho (chuyển kệ) không được tính vào kệ hiện tại của chính nó.
- Kệ chọn xong vẫn đi qua `storage.putaway` như khi quét.
