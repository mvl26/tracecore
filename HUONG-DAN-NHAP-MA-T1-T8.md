# Hướng dẫn nhập mã T1 → T8 — TraceCore (site dev http://localhost:8022)

Đăng nhập Desk: `Administrator` / `123456` (2FA đã tắt).
Mở trạm: `http://localhost:8022/app/station?station=TR-00x` (hoặc launcher `/app/tracecore` → chọn trạm → Vào trạm).
**Nhập mã = gõ (hoặc dán) vào ô quét trên cùng rồi nhấn Enter.** Ô nào khác thì có ghi rõ.

---

## 0. Bảng mã dùng khi test

### Thẻ nhân viên

| Thẻ | Người | Dùng ở |
| --- | --- | --- |
| `THE-KTV-01` | KTV Test (R03, R04, R05, R06) | Đăng nhập T1, T2, T3, T4, T5, T6, T7 |
| `THE-GIAO-01` | Người giao Test — Khoa ngoại tracecore | T1 (người giao) |
| `THE-R02-01` | Giám sát R02 Test — **PIN `246810`** | T5b (giải phóng mẻ) |
| `THE-DD-01` | Điều dưỡng Test — Khoa ngoại tracecore (R08) | T7 (người nhận ký), đăng nhập T8 |

### Mã cố định

| Mã | Là gì | Dùng ở |
| --- | --- | --- |
| `9520000NGOAI1000001` | **Set ID** bộ "Bộ ngoại test" (loại `NGOAI1`, BOM: M1 × 1) | T1, T2, T3, T4 |
| `TB-0013` | Máy rửa test — chương trình `RUA-TEST-01` (90–95 °C) | T2 |
| `TB-0014` | Máy hấp test — chương trình `HAP-TEST-134` (132–138 °C; 0–2,3 bar) | T5, T5b |
| `LOT-CI5-TEST-01` | Lô chỉ thị hóa học loại 5 | T4 |
| `KE-0004` | Kệ test A (kho vô khuẩn) | T6 |
| `HOAN-THANH-NAP` | Mã lệnh "Hoàn thành nạp" (thay cho bấm nút) | T2, T5 |

### Mã sinh ra trong lúc test — ghi lại

| Mã | Sinh ở | Giá trị |
| --- | --- | --- |
| Mã lô rửa `LR-…` | T2 — Hoàn thành nạp | **`LR-261026-01`** (đã sinh) |
| Cycle ID `CY-…` | T4 — Hoàn thành đóng gói | `CY-____________` |
| Mã mẻ `ME-…` | T5 — Hoàn thành nạp | `ME-__________` |

> **Set ID dùng từ T1 đến T4. Cycle ID dùng từ T5 đến T8.**

---

## T1 — Tiếp nhận · `?station=TR-001` · ✅ đã xong (phiếu RC-2026-00001)

| # | Nhập / bấm | Mã |
| --- | --- | --- |
| 1 | Thẻ người thao tác | `THE-KTV-01` |
| 2 | Thẻ người giao | `THE-GIAO-01` |
| 3 | Set ID | `9520000NGOAI1000001` |
| 4 | Bấm **Xác nhận tất cả thành phần** → **Xác nhận bộ** → **Ghi sổ phiếu** | — |

Kết quả: bộ **Đang xử lý**, chu trình 1, cổng **T1 Đạt**.

---

## T2 — Rửa khử khuẩn · `?station=TR-002`

| # | Chế độ | Nhập / bấm | Mã |
| --- | --- | --- | --- |
| 1 | — | Thẻ người thao tác | `THE-KTV-01` |
| 2 | Test hằng ngày | ✅ đã ghi hôm nay (washer_cleaning Đạt) — bỏ qua | — |
| 3 | **Nạp lô** | QR máy rửa | `TB-0013` |
| 4 | Nạp lô | Set ID | `9520000NGOAI1000001` |
| 5 | Nạp lô | Bấm **Hoàn thành nạp → sinh mã lô** | ✅ đã sinh `LR-261026-01` |
| 6 | **Dỡ lô** | QR máy rửa | `TB-0013` |
| 7 | Dỡ lô | Mã lô | `LR-261026-01` |
| 8 | Dỡ lô | Form nhập tay: Temperature `92` · Kết quả máy **Đạt** · giờ bắt đầu < giờ kết thúc · **tải 1 ảnh bất kỳ** · Cảnh báo **Không** · tick xác nhận → **Lưu dữ liệu nhập tay và xác nhận** | — |
| 9 | Dỡ lô | Kết quả chu trình **Đạt** · Test làm sạch **Đạt** · tick → **Ghi kết quả cho 1 bộ** | — |

Kết quả: lô rửa ghi sổ, cổng **T2 Đạt**.

---

## T3 — Kiểm tra, lắp ráp · `?station=TR-003`

| # | Nhập / bấm | Mã |
| --- | --- | --- |
| 1 | Thẻ người thao tác | `THE-KTV-01` |
| 2 | Set ID | `9520000NGOAI1000001` |
| 3 | Bấm **Xác nhận tất cả thành phần** (BOM: M1 × 1) → **Ghi nhận kiểm đếm** | — |

Kết quả: cổng **T3 Đạt**, "Đóng gói: sẵn sàng".

---

## T4 — Đóng gói, sinh Cycle ID · `?station=TR-004`

| # | Nhập / bấm | Mã |
| --- | --- | --- |
| 1 | Thẻ người thao tác | `THE-KTV-01` |
| 2 | Set ID | `9520000NGOAI1000001` |
| 3 | Bấm **Xác nhận tất cả thành phần** | — |
| 4 | **Ô "Quét lô chỉ thị" riêng** (không phải ô quét trên cùng) | `LOT-CI5-TEST-01` |
| 5 | Bấm **Xác nhận hoàn thành đóng gói** → **ghi lại Cycle ID** | → `CY-…` |

Kết quả: gói **Đã đóng gói**, hạn = hôm nay + 30 ngày, cổng **T4 Đạt**. Không có máy in → nhãn "chờ in" (bình thường).

---

## T5 — Nạp mẻ tiệt khuẩn · `?station=TR-005`

| # | Chế độ | Nhập / bấm | Mã |
| --- | --- | --- | --- |
| 1 | — | Thẻ người thao tác | `THE-KTV-01` |
| 2 | **Test hằng ngày** | QR máy hấp → ghi **Bowie-Dick = Đạt** (lô test tùy ý, hạn ≥ hôm nay) | `TB-0014` |
| 3 | Test hằng ngày | Ghi tiếp **Leak = Đạt** → **Quay lại nạp** | — |
| 4 | **Nạp mẻ** | QR máy hấp, chọn chương trình `HAP-TEST-134` | `TB-0014` |
| 5 | Nạp mẻ | Cycle ID | `CY-…` (từ T4) |
| 6 | Nạp mẻ | Bấm **Hoàn thành nạp → sinh mã mẻ** → **ghi lại mã mẻ** | → `ME-…` |
| 7 | **Dữ liệu chu trình** | QR máy hấp | `TB-0014` |
| 8 | Dữ liệu chu trình | Mã mẻ | `ME-…` |
| 9 | Dữ liệu chu trình | Temperature `134` · Pressure `2,1` · giờ kết thúc · tick xác nhận | — |
| 10 | Dữ liệu chu trình | Ô **"Quét thẻ nhân viên để xác nhận"** → **Lưu dữ liệu nhập tay và xác nhận** | `THE-KTV-01` |

Kết quả: mẻ **Hoàn tất chu trình**.

---

## T5b — Dỡ mẻ, giải phóng · vẫn `?station=TR-005`

| # | Người | Nhập / bấm | Mã |
| --- | --- | --- | --- |
| 1 | KTV | Bấm **Dỡ và giải phóng** → QR máy hấp | `TB-0014` |
| 2 | KTV | Mã mẻ | `ME-…` |
| 3 | KTV | Kết quả chu trình **Đạt** · tick → **Ghi kết quả chu trình** | — |
| 4 | KTV | **Chỉ thị hóa học loại 5 = Đạt** → **Ghi chỉ thị** (Bowie-Dick tự lấy từ test hằng ngày) | — |
| 5 | — | Bấm **Log out** | — |
| 6 | R02 | Thẻ giám sát | `THE-R02-01` |
| 7 | R02 | **Dỡ và giải phóng** → QR máy hấp → mã mẻ | `TB-0014` → `ME-…` |
| 8 | R02 | Ô **PIN R02** → **Giải phóng mẻ** | `246810` |

Kết quả: gói **Đã giải phóng**, cổng **T5 Đạt**, bộ **Vô khuẩn**.

---

## T6 — Kho vô khuẩn · `?station=TR-006`

| # | Nhập / bấm | Mã |
| --- | --- | --- |
| 1 | Thẻ người thao tác | `THE-KTV-01` |
| 2 | Cycle ID | `CY-…` |
| 3 | Mã kệ | `KE-0004` |

Kết quả: gói **Trong kho vô khuẩn** tại KE-0004.

---

## T7 — Cấp phát · `?station=TR-007`

| # | Nhập / bấm | Mã |
| --- | --- | --- |
| 1 | Thẻ người thao tác | `THE-KTV-01` |
| 2 | Chạm chọn khoa **Khoa ngoại tracecore** | — |
| 3 | Cycle ID | `CY-…` |
| 4 | Bấm **Người nhận ký** → **Ký bằng thẻ** → thẻ người nhận | `THE-DD-01` |
| 5 | Bấm **Xác nhận và in** | — |

Kết quả: gói **Đã cấp phát**, bộ **Tại khoa**.

---

## T8 — Quét sử dụng · `?station=TR-008`

| # | Nhập / bấm | Mã |
| --- | --- | --- |
| 1 | Thẻ người thao tác (**điều dưỡng**, không phải KTV) | `THE-DD-01` |
| 2 | Cycle ID | `CY-…` |
| 3 | Mã bệnh nhân · Mã ca mổ · Phẫu thuật viên · Phòng | `BN12345678` · `CA-TEST-01` · `BS Test` · `P1` |
| 4 | Bấm **Xác nhận: ghi nhận sử dụng gói này** | — |

Kết quả: gói **Đã sử dụng**, bộ **Chờ tiếp nhận** → quay lại T1 cho chu trình 2.

---

## Tóm tắt một dòng mỗi trạm

| Trạm | Thẻ đăng nhập | Nhập lần lượt |
| --- | --- | --- |
| T1 | `THE-KTV-01` | `THE-GIAO-01` → `9520000NGOAI1000001` |
| T2 | `THE-KTV-01` | `TB-0013` → `9520000NGOAI1000001` → Hoàn thành nạp · Dỡ: `TB-0013` → `LR-261026-01` |
| T3 | `THE-KTV-01` | `9520000NGOAI1000001` |
| T4 | `THE-KTV-01` | `9520000NGOAI1000001` → `LOT-CI5-TEST-01` (ô riêng) → **CY-…** |
| T5 | `THE-KTV-01` | Test ngày `TB-0014` · `TB-0014` → `CY-…` → **ME-…** · Dữ liệu: `TB-0014` → `ME-…` → `THE-KTV-01` |
| T5b | `THE-KTV-01` rồi `THE-R02-01` | `TB-0014` → `ME-…` · PIN `246810` |
| T6 | `THE-KTV-01` | `CY-…` → `KE-0004` |
| T7 | `THE-KTV-01` | chọn khoa → `CY-…` → `THE-DD-01` |
| T8 | `THE-DD-01` | `CY-…` |

## Khi màn báo đỏ

| Báo | Nghĩa | Làm |
| --- | --- | --- |
| Không tìm thấy bộ / Mã không hợp lệ | Gõ sai mã | Dán lại đúng mã từ tài liệu này |
| Chưa qua bước trước (GATE_PREV_NOT_PASSED) | Bộ chưa xong trạm trước | Quay lại trạm trước |
| Cần test hằng ngày (DAILY_TEST_REQUIRED) | Máy chưa test hôm nay | Bấm **Test hằng ngày** |
| Lô test hết hạn (TEST_LOT_EXPIRED) | Hạn lô test < hôm nay | Chọn hạn ≥ hôm nay |
| Card login was rejected | Thẻ không có năng lực ở trạm này | Kiểm tra đúng thẻ cho đúng trạm (bảng 0) |
