# FEAT-086 Mặc định xử lý của loại bộ: vật liệu gói, chỉ thị, chương trình — kế hoạch

> Nguồn: Amendment A-122 (`docs/architecture.md`), FR-M1-03, FR-M2-07, FR-M2-07.2, BRU-REP-009, BRU-REP-013.
> Người dùng yêu cầu ngày 05/11/2026:
> 1. "Phần trạm đóng gói, phần loại gói chia thành 3 nhóm: hộp hấp, túi ép, xăng vải, vải không dệt dạng droplist và thiết lập chọn mặc định hiển thị vật liệu đóng gói theo bộ dụng cụ ban đầu nhưng có thể điều chỉnh được".
> 2. "Khi thiết lập bộ dụng cụ thì để mặc định loại chỉ thị, loại vật liệu đóng gói, các chương trình triệt khuẩn được phép".
>
> Người dùng chốt: 3 nhóm (xăng vải + vải không dệt gộp thành Vải gói); một droplist có optgroup; loại gói mặc định theo `Instrument Set Type.default_pack_type`; giữ nguyên chỗ kiểm chương trình–gói (T5); chỉ thị mặc định là một mặt hàng cụ thể, T4 chỉ đưa lô của mặt hàng đó lên đầu, không chọn sẵn lô; thiếu mặc định không chặn; gom ba mục về một tab trên form loại bộ.
> Nhánh: `feat/FEAT-086-set-type-defaults` (đổi số từ A-121/FEAT-085 vì trùng với nhánh bảng thành phần).

## Acceptance criteria (EARS)

- **AC-1** (A-122 a): Item có trường `tc_pack_material` (Select `Rigid Container` / `Sealed Pouch` / `Wrap`, để trống được), chỉ hiện khi nhóm CSSD là `Packaging`.
- **AC-2** (A-122 b): Patch `a122_pack_material` điền nhóm cho Item `Packaging` còn trống theo tiền tố mã rồi từ khóa tên; Item đã có nhóm hoặc không khớp thì không đổi; chạy lại không đổi gì thêm.
- **AC-3** (FR-M2-07, A-122 c): `packing.pack_types(set_type)` trả mỗi loại gói kèm `material` và `is_default`; vẫn lọc theo phương pháp (A-97) và hạn lưu > 0.
- **AC-4** (FR-M2-07, A-122 c, d): Khi T4 mở ngữ cảnh một bộ, khối Loại gói phải là một `<select>` có optgroup theo thứ tự Hộp hấp → Túi ép → Vải gói → Chưa phân nhóm, chọn sẵn loại gói mặc định của loại bộ (không có thì dòng đầu), dòng mặc định có chữ "mặc định của bộ".
- **AC-5** (FR-M2-07): Khi KTV chọn loại gói khác trong droplist, màn phải đổi loại gói gửi lên `generate_cycle_id` và hạn dùng dự kiến; giá trị không có trong danh sách thì bỏ qua.
- **AC-6** (BRU-REP-009): Máy chủ vẫn từ chối loại gói sai phương pháp/không dùng được (`PACK_TYPE_INVALID`) như trước.
- **AC-7** (FR-M1-03, A-122 f): Loại bộ có `default_ci_item` không bắt buộc; nếu điền thì phải là Item `Chemical Indicator` chưa tắt, loại 5/6, phương pháp trống hoặc đúng phương pháp của loại bộ, sai thì không cho lưu; ô gợi ý chỉ liệt kê mặt hàng hợp lệ; trường có trong tạo và sao chép loại bộ.
- **AC-8** (FR-M2-07.2, BRU-REP-013, A-122 g): `packing.ci_lots(method, on, preferred_item)` đưa lô của mặt hàng mặc định lên đầu (hạn gần trước, tổng ≤ 10), mỗi lô có `is_default`; `get_context` trả `ci.default_item`; T4 ghi "mặc định của bộ" trên nút lô đó và **không** chọn sẵn lô.
- **AC-9** (FR-M1-03, A-122 h): Form loại bộ có tab "Mặc định xử lý" gồm loại gói mặc định, chỉ thị mặc định, hạn lưu và bảng chương trình được phép.
- **AC-10**: Chuỗi mới qua `_()` / `__()` và có trong `translations/vi.csv`; control trạm chữ ≥ 16 px, cao ≥ 48 px, chỉ token `--tc-*` (dùng lại `.tc-field select`).

## Tasks (TDD)

1. Custom Field `Item-tc_pack_material` trong `fixtures/custom_field.json` (AC-1). Test `reprocessing/tests/test_pack_material.py`. *Xong.*
2. `packing.pack_types` thêm `material`, `is_default` (AC-3, AC-6). *Xong.*
3. Patch `a122_pack_material` + `patches.txt` (AC-2). *Xong.*
4. `station_t4.js`: droplist loại gói (AC-4, AC-5). Test JS `tracecore/tests/test_station_behavior.py`. *Xong.*
5. `default_ci_item` trên `Instrument Set Type` (JSON, `set_type.validate_header`, `bom_versions.HEADER_FIELDS/COPY_FIELDS`, `v1.set_type.ci_item_query`, `instrument_set_type.js`) và bố cục tab Mặc định xử lý (AC-7, AC-9). Test `instrument/tests/test_set_type_defaults.py`.
6. `packing.ci_lots(..., preferred_item)` + `get_context` + `ciLotsHtml` ghi "mặc định của bộ" (AC-8). Test `test_pack_material.py` và JS.
7. Bản dịch, lint, test module, coverage changed-code ≥ 70 %.
