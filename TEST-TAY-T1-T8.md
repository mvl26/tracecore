# Kịch bản test tay T1 → T8 (site dev http://localhost:8022)

## 1. Bảng mã cố định (đã tạo sẵn)

| Loại | Mã | Ghi chú |
| --- | --- | --- |
| **Set ID (bộ dụng cụ)** | `9520000NGOAI1000001` | 9520000 + NGOAI1 + 000001 — nên copy-paste |
| Loại bộ / BOM | `NGOAI1` · BOM v1 = **M1 × 1** | Bộ ngoại test, Steam, giấy gói `Goi-test` (30 ngày) |
| Khoa | Khoa ngoại tracecore | |
| Thẻ KTV | `THE-KTV-01` | KTV Test — đăng nhập T1 → T7 |
| Thẻ người giao | `THE-GIAO-01` | chỉ dùng ở T1 |
| Thẻ giám sát R02 | `THE-R02-01` · PIN `246810` | chỉ dùng ở T5b |
| Thẻ điều dưỡng | `THE-DD-01` | ký nhận ở T7, đăng nhập T8 |
| Máy rửa | `TB-0013` · chương trình `RUA-TEST-01` (90–95 °C) | T2 |
| Máy hấp | `TB-0014` · chương trình `HAP-TEST-134` (132–138 °C, 0–2,3 bar) | T5 |
| Lô chỉ thị hóa học loại 5 | `LOT-CI5-TEST-01` | T4 |
| Kệ kho vô khuẩn | `KE-0004` | T6 |

## 2. Mã sinh ra trong lúc test — ghi lại khi màn hiện

| Mã | Sinh ở | Ghi vào đây |
| --- | --- | --- |
| Mã lô rửa `LR-…` | T2 Hoàn thành nạp | `LR-________` |
| Cycle ID `CY-…` | T4 Hoàn thành đóng gói | `CY-________` |
| Mã mẻ `ME-…` | T5 Hoàn thành nạp | `ME-________` |

Quy tắc chung: gõ mã vào **ô quét trên cùng** rồi **Enter**. Mỗi trạm mở bằng
`http://localhost:8022/app/station?station=TR-00x`, rồi gõ thẻ để đăng nhập.

---

## T1 Tiếp nhận — `?station=TR-001` — ✅ ĐÃ XONG (phiếu RC-2026-00001)

---

## T2 Rửa — `?station=TR-002` — thẻ `THE-KTV-01`

Test hằng ngày máy rửa: ✅ đã ghi hôm nay (bỏ qua).

**Nạp lô** (chip "Nạp lô")
1. `TB-0013` → hiện máy + chương trình `RUA-TEST-01`
2. `9520000NGOAI1000001` → bộ vào khung "Bộ đã quét vào máy (1)"
3. Bấm **Hoàn thành nạp → sinh mã lô** → **ghi lại `LR-…`**

**Dỡ lô** (chip "Dỡ lô (1 lô đang chạy)")
4. `TB-0013` → `LR-…`
5. Form nhập tay: Temperature `92` · Kết quả máy **Đạt** · giờ bắt đầu < giờ kết thúc · **tải 1 ảnh bất kỳ** (bản in) · Cảnh báo máy **Không** · tick xác nhận → **Lưu dữ liệu nhập tay và xác nhận**
6. Kết quả chu trình **Đạt** · Test làm sạch **Đạt** · tick xác nhận → **Ghi kết quả cho 1 bộ**

✔ Kết quả: lô rửa ghi sổ, cổng **T2 = Đạt**.

---

## T3 Kiểm tra – lắp ráp — `?station=TR-003` — thẻ `THE-KTV-01`

1. `9520000NGOAI1000001` → hiện BOM: **M1 × 1**
2. Bấm **Xác nhận tất cả thành phần** (hoặc "Đủ" ở dòng M1)
3. Bấm **Ghi nhận kiểm đếm**

✔ Kết quả: cổng **T3 = Đạt**, màn hiện "Đóng gói: sẵn sàng".

---

## T4 Đóng gói + Cycle ID — `?station=TR-004` — thẻ `THE-KTV-01`

1. `9520000NGOAI1000001` → hiện BOM, loại gói `Goi-test`
2. Bấm **Xác nhận tất cả thành phần**
3. Gõ `LOT-CI5-TEST-01` vào **ô "Quét lô chỉ thị" riêng** (KHÔNG gõ vào ô quét trên cùng)
4. Bấm **Xác nhận hoàn thành đóng gói** → **ghi lại `CY-…`** (hạn = hôm nay + 30 ngày)

✔ Kết quả: gói **Đã đóng gói**, cổng **T4 = Đạt**. Không có máy in thật → nhãn "chờ in" (bình thường).

---

## T5 Nạp mẻ tiệt khuẩn — `?station=TR-005` — thẻ `THE-KTV-01`

**Test hằng ngày máy hấp** (nút "Test hằng ngày", làm 1 lần/ngày)
1. `TB-0014` → ghi **Bowie-Dick = Đạt** (lô test gõ tùy ý, hạn ≥ hôm nay)
2. Ghi tiếp **Leak (rò rỉ) = Đạt** → **Quay lại nạp**

**Nạp mẻ**
3. `TB-0014` → chọn chương trình `HAP-TEST-134`
4. `CY-…` (Cycle ID từ T4)
5. Bấm **Hoàn thành nạp → sinh mã mẻ** → **ghi lại `ME-…`**

**Dữ liệu chu trình** (chip "Dữ liệu chu trình")
6. `TB-0014` → `ME-…`
7. Temperature `134` · Pressure `2,1` · giờ kết thúc · tick xác nhận · gõ thẻ **`THE-KTV-01`** vào ô "Quét thẻ nhân viên để xác nhận" → **Lưu dữ liệu nhập tay và xác nhận**

✔ Kết quả: mẻ **Hoàn tất chu trình**, gói "Trong mẻ".

---

## T5b Dỡ mẻ – giải phóng — vẫn `?station=TR-005`

**Phần KTV** (đang đăng nhập `THE-KTV-01`)
1. Bấm **Dỡ và giải phóng** → `TB-0014` → `ME-…`
2. Kết quả chu trình **Đạt** · tick xác nhận → **Ghi kết quả chu trình**
3. **Chỉ thị hóa học loại 5 = Đạt** → **Ghi chỉ thị**
4. Bowie-Dick: màn tự lấy từ test hằng ngày (không cần ghi lại)

**Phần giám sát R02**
5. Bấm **Log out** → gõ thẻ **`THE-R02-01`**
6. **Dỡ và giải phóng** → `TB-0014` → `ME-…`
7. Ô **PIN R02**: `246810` → **Giải phóng mẻ**

✔ Kết quả: gói **Đã giải phóng**, cổng **T5 = Đạt**, bộ chuyển **Vô khuẩn**.

---

## T6 Kho vô khuẩn — `?station=TR-006` — thẻ `THE-KTV-01`

1. `CY-…`
2. `KE-0004`

✔ Kết quả: "Gói … đã cất trên KE-0004", gói **Trong kho vô khuẩn**.

---

## T7 Cấp phát — `?station=TR-007` — thẻ `THE-KTV-01`

1. Chạm chọn khoa **Khoa ngoại tracecore**
2. `CY-…` → gói vào phiếu
3. Bấm **Người nhận ký** → **Ký bằng thẻ** → gõ `THE-DD-01`
4. Bấm **Xác nhận và in**

✔ Kết quả: phiếu cấp phát ghi sổ, gói **Đã cấp phát**, bộ **Tại khoa**.

---

## T8 Quét sử dụng — `?station=TR-008` — thẻ `THE-DD-01`

1. `CY-…` → hiện thẻ gói (không cảnh báo khác khoa)
2. Mã bệnh nhân `BN12345678` · Mã ca mổ `CA-TEST-01` · Phẫu thuật viên `BS Test` · Phòng `P1`
3. Bấm **Xác nhận: ghi nhận sử dụng gói này**

✔ Kết quả: gói **Đã sử dụng**, bộ **Chờ tiếp nhận** → vòng khép kín, có thể quay lại T1 cho chu trình 2.

---

## Thử chặn (sau khi xong luồng chính)

| Ở đâu | Làm | Phải thấy |
| --- | --- | --- |
| T8 | Quét lại cùng `CY-…` | Báo đỏ: gói đã sử dụng |
| T6 | Quét `CY-…` trước khi T5b giải phóng | Báo đỏ: gói chưa giải phóng |
| T5b | KTV tự nhập PIN rồi giải phóng | Báo đỏ: cần R02 xác nhận |
| T3 | Quét bộ trước khi xong T2 | Báo đỏ: chưa qua bước trước (đã thấy lúc 14:03) |
