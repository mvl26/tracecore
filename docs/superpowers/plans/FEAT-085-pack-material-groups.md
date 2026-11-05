# FEAT-085 Nhóm vật liệu gói và droplist loại gói ở T4 — kế hoạch

> Nguồn: Amendment A-121 (`docs/architecture.md`), FR-M2-07, BRU-REP-009. Người dùng yêu cầu ngày 05/11/2026: "Phần trạm đóng gói, phần loại gói chia thành 3 nhóm: hộp hấp, túi ép, xăng vải, vải không dệt dạng droplist và thiết lập chọn mặc định hiển thị vật liệu đóng gói theo bộ dụng cụ ban đầu nhưng có thể điều chỉnh được".
> Người dùng chốt: 3 nhóm (xăng vải + vải không dệt gộp thành Vải gói), một droplist có optgroup, mặc định theo `Instrument Set Type.default_pack_type`, giữ nguyên chỗ kiểm chương trình–gói (T5).
> Nhánh: `feat/FEAT-085-pack-material-groups`.

## Acceptance criteria (EARS)

- **AC-1** (A-121 a): Item có trường `tc_pack_material` (Select `Rigid Container` / `Sealed Pouch` / `Wrap`, để trống được), chỉ hiện khi nhóm CSSD là `Packaging`.
- **AC-2** (A-121 b): Patch `a121_pack_material` điền nhóm cho Item `Packaging` còn trống theo tiền tố mã rồi từ khóa tên; Item đã có nhóm hoặc không khớp thì không đổi; chạy lại không đổi gì thêm.
- **AC-3** (FR-M2-07, A-121 c): `packing.pack_types(set_type)` trả mỗi loại gói kèm `material` và `is_default`; vẫn lọc theo phương pháp (A-97) và hạn lưu > 0.
- **AC-4** (FR-M2-07, A-121 c, d): Khi T4 mở ngữ cảnh một bộ, khối Loại gói phải là một `<select>` có optgroup theo thứ tự Hộp hấp → Túi ép → Vải gói → Chưa phân nhóm, chọn sẵn loại gói mặc định của loại bộ (không có thì dòng đầu), dòng mặc định có chữ "mặc định của bộ".
- **AC-5** (FR-M2-07): Khi KTV chọn loại gói khác trong droplist, màn phải đổi loại gói gửi lên `generate_cycle_id` và hạn dùng dự kiến; giá trị không có trong danh sách thì bỏ qua.
- **AC-6** (BRU-REP-009): Máy chủ vẫn từ chối loại gói sai phương pháp/không dùng được (`PACK_TYPE_INVALID`) như trước.
- **AC-7**: Chuỗi mới qua `_()` / `__()` và có trong `translations/vi.csv`; control trạm chữ ≥ 16 px, cao ≥ 48 px, chỉ token `--tc-*` (dùng lại `.tc-field select`).

## Tasks (TDD)

1. Custom Field `Item-tc_pack_material` trong `fixtures/custom_field.json` (AC-1). Test `reprocessing/tests/test_pack_material.py`.
2. `packing.pack_types` thêm `material`, `is_default` (AC-3, AC-6). Test cùng file.
3. Patch `tracecore/patches/v0_1/a121_pack_material.py` + `patches.txt` (AC-2). Test cùng file.
4. `station_t4.js`: `packHtml()` dựng droplist optgroup; `onScan` chọn mặc định theo `is_default`; sự kiện `change` của `#tc-t4-pack` → `choosePackType` (AC-4, AC-5). Test JS `tracecore/tests/test_station_behavior.py`.
5. Bản dịch, lint, test module, coverage changed-code ≥ 70 %.
