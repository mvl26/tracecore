# Bảng quét T1 → T8 (theo docs/use-cases.md UC-05 … UC-13)

Quy ước: **quét = gõ mã vào ô quét trên cùng + Enter**. Cột "Mã test" là dữ liệu trên site dev 8022.

## Các loại mã

| Loại mã | Dạng | Ở đâu ngoài thực tế | Mã test |
| --- | --- | --- | --- |
| Thẻ nhân viên | mã thẻ | thẻ đeo của nhân viên | KTV `THE-KTV-01` · Người giao `THE-GIAO-01` · R02 `THE-R02-01` · Điều dưỡng `THE-DD-01` |
| **Set ID** (bộ, vĩnh viễn) | GS1 GIAI `9520000…` | khắc/dán trên khay | `9520000NGOAI1000001` |
| QR máy | `TB-####` | dán trên máy rửa/hấp | rửa `TB-0013` · hấp `TB-0014` |
| Mã lô rửa | `LR-YYMMDD-NN` | nhãn QR lô, **sinh ở T2** | `LR-261026-01` |
| Lô chỉ thị hóa học | mã lô NSX | hộp chỉ thị | `LOT-CI5-TEST-01` |
| **Cycle ID** (gói, dùng 1 lần) | `CY-YYMMDD-NNNN` | nhãn trên gói, **sinh ở T4** | ghi lại khi T4 sinh |
| Mã mẻ | `ME-YYMMDD-NN` | nhãn QR mẻ, **sinh ở T5** | ghi lại khi T5 sinh |
| Mã kệ | `KE-####` | dán trên kệ | `KE-0004` |
| Mã lệnh | `HOAN-THANH-NAP` | thẻ lệnh ở máy | thay cho nút Hoàn thành nạp (T2, T5) |

## Thứ tự quét từng trạm

| Trạm | Người (role) | Quét theo thứ tự | Hệ thống kiểm gì khi quét | Kết quả |
| --- | --- | --- | --- | --- |
| **Mọi trạm** | — | ① **Thẻ người thao tác** | thẻ bật, nhân viên Active, có user + role, năng lực trạm còn hạn | mở phiên (≤ 8 giờ, khóa sau 10 phút) |
| **T1** Tiếp nhận (UC-05) | KTV khu bẩn (R03) | ② **Thẻ người giao** (1 lần/phiếu) → ③ **Set ID** từng bộ | người giao thuộc khoa; bộ ở trạng thái Mới/Tại khoa/Chờ tiếp nhận | bấm xác nhận thành phần → Xác nhận bộ → **Ghi sổ phiếu**; cổng **T1 Đạt** |
| **T2** Rửa – nạp (UC-06) | KTV khu bẩn (R03) | ② **QR máy rửa** → ③ **Set ID** từng bộ → ④ `HOAN-THANH-NAP` (hoặc nút) | máy Sẵn sàng + **test hằng ngày** Đạt; chưa quét máy thì không nhận bộ; bộ có **cổng T1 Đạt**, chưa ở lô khác | sinh **mã lô LR-** |
| **T2** Rửa – dỡ | KTV (R03/R04) | ② **QR máy rửa** → ③ **mã lô LR-** | máy khớp lô | nhập tay dữ liệu máy + xác nhận → kết luận Đạt; cổng **T2 Đạt** cho mọi bộ trong lô |
| **T3** Lắp ráp (UC-07) | KTV khu sạch (R04) | ② **Set ID** | **cổng T2 Đạt** | đếm theo BOM → Ghi nhận kiểm đếm; cổng **T3 Đạt** |
| **T4** Đóng gói (UC-08) | KTV khu sạch (R04) | ② **Set ID** → ③ **lô chỉ thị hóa học** (ô riêng) | **cổng T3 Đạt**; chỉ thị đúng phương pháp, loại 5, còn hạn; loại bộ có GTIN | Xác nhận hoàn thành đóng gói → sinh **Cycle ID CY-** + nhãn; cổng **T4 Đạt** |
| **T5** Nạp mẻ (UC-09) | KTV tiệt khuẩn (R05) | ② **QR máy hấp** → ③ **Cycle ID** từng gói → ④ `HOAN-THANH-NAP` (hoặc nút) | máy Sẵn sàng + **Bowie-Dick + leak** hôm nay; gói có **cổng T4 Đạt**, tương thích chương trình, đủ dung tích | sinh **mã mẻ ME-** |
| **T5** Dữ liệu mẻ | KTV (R05) | ② **QR máy hấp** → ③ **mã mẻ ME-** → ④ **thẻ của chính mình** để xác nhận | thẻ trùng người đang đăng nhập | nhập nhiệt độ/áp suất → mẻ **Hoàn tất chu trình** |
| **T5b** Dỡ – giải phóng (UC-10) | KTV (R05) rồi **giám sát (R02)** | ② **QR máy hấp** → ③ **mã mẻ ME-**; sau đó R02 quét **thẻ R02** + nhập **PIN** | có dữ liệu máy; chỉ thị hóa học Đạt; Bowie-Dick ngày; chỉ R02 được giải phóng | **Giải phóng mẻ** → cổng **T5 Đạt**, bộ **Vô khuẩn** |
| **T6** Kho (UC-11) | KTV kho (R06) | ② **Cycle ID** → ③ **mã kệ KE-** | gói Đã giải phóng, bộ đủ 5 cổng; kệ tồn tại | gói **Trong kho vô khuẩn** tại kệ |
| **T7** Cấp phát (UC-12) | KTV cấp phát (R06) | (chạm chọn khoa) → ② **Cycle ID** từng gói → ③ **thẻ người nhận** của khoa | gói Trong kho, còn hạn, FEFO, cơ số khoa | Xác nhận → gói **Đã cấp phát**, bộ **Tại khoa** |
| **T8** Sử dụng (UC-13) | Điều dưỡng khoa (R08) | ② **Cycle ID** | gói chưa dùng/quá hạn/thu hồi; đúng khoa | nhập mã BN, ca mổ, PTV → gói **Đã sử dụng**, bộ **Chờ tiếp nhận** (về lại T1) |

## Mã nào đi theo bước nào

```
Set ID (vĩnh viễn) ── T1 ── T2 ── T3 ── T4 ┐
                                           └─ sinh Cycle ID (1 chu trình) ── T5 ── T5b ── T6 ── T7 ── T8
Máy:      T2 (TB-0013 → sinh LR-)                       T5 / T5b (TB-0014 → sinh ME-)
Thẻ phụ:  T1 thẻ người giao · T5b thẻ + PIN R02 · T7 thẻ người nhận
```

- Từ **T1 đến T4** quét **Set ID**. Từ **T5 đến T8** quét **Cycle ID**.
- Ở T2 và T5 luôn quét **máy trước** rồi mới quét bộ/gói; khi dỡ, quét **máy + mã lô/mẻ**.
- UC-08 bước 6 (quét lại nhãn sau khi dán) và UC-09 bước 3 (quét lô chỉ thị/BI trong mẻ) có trong tài liệu nhưng
  chưa đối chiếu với màn T4/T5 — kiểm khi test và ghi nhận nếu thiếu.
