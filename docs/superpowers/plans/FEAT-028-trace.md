# FEAT-028 — Truy xuất hai chiều (UC-14 bước 1–2, SCR-14)

**Đầu vào:** implementation-plan §3 FEAT-028; SRS FR-M2-19 (.1–.4), NFR-PERF-04, NFR-SEC-02; UC-14 (bước 1–2, A2, E1,
E2); architecture §5.3 (DT-USAGE), §8 bảo mật (mã BN: `patient_code_hash` HMAC-SHA256 để tra cứu không giải mã).

**Phạm vi:** trường `Usage Record.patient_code_hash` + patch điền cho bản ghi cũ; `tracecore.core.crypto.patient_hash`;
dịch vụ `tracecore.reprocessing.trace.query`; RPC `tracecore.v1.trace.query`; Script Report "Pack Trace" (xuất PDF bằng
in báo cáo chuẩn của Desk). Ngoài phạm vi: cổng khoa SCR-13 (R08 dùng báo cáo trên Desk, giới hạn khoa mình).

## Quyết định thiết kế

| Mã | Quyết định | FR |
| --- | --- | --- |
| T1 | Mã BN tra bằng `patient_code_hash` = HMAC-SHA256(khóa, mã đã bỏ khoảng trắng hai đầu và viết hoa); khóa `tc_patient_hash_key` trong site_config, không có thì dùng `encryption_key` của site. Hash ghi khi `Usage Record` lưu mã (kể cả nhập bổ sung ca cấp cứu); patch điền cho bản ghi cũ. Chỉ khớp chính xác. | FR-M2-19, .1, NFR-SEC-02 |
| T2 | Một "chuỗi" = (Set ID, chu trình). Tiêu chí: mã BN, Set ID, Cycle ID, mẻ, máy (máy rửa hoặc máy tiệt khuẩn), người dùng (User), khoảng ngày; nhiều tiêu chí thì lấy giao. Tối đa 50 chuỗi mới nhất. | FR-M2-19 |
| T3 | Sự kiện mỗi chuỗi: cổng T1–T5 từ `Step Gate Result` (người, thời điểm, trạm, chứng từ, kết quả; máy lấy từ lô rửa / mẻ), T6 nhập kho, T7 cấp phát (khoa, người nhận), T8 sử dụng (khoa, mã BN đã che). Sắp theo thời gian. | FR-M2-19.3 |
| T4 | Tra theo mẻ trả mọi gói của mẻ kèm trạng thái và mã BN che nếu đã dùng. | FR-M2-19.2 |
| T5 | Không có kết quả → danh sách rỗng kèm gợi ý tiêu chí khác. | FR-M2-19.4, UC-14 E1 |
| T6 | Quyền: R01, R02, System Manager xem mọi chuỗi; R08 chỉ chuỗi có gói cấp cho / dùng ở khoa của mình; vai trò khác bị từ chối. Mã BN chỉ ở dạng che; xem đủ vẫn qua `v1.usage.reveal_patient_code`. | UC-14, NFR-SEC-02 |

## Task (TDD)

1. `core.crypto.patient_hash` + trường hash trên Usage Record + patch. Test: hash ghi khi xác nhận sử dụng, chuẩn hóa, patch điền bản ghi cũ.
2. `trace.query` theo từng tiêu chí (T2–T5). Test chuỗi đủ T1→T8, tra theo mã BN / Set ID / Cycle ID / mẻ / máy / người / ngày, không lộ mã BN.
3. Quyền (T6). Test R08 khác khoa, vai trò không được phép.
4. RPC + Script Report + vi.csv + test báo cáo.
5. Test module liên quan, pre-commit, merge `develop` local.
