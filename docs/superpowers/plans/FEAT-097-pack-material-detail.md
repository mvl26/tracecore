# FEAT-097 Loại vật liệu đóng gói: giấy bọc, kích thước túi ép, số lớp — kế hoạch

> Nguồn: Amendment A-155 (`docs/architecture.md`), FR-M6-02.5, FR-M2-07; sửa nhóm vật liệu của A-122 (FEAT-086).
> Người dùng yêu cầu ngày 12/11/2026: "loại vật liệu đóng gói đấy thì sẽ cho người dùng chọn ví dụ hộp hấp, túi ép, … vải bọc, … giấy bọc, nếu là túi ép thì sẽ có kích thước, nếu là giấy bọc thì sẽ có 1 lớp hay 2 lớp".
> Sao chép loại bộ đã có (UC-02 A2, nút "Sao chép loại bộ" trên form Loại bộ) — không làm lại.
> Nhánh: `feat/FEAT-097-pack-material-detail`.

## Acceptance criteria

Xem `docs/implementation-plan.md` §FEAT-097 (AC-097-01..06).

## Tasks (TDD)

1. Custom Field `Item-tc_pack_material` thêm `Paper Wrap`; `Item-tc_pouch_size` (Data), `Item-tc_wrap_layers` (Select `Single Layer`/`Double Layer`), `depends_on` + `mandatory_depends_on` theo vật liệu (AC-097-01). Test `inventory/tests/test_pack_material_detail.py`.
2. `inventory.items.validate_item` → `_validate_pack_material`: chỉ nhóm Packaging; Túi ép bắt buộc kích thước hợp lệ (chuẩn hóa), Giấy bọc bắt buộc số lớp; xóa trường không áp dụng (AC-097-02..04).
3. `packing.pack_types` trả `pouch_size`, `wrap_layers` (AC-097-05).
4. `station_t4.js`: nhóm Giấy bọc trong `T4_PACK_MATERIALS`, dòng ghi kích thước/số lớp (AC-097-05). Test JS trong `tracecore/tests/test_station_behavior.py`.
5. Patch `a155_pack_material_detail` + `patches.txt` (AC-097-06).
6. `inventory.imports`: cột Pack Material, Pouch Size, Wrap Layers.
7. Bản dịch `vi.csv`, lint, test module, coverage changed-code ≥ 70 %.
