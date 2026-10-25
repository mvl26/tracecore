# TraceCore Admin — thiết kế frontend riêng

Ngày: 2026-10-25. Thiết kế được người dùng duyệt trong chat; văn bản cụ thể đang chờ review. Amendment A-35, bổ sung và thay thế quy định WEB của C-02/ADR-002. Không thay đổi kiosk, PDA hoặc Portal.

## Phạm vi và thứ tự chuyển đổi

**Làm rõ yêu cầu mới từ người dùng:** Admin tổng cần điều hướng tới các không gian của toàn bộ R01–R10, chia theo role, không chỉ dashboard của chính tài khoản quản trị. Nhóm sidebar mở ra các chức năng con; bấm chức năng mở đúng trang tương ứng (ví dụ R01 → Tổng quan hôm nay theo ảnh 02), có breadcrumb để quay về Admin. Nhóm KTV tách thành R03..R07, không gộp thành một role. R08 là khoa sử dụng/gửi–nhận–trả; bộ dụng cụ mượn ngoài bệnh viện (Loaner, SCR-04) là nghiệp vụ khác.

Đây là điều hướng/xem các không gian trong tài khoản Admin đang đăng nhập, không tự đăng nhập thành một nhân viên mẫu. Quyền xem tổng hợp liên role cần capability server riêng được cấp rõ cho Admin tổng; không suy ra từ role R10 cấu hình hoặc quyền vào Desk. Danh tính actor luôn là Admin thật; mở trang vai trò không tự cấp quyền duyệt, giải phóng, ký thay, xem mã bệnh nhân rõ hay vận hành trạm bỏ qua năng lực/thẻ/PIN. Phạm vi thao tác ghi tiếp tục theo quyền server; yêu cầu hiện tại xác nhận phạm vi xem và điều hướng liên role, chưa xác nhận cấp mọi quyền ghi cho Admin.

| Role (SRS §2.3) | Không gian trong Admin tổng |
| --- | --- |
| R01 Trưởng khoa KSNK | Tổng quan, ghi đè cơ số, thu hồi/sự cố, giá thành, thiết bị/test, nhân sự/chứng chỉ, sổ tiệt khuẩn và báo cáo |
| R02 Điều dưỡng trưởng / Giám sát CSSD | Điều phối, danh mục, phê duyệt/giải phóng, NC-CAPA, nhân sự/năng lực/ca, kiểm kê và xung đột đồng bộ |
| R03 KTV khu bẩn | T1 tiếp nhận, T2 nạp/dỡ lô rửa |
| R04 KTV khu sạch | T3 kiểm tra/lắp ráp, T4 đóng gói, bảo dưỡng và đề nghị ghi đè |
| R05 KTV tiệt khuẩn | Test ngày, T5 nạp mẻ, T5b dỡ/ghi kết quả/đề nghị giải phóng |
| R06 KTV kho vô khuẩn / cấp phát | T6 nhập/vị trí/FEFO, T7 cấp phát |
| R07 Nhân viên đồ vải & chất thải | Thu gom, giặt/cấp phát/đối chiếu đồ vải; thu gom/lưu giữ/bàn giao chất thải |
| R08 Nhân viên khoa sử dụng | Bộ tại khoa/cơ số, T8 sử dụng, gửi trả, đề nghị cấp, xác nhận thu hồi, đồ vải, tra cứu trong phạm vi khoa |
| R09 Kế toán / Vật tư | Kho vật tư/lô/hạn, chi phí, bảng giá, giá thành, xuất báo cáo |
| R10 Quản trị hệ thống (Phòng CNTT) | Khu/trạm, ngoại vi, tài khoản/quyền, mẫu nhãn/cấu hình, audit và hạ tầng |

Bảng là định hướng menu theo SRS, không thay thế ma trận permission và amendment của từng action. Người dùng thường chỉ thấy các nhóm được cấp; Admin tổng có quyền xem liên role riêng. Các màn STN/DEPT hiện hữu được mở qua điều hướng của Admin tổng với ngữ cảnh rõ ràng; việc thay giao diện hay mở bản xem quản trị cho các màn đó cần được cụ thể hóa trong kế hoạch, không tự mở rộng thành viết lại cả kiosk/PDA/Portal.

Giai đoạn 1 xây Admin Shell: login mang thương hiệu TraceCore, xác thực Frappe, điều hướng theo quyền, dashboard việc cần xử lý, hết phiên/đăng xuất và kiểm soát truy cập Desk. Giai đoạn 2 chuyển lần lượt Instrument, Instrument Set Type/BOM và Set Unit. Mỗi màn chuyển phải hoàn thành chức năng tương ứng đã có trước khi đưa vào menu nghiệp vụ. Không dẫn người dùng nghiệp vụ về Desk hoặc hiển thị placeholder như chức năng đã sẵn sàng. Các phân hệ chưa chuyển không xuất hiện trong menu người dùng; giữ màn cũ cho kỹ thuật trong thời gian chuyển đổi.

## Kiến trúc và build

Vue 3 + TypeScript + Vite, Vue Router; mã nguồn tại frontend/. Build thành assets có hash của app tracecore, HTML entry được Frappe phục vụ tại /tracecore và mọi deep link /tracecore/*. Backend và frontend cùng origin trong bản build triển khai. Dev dùng Vite và proxy cùng origin tới Frappe; không lưu token xác thực trong localStorage. Khóa dependency trong lockfile, chọn phiên bản tương thích Node 18 hiện có khi lập kế hoạch chi tiết; không tự nâng Node hoặc Frappe.

Trang SPA không tải Desk shell, frappe.boot hay navbar/sidebar ERPNext. Backend tiếp tục dùng Frappe v15, ERPNext, HRMS, DocType, permission, audit và các dịch vụ nghiệp vụ hiện hữu. Không chỉnh mã framework, không thêm DocType nghiệp vụ.

## Session, 2FA và phân quyền

Login và 2FA dùng luồng xác thực server Frappe hiện hành, bao gồm khóa đăng nhập, hết hạn mật khẩu và các bước bắt buộc của tài khoản. Chỉ chuyển sang màn có dữ liệu sau khi xác thực hoàn tất. Session cookie theo cơ chế Frappe; bootstrap cung cấp user, capability và CSRF token cần thiết. POST có CSRF và các RPC nghiệp vụ hiện có tiếp tục yêu cầu idempotency nếu đã quy định.

Menu và nút dựa trên capability trả từ server để hỗ trợ trải nghiệm; mỗi RPC vẫn tự kiểm tra quyền DocType, quyền theo bản ghi/khoa và action. Không coi ẩn menu là bảo mật. Bootstrap không chứa secrets, PIN hoặc dữ liệu bệnh nhân. Hết session chuyển về login và chỉ giữ return URL nội bộ hợp lệ; không tự phát lại thao tác ghi chưa rõ kết quả.

Desk chỉ cho Administrator và tài khoản có role kỹ thuật riêng TraceCore Desk Access được cấp rõ ràng; không mặc định cấp cho TC R10 hay System Manager. Đây là quyền mở shell, không thay đổi quyền dữ liệu Frappe. Kiểm tra ở server cho /app và deep link Desk; người nghiệp vụ chuyển về /tracecore. Ngoại lệ rõ ràng cho /app/station và các route station hiện hữu, giữ nguyên kiểm tra quyền/thẻ/PIN của trạm. /app/tracecore cũ chuyển đến SPA. API và assets không bị redirect thành HTML.

## Giao diện

Đối chiếu nguồn gốc ngày 2026-10-25: đã đọc HTML `17 Giao dien theo vai tro v1_10 20260920.html` và xem 21 PNG trong `TraceCore_UI_Screenshots.zip`. Ghi nhận chi tiết tại [UI source review](tracecore-ui-source-review.md). Khung A chỉ chốt kiểu điều hướng, không thay thế thiết kế nguồn: dùng sidebar trắng, mục active xanh nhạt có vạch navy, thông tin người/vai trò ở đầu sidebar, dải zonebar WEB, breadcrumb, card phẳng và bảng header navy. Dashboard đặt khối việc cần quyết định trước KPI. Sidebar navy trong mockup sơ bộ không phải chuẩn triển khai.

Menu WEB theo vai trò thực tế: R01 có các nhóm Tổng quan hôm nay, Ghi đè cơ số, Thu hồi & sự cố, Giá thành tái xử lý, Thiết bị & test ngày, Nhân sự & chứng chỉ, Sổ tiệt khuẩn điện tử khi các màn tương ứng sẵn sàng. Dụng cụ & bộ bổ sung cho vai trò có quyền; không áp menu R01 cho mọi người. Phân kỳ chuyển màn giữ như đã chốt; danh mục nguồn là đích đầy đủ, không phải cam kết tất cả có trong bản Shell đầu.

HTML v1.10 là prototype tham khảo hình thức và luồng, không là triển khai bảo mật/GS1. Quy tắc mới hơn trong SRS v1.11 và các amendment tiếp tục có hiệu lực; không sao chép PIN demo, chọn vai trò để tự cấp quyền, số liệu giả hoặc sinh mã ở browser. SCR-01..03 chưa có mockup chi tiết trong nguồn vừa gửi: phải đối chiếu SRS/use-cases và FEAT-014/015/016 khi thiết kế từng màn.

Desktop/laptop viewport từ 1366 px. Phương án A: sidebar theo nghiệp vụ, header tên trang và tài khoản, vùng nội dung rộng. Theo docs/tokens.json, font và quy tắc accessibility hiện hành; không đưa font/icon từ mạng. Menu chỉ chứa màn đã chuyển và có quyền. Điều hướng, breadcrumb và deep link do Vue Router quản lý.

Dashboard ưu tiên việc cần xử lý theo vai trò, chỉ lấy nguồn dữ liệu và thao tác đã có trên server. Mỗi dòng có loại việc, mã tham chiếu, thời điểm, mức ưu tiên bằng chữ và hành động tới màn đã chuyển. Nguồn chưa có API hoặc chưa có màn đích không đưa vào bản đầu. Tổng số áp cùng bộ lọc quyền với danh sách. KPI là thông tin bổ trợ, không hiển thị số demo. Không có việc hiển thị trạng thái trống.

Mọi trang có loading, empty, error, retry phù hợp. Mất mạng chặn thao tác ghi và thông báo rõ; Admin Shell chưa cung cấp offline queue. Lỗi validation hiển thị tại trường; lỗi nghiệp vụ chặn hiển thị inline; không lộ traceback. Form có dữ liệu chưa lưu phải cảnh báo trước khi rời trang.

## Chuyển phân hệ Dụng cụ & bộ

Instrument: list/filter/detail/create/edit theo permission, phương pháp tương thích, ảnh/IFU, trạng thái, cơ số/bảo dưỡng, GIAI theo cờ và quyền hiện có. Giữ nguyên quy tắc kiểm media, cảnh báo BOM và audit của FEAT-014.

Instrument Set Type: thông tin loại bộ, ảnh, BOM có phiên bản và ngày hiệu lực, tạo phiên bản kèm lý do, so sánh, hạn lưu và phiếu kiểm đếm theo FEAT-015. Phiên bản cũ bất biến; không ghi trực tiếp bảng con để bỏ qua dịch vụ nghiệp vụ.

Set Unit: danh sách/chi tiết/lịch sử, cấp lô 1–100, preview/in/in lại có lý do, CSV, xác minh gắn thẻ theo FEAT-016. Sinh mã và đổi trạng thái tiếp tục ở server; UI không cung cấp thao tác thanh lý chưa được hiện thực.

## Kiểm chứng và phát hành

Backend test: bootstrap/capability, lọc dashboard theo quyền, Desk guard gồm deep link và ngoại lệ station; test quyền RPC và phạm vi khoa, CSRF, session. Frontend test cho route guard, session/2FA state và các hành động ghi rủi ro. Playwright trên site dev ở 1366×768: login/2FA/logout/hết session, deep link refresh, role bị từ chối, lỗi mạng và thao tác chính của từng màn chuyển. Dùng dữ liệu seed, không truy cập production.

Build production phải chạy qua Frappe tại /tracecore, assets có hash và deep link không 404. Chạy kiểm tra hồi quy kiosk T1/T4 và quyền nghiệp vụ. Chỉ bật redirect người nghiệp vụ sau khi màn họ cần có trong SPA; rollout và rollback dùng cờ cấu hình site do backend đọc, mặc định tắt trước cutover. Khi tắt rollout, hành vi Desk hiện tại trở lại; dữ liệu nghiệp vụ không cần migration ngược.

## Phân rã kế hoạch

Lập kế hoạch riêng theo thứ tự: (1) Admin Shell/session/Desk guard/dashboard, (2) Instrument, (3) Set Type/BOM, (4) Set Unit. Mỗi kế hoạch phải rà chính xác RPC, schema và test hiện tại trước khi xác định interface. Không mở rộng chức năng nghiệp vụ hoặc sửa luật FR/BRU trong quá trình thay frontend.
