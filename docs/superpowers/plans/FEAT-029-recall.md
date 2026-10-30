# FEAT-029 — Thu hồi theo mẻ / lô chỉ thị (UC-14, SCR-14, WF-05)

**Đầu vào:** implementation-plan §3 FEAT-029; SRS FR-M2-20 (.1–.3), FR-M2-11.7, FR-M2-12.2 (phần thu hồi), BRU-REP-007;
UC-14 (luồng chính bước 3–6, A1, E2, E3); architecture §5.3 (DT-RECALL, child `Recall Order Pack`, WF-05, tên `TH-`),
§6.6 (sơ đồ thu hồi). Phụ thuộc FEAT-030 (Incident CAPA) đã có.

**Phạm vi:** DocType `Recall Order` + child `Recall Order Pack` (module Reprocessing), dịch vụ
`tracecore.reprocessing.recall`, RPC `tracecore.v1.recall.*`, form Desk SCR-14 (lập lệnh từ mẻ, xác nhận từng gói, đóng),
hook BI dương tính / mẻ Không đạt, nhắc khoa sau 2 giờ. Ngoài phạm vi: màn PDA xác nhận (FEAT-009 offline), email/SMS
(FEAT-010; tạm Notification Log), màn truy xuất (FEAT-028).

## Quyết định thiết kế

| Mã | Quyết định | FR / UC |
| --- | --- | --- |
| R1 | `Recall Order` submittable, tên `TH-.YYYY.-.#####`; Open (Nháp) → Closed (Ghi sổ, do dịch vụ). Không xóa, không hủy kiểu Frappe. | FR-M2-20, WF-05 |
| R2 | Gói bị ảnh hưởng = mọi Pack của mẻ (hoặc của mọi mẻ có chỉ thị dùng lô `lot`) ở trạng thái Released, In Sterile Stock, Issued, Used; không nhập tay. Không có gói nào → `RECALL_EMPTY`. Một mẻ chỉ có một lệnh đang mở (hook trả lệnh cũ; lập tay → `RECALL_EXISTS`). | FR-M2-20, UC-14 A1 |
| R3 | Khi lập lệnh: gói Released / In Sterile Stock → Pack `Recalled` và bộ về Chờ tiếp nhận (`step_gate.return_to_receipt`), dòng "Khóa trong kho"; gói Issued → Pack `Recalled` (T8 chặn `PACK_RECALLED`), dòng "Thu về từ khoa" kèm khoa nhận; gói Used → giữ Used, dòng "Báo bác sĩ" kèm mã bệnh nhân đã che (`Usage Record.patient_code_masked`). | FR-M2-20.1, .3, UC-14 E2 |
| R4 | Xác nhận từng dòng: "Khóa trong kho" do R02/R06; "Thu về từ khoa" do R02 hoặc nhân viên R08 thuộc đúng khoa; "Báo bác sĩ" chỉ R01. Đóng lệnh chỉ R01/R02 khi 100 % dòng đã xác nhận (`RECALL_INCOMPLETE`). | FR-M2-20.2, UC-14 bước 5–6 |
| R5 | Lệnh liên kết một Incident CAPA: dùng NC Load Failed của mẻ nếu đã có, nếu không tự tạo (Load Failed, mức High). | UC-14 bước 6, architecture §6.6 |
| R6 | Thông báo chuông Desk cho R01, R02 và người dùng R08 thuộc các khoa có gói; job 15 phút nhắc lại khoa và R01 cho dòng chưa xác nhận quá 2 giờ, tối đa một lần mỗi 2 giờ. | FR-M2-20, UC-14 E3 |
| R7 | Hook `tracecore_bi_positive` (BI dương sau giải phóng) và `tracecore_after_load_failed` (chỉ khi mẻ có gói đã giải phóng trở đi) tự lập lệnh; `bi_result` trả thêm mã lệnh. | FR-M2-11.7, FR-M2-12.2 |
| R8 | Quyền theo ma trận DT-RECALL (ghi chú đổi thành FEAT-029); sinh lại `custom_docperm.json`. | NFR-SEC |

## Task (TDD)

1. DocType + quyền + Audit. Test: tên `TH-`, không xóa.
2. `recall.create` (R2, R3, R5, R6). Test: phân loại 4 trạng thái gói, khóa gói/bộ, mã BN che, NC liên kết, thông báo, theo lô chỉ thị, rỗng, trùng.
3. `confirm_pack`, `close` (R4). Test vai trò từng loại dòng, đóng khi đủ 100 %.
4. Hook (R7) + nhắc 2 giờ (R6). Test tích hợp BI dương tính sau giải phóng tạo lệnh; T7 không cấp và T8 chặn gói đã thu hồi.
5. RPC + form Desk + nút "Lập lệnh thu hồi" trên mẻ + vi.csv + test desk assets.
6. Test module liên quan, pre-commit, merge `develop` local.
