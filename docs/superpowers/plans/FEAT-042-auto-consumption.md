# FEAT-042 — Tiêu hao tự động theo lô rửa / mẻ và xuất kho thủ công FEFO

**Nhánh:** `feat/FEAT-042-auto-consumption` · **Module:** M6 `inventory` · **UC:** UC-25 · **SCR:** SCR-25 (WEB)

**FR / BRU đáp ứng:** FR-M6-03, FR-M6-03.2, FR-M6-04, FR-M6-04.1, FR-M6-04.3, FR-M6-04.4; BRU-INV-001 (lô hết hạn bị chặn, FEFO), BRU-INV-002 (tiêu hao tự động theo định mức × số gói/kg khi hoàn tất).

**Chưa đạt trong FEAT-042 (ghi rõ để chủ đầu tư quyết):**

- FR-M6-03.1 (điều chỉnh số thực dùng của mẻ trước khi hoàn tất, kèm lý do): lô rửa đã nhập `qty` hóa chất lúc bắt đầu nên dùng luôn số đó; mẻ tiệt khuẩn cần nơi lưu số điều chỉnh (DocType/trường mới) → cần amendment riêng.
- FR-M6-04.2 (kiểm hạn chỉ thị sinh học tại thời điểm dùng): thuộc T5/T5b, đã có `check_chemical_lot`; không đổi ở đây.
- Lô giặt (FEAT-034, đồ vải): module `linen` chưa có; FEAT-034 sẽ nối vào cùng hàm `consume.consume_for`.
- Nhãn/bao gói/chỉ thị theo Cycle ID (`tracecore_after_cycle_id`): `Program Consumable` không có dòng theo loại gói nên chưa có định mức để trừ.
- Chi phí mẻ (FEAT-046), kiểm kê/cảnh báo tồn tối thiểu (FEAT-043).

## Quyết định thiết kế

| # | Quyết định | Căn cứ |
| --- | --- | --- |
| Q1 | Hàm lõi `tracecore.inventory.consume.consume_for(source_doctype, source_name, lines, *, reason)` tạo **một** Stock Entry `Material Issue` đã ghi sổ cho mỗi nguồn. Idempotent theo Custom Field `Stock Entry.tc_source_doctype` + `tc_source_name` (phiếu chưa hủy đã có thì trả phiếu đó, không tạo thêm). | FR-M6-03; implementation-plan dòng FEAT-042 (`tc_source`) |
| Q2 | Hook nối M2 → M6: `tracecore_after_wash_complete` và `tracecore_after_load_release` đăng ký `tracecore.inventory.consume.on_wash_complete` / `on_load_release` (M2 không import M6). | architecture D9, A-42 |
| Q3 | Lô rửa: dòng hóa chất lấy từ hồ sơ lô (`item`, `lot`, `qty` người vận hành đã quét/nhập). `qty` = 0 thì dùng định mức chương trình. Các `Program Consumable` khác (không phải hóa chất của lô) trừ theo `qty_per_load + qty_per_pack × số bộ`, lô chọn FEFO. | FR-M6-03; Q9 FEAT-021 |
| Q4 | Mẻ tiệt khuẩn: mỗi `Program Consumable` trừ `qty_per_load + qty_per_pack × số gói`, lô chọn FEFO; ghi lô thực dùng vào Stock Entry (`tc_source_*`, dòng có `batch_no`) để truy xuất. | FR-M6-03 |
| Q5 | Chọn lô FEFO: lô còn tồn dương, **chưa hết hạn** (hạn ≥ hôm nay giờ VN), hạn gần trước, lô không hạn xếp sau cùng, rồi theo tên lô. Một dòng định mức có thể tách nhiều lô khi lô đầu không đủ. | BRU-INV-001; FR-M6-04 |
| Q6 | Tồn không đủ (FR-M6-03.2): ERPNext chặn tồn âm theo lô bất kể cờ `allow_negative_stock`, nên **trừ phần đang có, không trừ vượt**; phần thiếu ghi vào `tc_reason` của phiếu và gửi thông báo `CONSUMPTION_SHORT` cho R09; mẻ vẫn hoàn tất. Khác chữ SRS (tồn âm) — ghi ở A-46. | FR-M6-03.2; UC-25 A1; P-12 |
| Q7 | Không có định mức (UC-25 E2): không trừ, thông báo `CONSUMPTION_NO_NORM` cho R09. | UC-25 E2 |
| Q8 | Lỗi bất ngờ khi trừ kho không được làm hỏng mẻ: chạy trong savepoint, bắt lỗi, ghi Error Log + thông báo `CONSUMPTION_FAILED`; mẻ hoàn tất như bình thường và R09 xử lý tay. | FR-M6-03.2 |
| Q9 | Xuất thủ công `tracecore.v1.stock.issue_manual(item, qty, reason, lots=None, department=None, warehouse=None)` (`@idempotent`): bắt buộc lý do (`REASON_REQUIRED`), chặn lô hết hạn (`LOT_EXPIRED`), lô không phải lô hạn gần nhất thì vẫn xuất nhưng trả `warnings` (FR-M6-04.4), tồn không đủ thì chặn (`STOCK_INSUFFICIENT`). `department` ghi vào lý do khi xuất cho khoa khác (A2). Vai R05, R06, R09, R02, System Manager. | FR-M6-04.*; UC-25 E1, E3 |
| Q10 | `tracecore.v1.stock.suggest_lots(item, qty)` (GET): gợi ý lô FEFO để màn xuất kho điền sẵn. | FR-M6-04 |
| Q11 | Custom Field mới trên `Stock Entry`: `tc_source_doctype` (Data), `tc_source_name` (Data), `tc_reason` (Small Text) — đã nêu trong architecture §5.3 (V6/V14), nay tạo. Lọc fixtures `Stock Entry-tc_%`. | architecture V14 |
| Q12 | Màn SCR-25: dùng form Stock Entry của Desk (bộ lọc `tc_source_doctype`) cộng link trên trang chủ; không viết Page mới. | ADR-002 |

## Task (TDD)

1. **T1 (Q5)** `consume.pick_lots(item, qty, today)` — FEFO, bỏ lô hết hạn, tách lô, phần thiếu. Test trước.
2. **T2 (Q1, Q11)** `consume.consume_for` + Custom Field + idempotent. Test: tạo 1 Stock Entry ghi sổ, tồn giảm, chạy lại không nhân đôi.
3. **T3 (Q3, Q2)** `on_wash_complete`. Test: lô rửa Đạt trừ hóa chất đúng lô, `qty` 0 dùng định mức, lô Không đạt không trừ.
4. **T4 (Q4, Q2)** `on_load_release`. Test: định mức × gói, nhiều lô, truy xuất lô vào Stock Entry.
5. **T5 (Q6–Q8)** thiếu tồn, không có định mức, lỗi trừ kho — mẻ vẫn hoàn tất, có thông báo `CONSUMPTION_*`.
6. **T6 (Q9, Q10)** `v1/stock.py` — xuất thủ công và gợi ý lô. Test đủ lỗi E1, E3, cảnh báo FR-M6-04.4.
7. **T7** link trang chủ (nhóm Kho), bản dịch `vi.csv`, amendment A-46, RTM, lint.

Marker `@bru("BRU-INV-001")` cho T1/T6, `@bru("BRU-INV-002")` cho T3/T4.
