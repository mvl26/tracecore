# FEAT-077 Khổ nhãn chung mặc định 50 × 30 mm — kế hoạch

> Nguồn: Amendment A-116 (`docs/architecture.md`), FR-M2-08, A-114 (d). Người dùng chọn "đổi mặc định trong hệ thống" ngày 04/11/2026.
> Nhánh: `feat/FEAT-077-label-size-50x30` trong `apps/tracecore`, tạo từ `develop` sau khi nhánh `docs/A-116-label-size-50x30` được duyệt và merge.

## Acceptance criteria (EARS)

- **AC-1** (A-116 a): Khi TraceCore Settings chưa đặt khổ nhãn, hệ thống phải dùng 50 × 30 mm cho `label_width_mm` × `label_height_mm`; mọi PDF nhãn (lô rửa, mẻ, gói, thẻ bộ, chất thải, QR đối tượng, nhãn thử) phải đúng khổ này.
- **AC-2** (A-116 a): Khi R10 đổi khổ trong Settings, PDF mới phải theo khổ đã đặt.
- **AC-3** (A-116 b): Khi migrate, nếu khổ đang đúng 60 × 40 hoặc trống thì patch phải đặt 50 × 30; nếu khác thì giữ nguyên. Chạy lại patch không đổi thêm.
- **AC-4** (A-116 c): Nhãn gói ở 50 × 30 phải còn DataMatrix GS1, Cycle ID, hạn dùng, dòng THIẾU khi có; tên bộ cắt gọn một dòng, không tràn khổ.

## Tasks (TDD)

1. **Mặc định và patch** (AC-1, AC-2, AC-3)
   - [ ] Test: `test_default_label_size_is_50x30`, `test_custom_size_is_used`, `test_patch_moves_only_old_default`, `test_patch_is_idempotent`. Thấy fail.
   - [ ] Đổi default trong `TraceCore Settings` JSON và hằng số `core/label_pdf.py`; patch `use_label_size_50x30_a116` (v15 patches.txt).
2. **Bố cục** (AC-4)
   - [ ] Test dựng PDF gói ở 50 × 30: kích thước trang, có DataMatrix, tên bộ dài bị cắt một dòng.
   - [ ] Chỉnh CSS/HTML nhãn gói trong `core/label_pdf.py` cho vừa khổ, bỏ dòng phụ tiếng Anh nếu thiếu chỗ.
3. **Hoàn tất**
   - [ ] Chạy test `core`, `v1.tests.test_pack_api`, `test_wash_api`, `test_load_api` và các test label_pdf; `pre-commit` sạch; không chạy E2E, không tạo PR; ghi rõ cần in thử trên cuộn 50 × 30 thật.
