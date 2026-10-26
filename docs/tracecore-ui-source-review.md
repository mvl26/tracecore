# Đối chiếu nguồn giao diện TraceCore

Ngày rà: 2026-10-25. Đã đọc HTML #17 v1.10 (499 dòng gồm CSS, HTML, JavaScript) và xem trực tiếp đủ 21 PNG. Nguồn do người dùng cung cấp tại Downloads; ảnh giải nén trong `.superpowers/references/ui-v1.10/TraceCore_UI_Screenshots/`. Không chạy JavaScript prototype trong quá trình đọc.

## Nguồn đã xem

| Ảnh | Nội dung | Liên hệ với inventory hiện tại |
| --- | --- | --- |
| 01 | Chọn không gian Trưởng khoa/KTV/Khoa | Entry tham khảo, không phải xác thực production |
| 02 | Tổng quan Trưởng khoa, việc cần quyết định trước KPI và hai bảng | SCR-32 |
| 03 | Duyệt ghi đè, bảng bộ đạt/sắp đạt cơ số | SCR-31 |
| 04 | Thu hồi theo gói/khoa và danh sách NC | SCR-14/15 |
| 05 | Giá thành theo trạm và chi phí đầu vào | SCR-29 |
| 06 | Sổ tiệt khuẩn, tham số/CI/BI/người giải phóng, PDF/Excel | SCR-32 |
| 07–08 | T1: thẻ giao, xác nhận BOM, nhiều bộ và ghi chú | SCR-05 |
| 09–10 | T2: nạp máy/lô, dỡ và nhập tay có xác nhận | SCR-06 |
| 11 | T3: ảnh bộ/dụng cụ, cổng, cơ số, kiểm đếm | SCR-07 |
| 12–13 | T4: chỉ thị/bảo dưỡng/xác nhận và preview nhãn | SCR-08 |
| 14 | T5: máy/chương trình và gói trong mẻ | SCR-09 |
| 15 | T5b: kết quả, giải phóng bằng PIN, BI | SCR-10 |
| 16 | T6: vị trí, đủ 5 cổng, tồn kho/FEFO | SCR-11 |
| 17 | T7: khoa, cơ số, người nhận/ký và phiếu cấp | SCR-12 |
| 18 | Bộ tại khoa, cơ số và cảnh báo thu hồi | View DEPT của nghiệp vụ cấp phát |
| 19 | PDA quét sử dụng: ảnh đang ở trạng thái lỗi, ô quét bị bó hẹp | SCR-13/37; không sao chép lỗi layout |
| 20 | Khoa xác nhận thu hồi | View DEPT SCR-14 |
| 21 | Tra cứu theo bệnh nhân/Cycle ID: ảnh đang hiển thị kết quả thông báo | View DEPT SCR-14; timeline chi tiết T1–T8 có trong HTML |

21 ảnh là các trạng thái/view, không tương đương 21 SCR độc lập. HTML còn có bảng nhân sự/chứng chỉ, thiết bị/test ngày và view khoa gửi trả, đề nghị cấp, đồ vải; ZIP không có ảnh riêng cho tất cả các view này.

## Hệ quả với Admin Shell

Giữ bố cục điều hướng A nhưng theo visual nguồn: rail trắng, active nền xanh nhạt/vạch navy, thông tin người/vai trò, nền xám xanh, card trắng viền xanh nhạt, zonebar, breadcrumb và bảng header navy. Token đã điều chỉnh accessibility trong docs/tokens.json thắng màu CSS gốc, đặc biệt chữ trắng trên cam/xám. Không mang gradient/emoji placeholder ảnh vào sản phẩm.

Dashboard R01 có khối Cần quyết định của Trưởng khoa trên cùng: ghi đè, thu hồi, máy khóa/sắp kiểm định và chứng chỉ sắp hết hạn; sau đó KPI, sản lượng theo trạm và tồn khoa/cơ số. Mỗi nguồn chỉ xuất hiện khi backend thật và quyền truy cập đã sẵn sàng. Ưu tiên này khớp lựa chọn dashboard việc cần xử lý của người dùng.

Điều hướng theo vai trò của HTML cụ thể hơn mockup A tổng quát. Phải giữ nhãn tác vụ theo vai trò và badge việc chờ thay vì chỉ gom mọi vai trò vào một menu chung. KTV và R08 là surface riêng, chưa nằm trong đợt đổi frontend WEB.

## Khoảng trống và khác biệt phiên bản

- Nguồn vừa gửi không có form/list chi tiết SCR-01 Instrument, SCR-02 Set Type/BOM, SCR-03 Set Unit; chỉ có dữ liệu mẫu và lời dẫn ảnh được tải từ danh mục. Thiết kế ba màn phải dùng SRS/use-cases, architecture amendments và kế hoạch FEAT-014/015/016. Không gọi các màn tự suy ra là bản sao nguồn #17.
- HTML v1.10 hiển thị chọn role, thẻ + PIN và PIN mẫu kiểm tại client. WEB mới đã chốt Frappe session/2FA, quyền server. Giữ ý tưởng vào đúng không gian, không dùng cơ chế demo để xác thực.
- Set ID mẫu dùng AI (01)/(21), Cycle ID và DataMatrix có dữ liệu/hình minh họa; backend hiện hành dùng GIAI và GS1 theo các amendment. UI hiển thị dữ liệu server, không tái tạo encoder từ prototype.
- Dữ liệu, ngày tháng, tổng số, thông báo đã in/xuất, audit và trừ kho trong HTML là mô phỏng. Chỉ backend thành công mới báo hoàn tất.
- Ảnh 19 cho thấy input PDA bị bó và trạng thái không tìm thấy gói; ảnh 21 là trạng thái kết quả thông báo chứ chưa có timeline. Dùng luồng trong HTML và quy tắc UX để thiết kế đầy đủ các trạng thái.
- SCR-38..43 thuộc v1.11 không có mẫu trong HTML v1.10; tài liệu #09 chưa được cung cấp trực tiếp trong lượt này.

## Kết luận áp dụng

Nguồn gốc điều chỉnh chi tiết visual và cấu trúc menu của thiết kế Admin đã ghi; không đổi quyết định Vue 3/TypeScript/Vite, backend Frappe, session và phạm vi desktop/triển khai từng phần. Trước khi code từng màn, kế hoạch phải ánh xạ SCR → trường/hành động → RPC và permission → trạng thái lỗi → test; không suy ra yêu cầu nghiệp vụ mới từ dữ liệu demo.
