# Ảnh tham chiếu giao diện v1.12 — KSNK toàn viện (Amendment A-113)

20 màn SCR-47..66 cho M11–M17 và M9 mở rộng. Dùng làm mẫu khi làm FEAT-056 trở đi (bước ui-design / writing-plans).

- Nguồn: canvas thiết kế "TraceCore v1.12 — Giao diện KSNK toàn viện" (03/11/2026), dựng theo `docs/design.md` + `docs/tokens.json`.
- Ảnh chụp ở tỉ lệ 2× (WEB rộng 1440 px, PDA 390 × 844), nén bảng màu 128 màu.
- **Thứ tự ưu tiên khi lệch nhau:** `docs/tokens.json` > `docs/design.md` > `docs/ux-foundations.md` > ảnh trong thư mục này. Ảnh không phải đặc tả: lấy giá trị màu, cỡ chữ, khoảng cách từ token `--tc-*`, không đo trên ảnh.
- **Dữ liệu trên ảnh là dữ liệu mẫu.** Ngưỡng chuyên môn (vi sinh môi trường, cụm ca, mốc theo dõi phơi nhiễm, mục gói dự phòng) chỉ là ví dụ cấu hình — chờ OQ-V12-08/09; không đưa vào code hay fixtures.
- WEB vẽ dạng shell rút gọn (navbar + menu KSNK + nội dung). Khi hiện thực trên Frappe Desk: dùng sidebar/Workspace chuẩn của Desk, List View/Form/Report theo ux-foundations §B1; giữ bố cục khối, badge có chữ và thứ tự hành động như ảnh.

| Ảnh | SCR | Tên | Surface | UC | FEAT |
| --- | --- | --- | --- | --- | --- |
| `SCR-66_BangChiSoKSNK.png` | SCR-66 | Bảng chỉ số KSNK toàn viện, báo cáo Hội đồng, tự đánh giá QĐ 38 | WEB (+ view DEPT) | UC-57 | 056, 065, 074 |
| `SCR-47_CoCau.png` | SCR-47 | Cơ cấu KSNK: cài đặt, Hội đồng, mạng lưới | WEB | UC-40 | 057 |
| `SCR-48_KeHoach.png` | SCR-48 | Kế hoạch năm, văn bản nội bộ, họp Hội đồng | WEB | UC-41 | 058 |
| `SCR-49_DaoTao.png` | SCR-49 | Đào tạo, sinh viên thực tập, cải tiến chất lượng | WEB | UC-42 | 059, 072 |
| `SCR-50_MauPhieu.png` | SCR-50 | Mẫu phiếu có phiên bản & lịch giám sát | WEB | UC-43 | 060 |
| `SCR-51_PDA-VeSinhTay.png` | SCR-51 | PDA — vệ sinh tay theo cơ hội (≤ 3 chạm) | PDA | UC-44 | 061 |
| `SCR-52_PDA-PhieuMuc.png` | SCR-52 | PDA — phiếu theo mục (ví dụ gói VAP, trạng thái ngoại tuyến) | PDA + DEPT | UC-44, 54, 56 | 060, 062, 070, 073 |
| `SCR-53_BaoCaoTuanThu.png` | SCR-53 | Báo cáo tuân thủ, phản hồi khoa, đề nghị mở NC | WEB | UC-45 | 060 |
| `SCR-54_HoaChat.png` | SCR-54 | Hóa chất KSNK theo khoa; đơn vị thuê ngoài & giấy phép | WEB | UC-46 | 066 |
| `SCR-55_Khoa-MauSo.png` | SCR-55 | Cổng khoa — mẫu số ngày & đợt thiết bị (có ví dụ lỗi tại ô) | DEPT | UC-47 | 062 |
| `SCR-56_CaNKBV.png` | SCR-56 | Ca NKBV, che mã BN, kỳ báo cáo | WEB | UC-48 | 063 |
| `SCR-57_NKVM.png` | SCR-57 | Giám sát NKVM: NNIS, cửa sổ theo dõi, kháng sinh dự phòng | WEB | UC-49 | 064 |
| `SCR-58_BaoCaoNKBV.png` | SCR-58 | Báo cáo NKBV, cảnh báo cụm ca, điều tra cắt ngang | WEB | UC-48, 49, 50 | 063, 064, 069, 072 |
| `SCR-59_ViSinh.png` | SCR-59 | Import vi sinh (WHONET/CSV), đa kháng, kháng sinh đồ | WEB | UC-51 | 067 |
| `SCR-60_CachLy.png` | SCR-60 | Lệnh cách ly & phòng cách ly | WEB + DEPT | UC-52 | 068 |
| `SCR-61_ODich.png` | SCR-61 | Điều tra ổ dịch (đường cong dịch), khai báo bệnh truyền nhiễm | WEB | UC-53 | 069 |
| `SCR-62_MoiTruong.png` | SCR-62 | Vệ sinh môi trường, xét nghiệm môi trường, hạ tầng | WEB | UC-54 | 070 |
| `SCR-63_PDA-PhoiNhiem.png` | SCR-63 | PDA — báo phơi nhiễm 3 bước (ảnh ở bước 1) | PDA + DEPT | UC-55 | 071 |
| `SCR-64_PhoiNhiem.png` | SCR-64 | Hồ sơ phơi nhiễm & theo dõi; tiêm chủng nhân viên | WEB | UC-55 | 071 |
| `SCR-65_ATTP.png` | SCR-65 | An toàn thực phẩm; truyền thông người bệnh (QR) | WEB | UC-56 | 073 |

## Quy tắc thể hiện đã áp trên ảnh (dev giữ khi hiện thực)

1. Trạng thái luôn có chữ trên badge (Đạt / Không đạt / Chưa đủ mẫu / Không tính…), không dùng màu đơn thuần; ô số dưới mục tiêu có thêm ký hiệu ↓/↑.
2. Mã người bệnh luôn che (`••••••4821`) trên danh sách, báo cáo, PDA; xem đầy đủ chỉ R01/R11 có lý do + Audit Log (SCR-56).
3. Lỗi chặn nghiệp vụ là `alert-error` inline theo thứ tự kết quả → lý do → hành động, kèm viền đỏ tại ô sai (SCR-55, SCR-60); không modal/toast.
4. PDA: nút ≥ 48 px (nút chính 56 px), chữ ≥ 16 px, thanh trạng thái mạng + số giao dịch chờ ở đầu; banner ngoại tuyến (SCR-52).
5. Mã chứng từ, mã mẫu phiếu, mã chủng dùng font mono (Courier New); naming series theo architecture §5.3.3.
6. M16 không có trường kết quả xét nghiệm/chẩn đoán nhân viên (SCR-63, SCR-64).
