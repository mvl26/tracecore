# FEAT-008 Nhật ký môi trường khu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ghi nhiệt độ (T), độ ẩm (RH), áp suất chênh (dP) theo khu, nhập tay trên Desk hoặc cảm biến đẩy qua RPC; cảnh báo R02 khi vượt ngưỡng của khu; nhắc khi khu thiếu số liệu ở các mốc giờ cấu hình; báo cáo tháng theo khu.

**Architecture:** DocType `Environment Log` (M9, module `Admin Reports`, cạnh `Zone Station`), chứng từ Nháp → Ghi sổ → Hủy. Ngưỡng và cờ theo dõi là trường mới trên `Zone Station` (khu). Mốc giờ nhắc là trường mới của `TraceCore Settings`. Dịch vụ `tracecore/admin_reports/environment.py`; RPC `tracecore.v1.env.log` cho cảm biến (agent của trạm, `@idempotent`); thông báo qua `core.notification.emit`; Script Report `Environment Monthly Report`.

**Tech Stack:** Frappe v15, `IsolatedTestCase`, Desk form + Script Report.

**Spec:** `docs/implementation-plan.md` FEAT-008; `docs/srs.md` FR-M9-04, FR-M9-04.1, FR-M9-04.2, EI-HW-005, OQ-16; `docs/use-cases.md` UC-33 bước 3, A1; `docs/architecture.md` §5.3.1 M9 (Environment Log), §5.3.3; Amendment **A-55**.

## Global Constraints
- Chuỗi qua `_()`/`__()` có bản dịch `vi.csv`; UI Desk chỉ token `--tc-*`.
- Không làm: Modbus (EI-HW-005, Could), nhiệt độ kho lạnh chất thải (FR-M10-03.2 thuộc FEAT-048, dùng lại DocType này), NC tự tạo khi vượt ngưỡng, màn trạm/PDA (SCR-33 là WEB).

## Quyết định (Amendment A-55; người dùng chốt Q1–Q4 ngày 30/10/2026, chủ đầu tư chưa xác nhận)
| # | Quyết định |
| :- | :- |
| Q1 | Nguồn số liệu: nhập tay trên Desk (`source = Manual`) và RPC `tracecore.v1.env.log` cho cảm biến/agent đẩy qua HTTP (`source = Sensor`). Không làm Modbus. OQ-16 coi như chốt cho v1.0 ở mức này. |
| Q2 | Ngưỡng cấu hình trên từng khu (`Zone Station` có `is_zone = 1`): `env_monitored` và min/max cho T, RH, dP. Ô để trống thì không kiểm phía đó. Không đặt giá trị mặc định. |
| Q3 | Mốc giờ nhắc cấu hình được ở `TraceCore Settings.env_reminder_times` (danh sách `HH:MM`, mặc định `11:00, 17:00`). Tại mốc thứ i, khu theo dõi nào không có lần đo đã ghi sổ trong khung [mốc i-1, mốc i) (mốc đầu tính từ 00:00) thì nhắc. |
| Q4 | Người ghi: TC R02–R06 (R02 hủy/sửa đổi); R01, R10 chỉ đọc. R03–R06 được thêm quyền đọc `Zone Station` để chọn khu trên form. |
| D1 | Mã `MT-.YYYY.-.#####`. Một lần đo cần ít nhất một trong T, RH, dP. RH trong 0–100. `measured_at` không ở tương lai (cho lệch 5 phút). |
| D2 | Vượt ngưỡng: khi Ghi sổ, `out_of_range = 1` và `breaches` ghi chỉ số vượt; phát `ENV_OUT_OF_RANGE` (mặc định R02). |
| D3 | Thiếu số liệu: scheduler 15 phút `environment.remind_missing` phát `ENV_LOG_MISSING` (mặc định R02) mỗi khu × mốc × ngày tối đa một lần; R10 thêm người nhận ở Notification Rule. |
| D4 | RPC cảm biến: role `TC Agent` và `require_agent_for(station)`; khu = `parent_zone` của trạm; khu phải đang theo dõi. Từ chối là `BlockedError` (`ENV_ZONE_NOT_MONITORED`, `ENV_READING_INVALID`). |
| D5 | Báo cáo tháng: mỗi khu × ngày một dòng: số lần đo, min/max T, RH, dP, số lần vượt ngưỡng, số mốc thiếu. Lọc tháng, năm, khu; in/xuất bằng công cụ chuẩn của Report. |

## Tasks
- [x] **T1 DocType + ngưỡng khu + settings** — `Environment Log`, trường mới `Zone Station`, `TraceCore Settings`, ma trận quyền `DT-ENVLOG`. FR-M9-04, Q2, Q4, D1.
- [x] **T2 Dịch vụ đánh giá ngưỡng + cảnh báo** — `environment.validate_reading`, `on_submit` phát `ENV_OUT_OF_RANGE`. FR-M9-04.1, D2.
- [x] **T3 Nhắc thiếu số liệu** — `parse_times`, `remind_missing`, scheduler. FR-M9-04.2, Q3, D3.
- [x] **T4 RPC cảm biến** — `tracecore.v1.env.log`. FR-M9-04, EI-HW-005 (HTTP), Q1, D4.
- [x] **T5 Báo cáo tháng** — Script Report. FR-M9-04, D5.
- [x] **T6 Desk, bản dịch, tài liệu** — form JS, `vi.csv`, A-55 + §5.3.1/§5.3.3, rtm.

## Ghi chú hiện thực
- Ngưỡng (Zone Station) và số đo (Environment Log) là ô **Data** đã chuẩn hóa số (nhận dấu phẩy thập phân, lưu dấu chấm), vì Float của Frappe v15 là cột `not null default 0`: không phân biệt được "để trống" với 0, trái Q2 và D1.
- Khu vừa bật theo dõi giữa ngày sẽ được nhắc ngay cho các mốc đã qua của ngày đó (scheduler 15 phút xét mọi mốc đã qua).

## Acceptance criteria (EARS)
- AC1 Khi R02–R06 ghi sổ một lần đo của khu, hệ thống lưu T/RH/dP, giờ đo, người ghi, nguồn.
- AC2 Nếu một chỉ số vượt ngưỡng của khu, thì hệ thống đánh dấu lần đo vượt ngưỡng và cảnh báo R02.
- AC3 Nếu đến mốc nhắc mà khu theo dõi chưa có lần đo trong khung, thì hệ thống nhắc người phụ trách một lần.
- AC4 Khi cảm biến của trạm gửi số liệu qua `tracecore.v1.env.log`, hệ thống ghi sổ lần đo nguồn Cảm biến; gửi lại cùng khóa idempotency không tạo bản ghi thứ hai.
- AC5 Khi người dùng mở báo cáo tháng, hệ thống hiện số liệu theo khu × ngày của tháng đó.
