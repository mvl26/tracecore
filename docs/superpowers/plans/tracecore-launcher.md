# TraceCore launcher — Home → không gian làm việc

Người dùng duyệt ngày 23/10/2026: bổ sung liên kết từ Home tới Page
`/app/tracecore`, bố cục ba card quản lý / trạm / khoa. Bổ sung điều hướng
cho surface hiện hữu; không phải SCR-44..46, không thêm DocType hay đổi ADR.

## Acceptance criteria

- AC1 (EI-UI-001/002, ADR-002): Home có nút “Mở TraceCore”, sidebar có mục TraceCore; Page dùng Frappe Desk.
- AC2 (FEAT-003): lựa chọn theo role; đích tiếp tục kiểm quyền và thẻ/PIN.
- AC3 (FEAT-002): lấy mã trạm hoạt động từ DB, không hard-code mã TR.
- AC4 (FR-M9-14): có loading, empty, error/thử lại, offline/tự nạp khi online.
- AC5: chỉ bật T2/T4/T6 đã có trong base branch; phần chưa triển khai không dẫn tới màn giả.
- AC6 (design.md): ba card responsive, token, nhãn select, bàn phím và focus.

## Tasks

1. FrappeTestCase kiểm guest, role, active station, trạng thái triển khai (AC2/3/5).
2. Controller read-only và Page UI, không thay đổi xác thực (AC1/2/3).
3. Card, trạng thái, liên kết Home, bản dịch (AC1/4/5/6).
4. Test, lint, build và kiểm tra Home → Page → trạm (mọi AC).

## Tích hợp

Claude đang làm FEAT-019 trong bench và có thay đổi chưa commit. Nhánh này được
soạn trong clone Windows riêng; không đổi nhánh hoặc migrate/build bench đó.
Chạy FrappeTestCase từ nguồn ngoài qua loader trên test_site, không sao chép code
vào checkout của Claude. Khi merge FEAT-019/020, cập nhật danh sách màn đã triển khai.
