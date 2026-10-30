# FEAT-007 Sổ tiệt khuẩn điện tử, báo cáo KSNK, dự báo hết vòng đời Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Người dùng chọn kỳ, máy hoặc khoa để xem và xuất (PDF/Excel) sổ tiệt khuẩn điện tử theo máy, báo cáo KSNK tổng hợp tháng, dự báo bộ dụng cụ hết vòng đời theo tháng kèm giá; bản PDF sinh nền ≤ 30 s, có chỗ ký Trưởng khoa KSNK, người xuất, thời điểm xuất, và dấu TẠM khi kỳ chưa khóa.

**Architecture:** Dịch vụ `tracecore/admin_reports/sterilization_log.py` (M9, chỉ đọc DocType theo tên, không import M1/M2) dựng dữ liệu cho 3 Script Report (`Sterilization Log`, `KSNK Summary Report`, `Instrument Life Forecast`) và 3 mẫu in Jinja; xuất PDF chạy job RQ `long`, lưu File riêng tư, báo người xuất bằng chuông Desk (`Notification Log` chuẩn Frappe) và realtime. RPC `tracecore.v1.report.export` (alias `sterilization_log` theo implementation-plan). Ngày khóa báo cáo là trường mới `TraceCore Settings.report_locked_until` (permlevel 1, chỉ TC R01 ghi). Token in đọc từ `tokens.css` qua `core.print_tokens`.

**Tech Stack:** Frappe v15, `IsolatedTestCase`, Script Report, wkhtmltopdf (`frappe.utils.pdf.get_pdf`), RQ.

**Spec:** `docs/implementation-plan.md` FEAT-007; `docs/srs.md` FR-M9-02, FR-M9-02.1, OTH-LEG-001, NFR-COMP-01, NFR-PERF-03, EI-HW-007; `docs/use-cases.md` UC-32 bước 3; `docs/architecture.md` §5.3, NFR-PERF-03 (RQ long); Amendment **A-57**.

## Quyết định (Amendment A-57; người dùng chốt Q1–Q4 ngày 30/10/2026, chủ đầu tư chưa xác nhận)
| # | Quyết định |
| :- | :- |
| Q1 | Sổ tiệt khuẩn: mỗi mẻ (không tính mẻ Đang chạy) một dòng: ngày, mã mẻ, máy, chương trình, giờ bắt đầu/kết thúc, thông số chu trình (`params`: tên = giá trị đơn vị, đánh dấu ngoài ngưỡng), chỉ thị (Bowie-Dick, hóa học, sinh học: kết quả + lô), số gói và danh sách bộ, người vận hành, người giải phóng + giờ, kết quả. Lọc kỳ (bắt buộc), máy, khoa (mẻ có gói của khoa). Cột đề xuất, BV chỉnh sau UAT. |
| Q2 | Báo cáo KSNK tổng hợp: theo máy (phương pháp, số mẻ, đạt, không đạt, tỷ lệ không đạt), chỉ thị sinh học (số test, dương tính), lô rửa (tổng, đạt, không đạt), gói đã tiệt khuẩn, gói cấp phát theo khoa, lệnh thu hồi, sự cố/NC theo loại. Lọc kỳ, khoa (khoa chỉ áp cho phần cấp phát, mẻ có gói của khoa). |
| Q3 | Khóa kỳ: `TraceCore Settings.report_locked_until` (Date, permlevel 1: TC R01 đọc/ghi; R10, System Manager đọc). Ngày cuối kỳ > ngày khóa (hoặc chưa đặt) → bản in và PDF có dấu TẠM (FR-M9-02.1). |
| Q4 | Dự báo theo bộ (Set Unit không phải bộ mượn, chưa Thanh lý/Trả lại, có cơ số tối đa): còn lại = cơ số − đã dùng; tốc độ = số mẻ Giải phóng có bộ trong 90 ngày gần nhất ÷ 3; tháng hết = tháng hiện tại + ⌈còn lại ÷ tốc độ⌉ (bộ đã Hết vòng đời: tháng hiện tại); tốc độ 0 → không dự báo. Giá = Σ `Instrument.value` × `qty` theo BOM của bộ (`cycle_bom_version`, không có thì phiên bản hiện hành). Trong 12 tháng tới, nhóm theo tháng, tổng tiền mỗi tháng. |
| D1 | Xuất PDF: RPC `tracecore.v1.report.export(kind, filters)` kiểm quyền Report, `frappe.enqueue(queue="long")`, job dựng HTML + `get_pdf`, lưu `File` riêng tư (`is_private=1`), báo `Notification Log` + realtime `tc_report_ready` cho người xuất. Excel dùng nút xuất sẵn của Script Report. |
| D2 | Mỗi bản in có tiêu đề, kỳ/bộ lọc, người xuất, thời điểm xuất (dd/mm/yyyy HH:mm), chỗ ký Trưởng khoa KSNK, dấu TẠM nếu chưa khóa. |
| D3 | Quyền: Script Report cho TC R01, R02, R10, System Manager (dự báo thêm R09). Dịch vụ đọc dữ liệu với `ignore_permissions` sau khi đã kiểm quyền Report. |

## Tasks
- [x] **T1 Khóa kỳ** — trường `report_locked_until` + RPC `lock_period` (R01, Audit). FR-M9-02.1, Q3.
- [x] **T2 Sổ tiệt khuẩn** — `sterilization_log.log_rows` + Script Report. FR-M9-02, Q1.
- [x] **T3 Báo cáo KSNK** — `ksnk_summary` + Script Report. FR-M9-02, Q2.
- [x] **T4 Dự báo hết vòng đời** — `life_forecast` + Script Report. FR-M9-02, Q4.
- [x] **T5 Bản in + PDF nền** — mẫu Jinja, `render_html`, `export`, job, RPC. OTH-LEG-001, NFR-PERF-03, D1, D2.
- [x] **T6 Bản dịch, tài liệu** — `vi.csv`, A-57, rtm.

## Ghi chú hiện thực
- Q3 dự kiến dùng permlevel 1 cho R01, nhưng Frappe chỉ cho lưu Single khi có quyền ghi mức 0 (sẽ mở cả cấu hình SMS, GIAI cho R01). Đổi thành: trường chỉ đọc trên form, R01 đặt bằng nút "Khóa kỳ báo cáo" trên 3 báo cáo (RPC `tracecore.v1.report.lock_period`, Audit Log). Kết quả giữ đúng Q3: chỉ R01 đổi được ngày khóa.
- `core.print_tokens` lặp lại cách đọc `tokens.css` của `instrument.count_sheet` để M9 không import M1; gộp hai nơi là việc dọn sau.
- Đo NFR-PERF-03: PDF sổ tháng 600 mẻ (mỗi mẻ 12 bộ) ≈ 3,7 s, 859 KB.
- Bản dịch chèn giữa `vi.csv` (sau dòng `Cost sheet unpriced`) để không đụng phần FEAT-013 nối cuối file.

## Acceptance criteria (EARS)
- AC1 Khi người dùng chọn kỳ (và máy/khoa), hệ thống liệt kê mọi mẻ của kỳ với thông số, chỉ thị, người vận hành, người giải phóng.
- AC2 Khi người dùng mở báo cáo KSNK của kỳ, hệ thống hiện số mẻ đạt/không đạt theo máy, chỉ thị sinh học dương tính, cấp phát theo khoa, thu hồi, sự cố.
- AC3 Khi người dùng mở dự báo, hệ thống nhóm bộ sắp hết vòng đời theo tháng trong 12 tháng tới kèm giá thay thế.
- AC4 Khi người dùng bấm Xuất PDF, hệ thống sinh PDF nền và báo người dùng khi xong; bản PDF có người xuất, thời điểm xuất, chỗ ký Trưởng khoa KSNK.
- AC5 Nếu ngày cuối kỳ sau ngày khóa báo cáo, thì bản xuất có dấu TẠM.

## Phối hợp nhánh song song
FEAT-013 (tab khác, A-56) sửa `hooks.py`, `errors.py`, `core/notification`, cuối `vi.csv`. FEAT-007 không sửa ba file đầu; bản dịch chèn giữa `vi.csv`.
