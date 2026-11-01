# Software Requirements Specification: TraceCore

> Version: 1.11 · Status: Finalized · Last updated: 2026-10-17
> Requirement syntax: EARS
> Nguồn gốc: Bộ BA v1.10 (MC-TRACECORE-2026-BA-v1.10, 20/09/2026, Medcons — Nhóm BA). Mọi ID gốc được giữ nguyên.

> **Phạm vi file này:** Header, Revision History, §1 Introduction, §2 Overall Description, §3.1 Functional requirements (90 FR gốc-cấp = 73 FR BA v1.10 + FR-M9-08..16 + FR-M10-01..08, cùng ID gốc FR-Mx-NN), §3.2 External interface requirements, §3.3 Non-functional requirements (35 NFR), §3.4 Other requirements, Appendix A Glossary, Appendix B Open questions, Appendix C Quyết định phạm vi.
>
> Quy ước đánh dấu: `[chuẩn hóa]` = nội dung gốc được viết lại cho đo được/kiểm thử được, cần người dùng duyệt; `[NEW v1.11]` = ID mới không có trong BA v1.10; `[đề xuất]` = giá trị số do nhóm SRS đề xuất, chưa được chủ đầu tư xác nhận.

## Revision History

| Version | Date | Author | Changes |
| :------ | :--- | :----- | :------ |
| 1.0 | 18/09/2026 | Medcons — Nhóm BA | Baseline bộ BA (Bộ Số Chuẩn + #01–#04; các tài liệu còn lại lập theo đợt kế tiếp). CHG-001..018. |
| 1.10 | 20/09/2026 | Medcons — Nhóm BA | Áp dụng các quyết định review của chủ đầu tư 20/09/2026 (CHG-019..032, phát hành qua v1.1→v1.10): **CHG-019** Set ID theo GS1 DataMatrix GIAI, bỏ mã nội bộ; **CHG-020** hạn lưu theo loại gói nhập tay, không mặc định cứng; **CHG-021** cơ số tái xử lý nhập tay bởi R01/R02; **CHG-022** hai loại nhãn riêng hấp/plasma, chặn in sai loại (BRU-REP-011); **CHG-023** phụ lục #17 giao diện theo 3 vai trò; **CHG-024** tiếp nhận nhiều bộ nối tiếp, kiểm đếm từng dụng cụ, chỉ thị hóa học + nhắc tra dầu tại đóng gói (FR-M1-09, FR-M2-23, DT-INSTRMAINT, API-M1-06); **CHG-025** mã lô/mã mẻ nạp nhiều bộ gắn toàn bộ dữ liệu máy, cổng kiểm soát từng bước, Vô khuẩn khi đủ 5 cổng (FR-M2-24, FR-M2-25, BRU-FLOW-004, BRU-REP-015, DT-STEPGATE, API-M2-17, ST-SU-REDO); **CHG-026** dữ liệu máy hai nguồn — tự động hoặc nhập tay bắt buộc có xác nhận (FR-M2-10 Should→Must); **CHG-027** nạp/dỡ máy bằng quét QR máy + mã bộ + mã mẻ, mã mẻ tự sinh khi Hoàn thành nạp (BRU-REP-016); **CHG-028** Cycle ID tự sinh khi xác nhận hoàn thành đóng gói, là điều kiện vào mẻ; **CHG-029** ảnh chụp thực tế dụng cụ/bộ thay sơ đồ vẽ; **CHG-030** đặt tên sản phẩm TraceCore, phát hành một file bàn giao; **CHG-031** Technology Stack chi tiết Frappe/ERPNext v15 trong #12; **CHG-032** tiếp nhận chỉ quét mã bộ + thẻ nhân viên giao, xác nhận thành phần từng dòng/tất cả, hệ thống sinh mã cho mọi đối tượng quét (FR-M9-07, BRU-ID-006). Bộ Số Chuẩn: N_FR 68→73, N_BRU 37→45, N_DT 38→40, N_API 38→40, N_STATE 47→48. |
| 1.11 | 2026-10-17 | Pipeline RE (Claude) + chủ đầu tư | Chuẩn hóa EARS giữ ID; thêm M10 chất thải y tế (FR-M10-01..08, UC-34..37, SCR-38..41); duyệt FR-M9-08..16 và 21 NFR mới; FR-M9-06 → Must; chốt Set ID GIAI / Cycle ID GS1 DataMatrix; dịch vụ ngoài out-of-scope. Bộ Số Chuẩn BA v1.10 → v1.11: N_MOD 9→10, N_FR 73→90, N_NFR 14→35, N_UC 33→39, N_SCR 37→43 (UC-38/39, SCR-42/43 phủ FR-M9-10/11/12). |
| 1.11 A-02 | 2026-10-20 | Miyano (dev lead) + Claude Code; D1–D5, D7 tạm — trình CĐT 20/10/2026; D6 còn mở | Ghi chú theo Amendment A-02 của `docs/architecture.md` (FEAT-018, quyết định D1–D14), không thêm/bớt ID FR hay BRU: FR-M1-09.6 (ngưỡng chặn bảo dưỡng, D5), FR-M2-07.7 (hạn dùng, D4), FR-M2-08.5 (cửa sổ in lại 10 phút tính từ lúc tạo Pack, giờ server — ruling Task 8), §3.1.11 điểm rà soát #1 và #5, Appendix B OQ-05 (D6 vẫn mở). Chi tiết xem architecture.md, Revision History A-02. |
| 1.11 A-03 | 2026-10-20 | Miyano (dev lead) + Claude Code; E1–E3 đã duyệt (người dùng xác nhận 21/10/2026); E4–E8 dev lead xác nhận | Ghi chú theo Amendment A-03 của `docs/architecture.md` (FEAT-002, quyết định E1–E8), không thêm/bớt ID FR hay BRU: FR-M9-03 và FR-M9-03.1–03.3 (mã khu `ZONE-.##`, chức năng trạm theo khu, trạm chưa gán khu lưu được nhưng không hoạt động, ngoại vi quét/cân, máy hai cửa, quyền). Chi tiết xem architecture.md, Revision History A-03. |
| 1.11 A-04 | 2026-10-21 | Miyano (dev lead) + Claude Code; Q1–Q3 tạm — chờ chủ đầu tư duyệt; Q4–Q9 dev lead xác nhận; E1–E3 của A-03 đã duyệt (người dùng xác nhận 21/10/2026) | Ghi chú theo Amendment A-04 của `docs/architecture.md` (FEAT-038, quyết định Q1–Q9, ruling P1), không thêm/bớt ID FR hay BRU: FR-M5-01 và FR-M5-01.1–01.3 (khấu hao/mẻ, serial, khu vào/ra, trạng thái, QR thuộc FEAT-005), FR-M5-02 và FR-M5-02.1–02.4 (định mức đủ/thiếu/mặc định, `param_schema`, dải an toàn, quyền). Chi tiết xem architecture.md, Revision History A-04. |
| 1.11 A-05 | 2026-10-21 | Miyano (dev lead) + Claude Code; R1–R3 tạm — chờ chủ đầu tư duyệt; R4–R8 dev lead xác nhận | Ghi chú theo Amendment A-05 của `docs/architecture.md` (FEAT-005, quyết định R1–R8), không thêm/bớt ID FR hay BRU: FR-M9-07 và FR-M9-07.1–07.4 (đường in nhãn từ Desk, nhãn 50 × 30 mm, cấp mã cuộn `CN-`, vô hiệu mã, thẻ có sẵn của bệnh viện). Chi tiết xem architecture.md, Revision History A-05. |
| 1.11 A-06 | 2026-10-21 | Miyano (dev lead) + Claude Code; I1–I8 tạm — chờ chủ đầu tư duyệt; I9–I17 dev lead xác nhận | Ghi chú theo Amendment A-06 của `docs/architecture.md` (FEAT-014, quyết định I1–I17), không thêm/bớt ID FR hay BRU: FR-M1-01.3 (phiên bản dụng cụ không có DocType riêng: `version_no` + Audit Log, cảnh báo BOM không chặn), FR-M1-02 (mã GIAI dụng cụ `<prefix>I-########`, cờ `TraceCore Settings`; FR-M1-02.2/.4 chuyển FEAT-020), FR-M1-09 (ngưỡng theo `Instrument Group`, khởi tạo bộ đếm, hook `tracecore_after_release`), OQ-07 và OQ-22 ghi trạng thái. Chi tiết xem architecture.md, Revision History A-06. |
| 1.11 A-07 | 2026-10-22 | Miyano (dev lead) + Claude Code; V1–V6, V11 tạm — chờ chủ đầu tư duyệt; V7–V10, V12–V14 dev lead xác nhận | Ghi chú theo Amendment A-07 của `docs/architecture.md` (FEAT-041, quyết định V1–V14), không thêm/bớt ID FR hay BRU: FR-M6-01 (Custom Field NCC/số chứng từ/lô/hạn trên Stock Entry, giá bình quân theo Item), FR-M6-01.2 (quy tắc nhập Excel), FR-M6-02 (tồn tối thiểu theo kho = `Item Reorder`, quy cách, quyền), FR-M6-02.1 (nhóm giữ thêm `Lubricant`, chỉ thị hóa học đủ lớp 1–6 bằng cách thêm lớp 3). Chi tiết xem architecture.md, Revision History A-07. |
| 1.11 A-08 | 2026-10-21 | Miyano (dev lead) + Codex; A1–A8 chờ review FEAT-003 | Ghi chú theo Amendment A-08 của `docs/architecture.md` (FEAT-003), không thêm/bớt ID FR hay BRU: precedence ma trận SEC #13; 2FA WEB; thẻ/PIN trạm; token phiên chỉ lưu hash; phiên 8 giờ/idle 10 phút/một thẻ–một phiên; quyền tạm tối đa 24 giờ; khóa PIN; chính sách mật khẩu. Chi tiết xem architecture.md và `docs/superpowers/plans/FEAT-003-rbac-station-auth.md`. |
| 1.11 A-09 | 2026-10-22 | Miyano (dev lead) + Claude Code; S1–S8 tạm — chờ chủ đầu tư duyệt; S9–S15 dev lead xác nhận | Ghi chú theo Amendment A-09 của `docs/architecture.md` (FEAT-015, quyết định S1–S15), không thêm/bớt ID FR hay BRU: FR-M1-03.3/.4/.5 (luật tương thích theo họ phương pháp, hạn lưu ghi đè ngắn hơn, loại gói phải có hạn lưu), FR-M1-04, FR-M1-04.1/.2/.4 (phiên bản BOM bất biến không thêm DocType, ghim phiên bản theo chu trình qua `step_gate.start_cycle`, hiệu lực từ ngày hiệu lực, chặn ngày quá khứ), FR-M2-07.8 (sửa hạn lưu loại gói qua RPC có lý do cho R02/R10). Chi tiết xem architecture.md, Revision History A-09. |
| 1.11 A-10 | 2026-10-22 | Miyano (dev lead) + Claude Code; D1 chủ đầu tư/người dùng chốt 22/10/2026; D2–D7 dev lead xác nhận | Ghi chú theo Amendment A-10 của `docs/architecture.md` (FEAT-025, quyết định D1–D7), không thêm/bớt ID FR hay BRU: FR-M2-13 (nhập kho theo vị trí `KE-`, FEFO), FR-M2-14 (quá hạn = hạn dùng < hôm nay, chạy 00:00; rách/ướt/mở cần lý do; Set Unit → `Awaiting Receipt`); mâu thuẫn số 4 ở §3.1.11 đã chốt (D1). Chi tiết xem architecture.md, Revision History A-10. |
| 1.11 A-12 | 2026-10-22 | Miyano (dev lead) + Claude Code; Q1, Q5, Q11, Q13, Q23 tạm — chờ chủ đầu tư duyệt; Q17, Q22 đã chốt (người dùng xác nhận 22/10/2026); các Q còn lại dev lead xác nhận | Ghi chú theo Amendment A-12 của `docs/architecture.md` (FEAT-021, quyết định Q1–Q23), không thêm/bớt ID FR hay BRU: FR-M2-03.1–.6, FR-M2-04.1–.7, FR-M2-24 (chỉ nguồn Nhập tay có xác nhận), FR-M2-25 (T2); mã lô chỉ sinh khi Hoàn thành nạp; `wash.complete` nhận một phần; mã HTTP 423 cho máy không sẵn sàng; NC tự tạo, trừ hóa chất, chi phí lô đạt từng phần. Chi tiết xem architecture.md và `docs/superpowers/plans/FEAT-021-t2-wash-batch.md`. |
| 1.11 A-13 | 2026-10-22 | Miyano (dev lead) + Claude Code; G1–G10, G14 tạm — chờ chủ đầu tư duyệt (người dùng đã duyệt kế hoạch 22/10/2026, chủ đầu tư chưa); G11–G13, G15–G17 dev lead xác nhận | Ghi chú theo Amendment A-13 của `docs/architecture.md` (FEAT-016, quyết định G1–G17), không thêm/bớt ID FR hay BRU và không đổi câu EARS: FR-M1-05 (tạo chỉ qua cấp Set ID, tiền tố GS1 là cấu hình site, mẫu thẻ = chọn loại bản in, điều kiện cấp, nguồn bộ), FR-M1-05.1 (1–100 bộ, nguyên tử, serial liên tiếp, GIAI không check digit, hết dải, chặn tiền tố demo), FR-M1-05.3 (in lại có lý do, số lần in suy ra từ Print Job), FR-M1-05.4 (một Print Job mỗi nhãn, Set ID giữ khi máy in lỗi), FR-M1-06 và FR-M1-06.2 (lịch sử vòng đời từ Audit Log kèm sự kiện, thanh lý, hiển thị nguồn số chu trình). Chi tiết xem architecture.md, Revision History A-13. |
| 1.11 A-59 | 2026-10-30 | Miyano (dev lead, người dùng yêu cầu 30/10/2026) + Claude Code; chủ đầu tư chưa xác nhận | Ghi chú theo Amendment A-59 của `docs/architecture.md`, không thêm/bớt ID FR hay BRU: FR-M4-02, loại chứng chỉ tự điền và gợi ý từ các loại đã dùng; bốn loại nêu trong FR là ví dụ, không còn là danh sách cố định. |
| 1.11 A-77 | 2026-10-31 | Miyano (dev lead, người dùng duyệt ngày 31/10/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-77 của `docs/architecture.md`: thêm FR-M2-04.8 đến FR-M2-04.10 (chỉ thị rửa bắt buộc theo chương trình, trạng thái Chờ đọc chỉ thị); ghi chú FR-M2-04. |
| 1.11 A-86 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-86 của `docs/architecture.md`: máy tiệt khuẩn không nhận mẻ mới khi mẻ trước chưa dỡ (sửa A-22), ghi người dỡ, thời lượng so với chuẩn ở màn dỡ. Nhãn lô vẫn in lúc nạp. Ticket #1809. |
| 1.11 A-85 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-85 của `docs/architecture.md`: tab Kiểm tra hằng ngày chỉ hiện máy theo chức năng của trạm và cấu hình test; không đổi FR. Ticket #1826. |
| 1.11 A-84 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-84 của `docs/architecture.md`: test hằng ngày có bước bắt đầu, kết thúc, chỉ ghi kết quả sau khi kết thúc; máy hiện trạng thái theo mẻ đang chạy. Ticket #1823. |
| 1.11 A-83 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-83 của `docs/architecture.md`: phân loại chương trình test, chương trình mặc định của máy, danh sách loại gói rỗng không nhận gói. Ticket #1821, #1839, #1840. |
| 1.11 A-82 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-82 của `docs/architecture.md`: vị trí nút nguy hiểm T3/T4, lý do từ chối chỉ thị, Audit Log hủy Cycle ID; không đổi FR. Ticket #1843, #1834. |
| 1.11 A-81 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-81 của `docs/architecture.md`: người đóng gói và người lắp bộ ghi theo nhân viên của phiên trạm (thêm FR-M2-07.13). Ticket #1841. |
| 1.11 A-80 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-80 của `docs/architecture.md`: màn T3 giữ bộ đang đếm khi quét sai, dòng tổng theo kết quả; không đổi FR. Ticket #1842. |
| 1.11 A-79 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-79 của `docs/architecture.md`: thêm FR-M2-05.5, FR-M2-05.6; bỏ thao tác xác nhận tất cả ở T3. Ticket #1820. |
| 1.11 A-78 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-78 của `docs/architecture.md`: thêm FR-M6-03.3, FR-M6-03.4 và FR-M6-04.5 (tiêu hao theo một Company, xử lý lại tiêu hao lỗi). Ticket #1816. |
| 1.11 A-70 | 2026-10-31 | Miyano (dev lead, người dùng duyệt ngày 31/10/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-70 của `docs/architecture.md`: test hằng ngày cấu hình theo từng viện (3 chế độ trong `TraceCore Settings`), sửa FR-M5-05, FR-M5-05.1, .2, .3, FR-M5-06, FR-M2-09.3, ghi chú FR-M2-11. Không thêm/bớt ID FR hay BRU. |
| 1.11-draft | 2026-10-17 | Nhóm SRS (Claude Code, chế độ IMPORT) | Chuẩn hóa sang SRS pipeline (ISO/IEC/IEEE 29148), yêu cầu chức năng viết theo EARS, giữ nguyên toàn bộ ID gốc. Bổ sung mục giao diện ngoài có ID (EI-*), NFR đề xuất lấp khoảng trống catalog (chờ duyệt), Appendix B gom vấn đề mở. |
| 1.11 A-64 | 2026-10-30 | Miyano (dev lead, người dùng duyệt ngày 30/10/2026; chủ đầu tư chưa) + Claude Code | Sửa nội dung FR-M2-00.4 (đủ thứ tự chức năng thay cho 8 trạm), ghi chú FR-M9-03, FR-M9-03.2, không thêm/bớt ID FR hay BRU. Chi tiết xem architecture.md, Revision History A-64. |
| 1.11 A-71 | 2026-10-31 | Miyano (dev lead, người dùng duyệt ngày 31/10/2026; chủ đầu tư chưa) + Claude Code | Khung mã lỗi: thêm FR-M9-17..21, FR-M5-07; sửa FR-M4-03.1 (ngoại lệ cho phép tạm NS-001). Xem Amendment A-71 của `docs/architecture.md`. |
| 1.11 A-76 | 2026-10-31 | Miyano (dev lead, người dùng duyệt ngày 31/10/2026; chủ đầu tư chưa) + Claude Code | Theo Amendment A-76 của `docs/architecture.md`: mã doanh nghiệp GS1 khai trong `TraceCore Settings`, tự cấp GTIN-14 cho loại bộ, cấp bù, mở khóa có lý do. Ghi chú OQ-05 (chốt công thức; giá trị prefix thật còn mở). Không thêm/bớt ID FR hay BRU. |
| 1.11 A-87 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Ghi chú theo Amendment A-87 của `docs/architecture.md` (#1818, #1819): FR-M2-04.1 và FR-M2-11 khi chọn tay dùng danh sách lô/mẻ chờ dỡ, không dùng danh sách bộ; chọn tay một dòng gửi cả mã lô/mẻ và mã máy, ghi Audit Log `Manual Entry`. |
| 1.11 A-88 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Ghi chú theo Amendment A-88 của `docs/architecture.md` (#1844, #1836, D7): đổi chương trình tại T5 giữ gói và kiểm lại, gói không hợp đánh dấu đỏ; giao diện không còn mã nội bộ FEAT-/BRU-; gói hiển thị theo `Tên bộ – Khoa (CY-…)`. |
| 1.11 A-89 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Amendment A-89 của `docs/architecture.md` (#1815, D4): sửa FR-M2-10.3 và Q8: tham số ngoài dải chặn kết luận Đạt, không còn cho R02 xác nhận để giải phóng; form dữ liệu chu trình điền sẵn theo chương trình, lưu giá trị mặc định và trường đã sửa; `data_source` thêm `Manual Default`. |
| 1.11 A-90 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Amendment A-90 của `docs/architecture.md`: đổi trạm khác khu phải quét lại thẻ; cùng khu giữ phiên nếu đủ năng lực (FR-M4-03.1, FR-M9-08.1). Không đổi mã FR. |
| 1.11 A-91 | 2026-11-01 | Miyano (dev lead, người dùng yêu cầu làm theo ticket ngày 01/11/2026; chủ đầu tư chưa) + Claude Code | Amendment A-91 của `docs/architecture.md`: khung trạm một thanh điều hướng, danh sách trạm theo thẻ, đổi trạm không tải lại trang, banner khẩn có hành động (FR-M9-10, FR-M9-14). Không đổi mã FR. |

---

## 1. Introduction

### 1.1 Purpose

Tài liệu này đặc tả đầy đủ yêu cầu chức năng và phi chức năng của **TraceCore — Phần mềm Quản lý Vận hành Khoa Kiểm soát Nhiễm khuẩn (CSSD-KSNK)**, mã dự án `MC-TRACECORE-2026`, để đội phát triển (DEV/AI) xây dựng trên nền Frappe/ERPNext v15 và để QA/UAT kiểm chứng.

Đối tượng đọc:

| Đối tượng | Dùng tài liệu để |
| --- | --- |
| Đội DEV/AI (Medcons / đối tác) | Thiết kế kiến trúc, DocType, workflow, API, giao diện; cơ sở cho `software-architecture`, `ux-foundations`, `implementation-planning`. |
| QA / UAT | Lập test case và nghiệm thu theo FR/NFR; đối chiếu RTM. |
| Chủ đầu tư — Trưởng khoa KSNK (R01), Giám sát CSSD (R02), Phòng CNTT (R10) | Duyệt phạm vi, quy tắc, cơ số, ngưỡng NFR và các mục `[chuẩn hóa]`, `[đề xuất]`. |
| Medcons PM/BA | Kiểm soát thay đổi; mọi thay đổi ghi vào #00 CHG và Revision History. |

Tài liệu này **kế thừa và thay thế về cấu trúc** cho #05 SRS v1.10; nội dung nghiệp vụ không thay đổi so với BA v1.10 trừ các điểm được đánh dấu rõ. Phiên bản 1.11 (Finalized, 2026-10-17) gồm **10 phân hệ (M1–M10), 90 FR gốc-cấp, 35 NFR, 39 UC, 43 SCR**.

### 1.2 Product vision & scope

**Vấn đề.** Khoa KSNK (đơn vị tiệt khuẩn trung tâm — CSSD) của bệnh viện vận hành theo mô hình **một chiều, 3 khu liên thông** (khu bẩn → khu sạch → khu vô khuẩn) với máy rửa khử khuẩn và máy tiệt khuẩn hai cửa làm ranh giới vật lý. Việc ghi nhận hiện dựa trên sổ giấy và Excel (sổ tiệt khuẩn theo mẻ, sổ cấp phát theo khoa, nhãn gói viết tay), dẫn đến: không truy xuất được từ bệnh nhân tới mẻ tiệt khuẩn; không kiểm soát được số lần tái xử lý của dụng cụ; không biết chi phí thực của một bộ dụng cụ; không đối chiếu được đồ vải thu – trả theo khoa; máy quá hạn kiểm định vẫn chạy; chỉ thị hết hạn vẫn được dùng (chi tiết AS-IS tại #03 §1).

**Tầm nhìn.** TraceCore là phần mềm kết hợp **truy xuất dụng cụ (instrument tracking)** + **quản lý đồ vải** + **ERP nội bộ khoa** (nhân sự, thiết bị, kho, chi phí, cơ số), trong đó:

- Mỗi bộ dụng cụ mang **Set ID vĩnh viễn** (GS1 DataMatrix GIAI) và mỗi chu trình đóng gói sinh một **Cycle ID** dùng một lần (mã vạch hai tầng).
- Chuỗi tái xử lý **8 trạm (cấu hình mặc định, A-64) T1–T8** được ghi nhận đầy đủ với **cổng kiểm soát 5 bước**: bước trước phải Đạt mới ghi nhận bước sau; bộ chỉ Vô khuẩn và vào kho khi đủ 5 cổng.
- Mỗi mẻ tiệt khuẩn / lô rửa mang **mã mẻ / mã lô** tự sinh khi Hoàn thành nạp, là nơi gắn toàn bộ dữ liệu máy (tự động qua API với máy kết nối được, hoặc nhập tay bắt buộc có xác nhận người vận hành).
- **Chặn sinh Cycle ID khi bộ dụng cụ vượt cơ số**; ghi đè phải có phê duyệt.
- Đồ vải quản lý theo **khoa – loại – số lượng – cân nặng**, không theo từng chiếc.
- **Chất thải y tế rắn** (M10, từ v1.11) quản lý toàn bệnh viện theo **khoa – loại (mã màu TT 20/2021/TT-BYT) – số túi/thùng – kg**, khoa KSNK là đầu mối giám sát: thu gom → lưu giữ tạm → bàn giao đơn vị xử lý có giấy phép kèm chứng từ chất thải nguy hại.
- **Không tích hợp HIS/EMR** ở phiên bản này; mã bệnh nhân nhập tay tại trạm sử dụng và được mã hóa khi lưu.

**Nền tảng.** Frappe Framework v15 / ERPNext v15 (DocType + Workflow + PWA cho PDA), triển khai on-premise tại bệnh viện.

#### 1.2.1 Trong phạm vi (In-scope) — v1.0 (từ #01 §4.1)

| Phân hệ | Nội dung chính trong phạm vi |
| --- | --- |
| M1 Danh mục dụng cụ | Dụng cụ đơn lẻ, loại bộ (BOM có phiên bản), bộ vật lý Set ID, thẻ DataMatrix, dụng cụ mượn, vật tư tái sử dụng. |
| M2 Chuỗi tái xử lý | 8 trạm (cấu hình mặc định, A-64) quét, Cycle ID, lô rửa, mẻ tiệt khuẩn (Load ID), chỉ thị, giải phóng/cách ly, kho vô khuẩn FEFO, cấp phát ký điện tử, quét sử dụng, truy xuất, thu hồi, sự cố – CAPA. |
| M3 Đồ vải | Thu gom – lô giặt – cấp phát theo khoa, loại, số chiếc, cân nặng; đối chiếu thu – trả; định mức; bộ săng mổ tiệt khuẩn đi theo M2. |
| M4 Nhân sự | Hồ sơ, CCHN, chứng chỉ, khám sức khỏe, tiêm chủng, ma trận năng lực gắn quyền trạm, phân ca. |
| M5 Thiết bị | Hồ sơ thiết bị theo khu, chương trình xử lý có định mức, bảo trì – kiểm định – hiệu chuẩn, sự cố, test hằng ngày, khóa máy. |
| M6 Kho vật tư | Danh mục vật tư tái xử lý, nhập – xuất – tồn theo lô/hạn, FEFO, tiêu hao tự động theo mẻ, kiểm kê, cảnh báo. |
| M7 Chi phí | Nhập mọi chi phí đầu vào; bảng định giá có phiên bản; phân bổ theo mẻ; giá thành theo bộ, Cycle ID, khoa, phương pháp. |
| M8 Cơ số | Cơ số tái xử lý tối đa, cơ số tồn khoa, cảnh báo sớm, chặn sinh Cycle ID, ghi đè có phê duyệt. |
| M9 Báo cáo & quản trị | Dashboard, sổ tiệt khuẩn điện tử, báo cáo BYT, khu vực một chiều, trạm, môi trường, người dùng, audit trail, offline trạm; [v1.11] đăng xuất/phiên, đổi/đặt lại mật khẩu, thông báo, import/export, tìm kiếm, trạng thái màn hình, trợ giúp, xóa mềm (FR-M9-08..16). |
| M10 Quản lý chất thải y tế [v1.11] | Chất thải **rắn** toàn bệnh viện, khoa KSNK giám sát: danh mục loại & mã màu theo TT 20/2021/TT-BYT, thu gom theo khoa – loại – số – kg, lưu giữ tạm & thời gian lưu tối đa, bàn giao đơn vị xử lý có giấy phép + chứng từ chất thải nguy hại (NĐ 08/2022/NĐ-CP), sự cố, báo cáo, định mức. |

#### 1.2.2 Ngoài phạm vi (Out-of-scope) — từ #01 §4.2

- Tích hợp HIS/EMR/LIS (lịch mổ, bệnh nhân, thanh toán) — nhập tay mã bệnh nhân; để mở API `cssd.v1` cho giai đoạn sau.
- Kết nối trực tiếp PLC máy tiệt khuẩn — giai đoạn 2; v1.0 nhập tay/đính kèm biểu đồ mẻ. *(Lưu ý: #12 §4 và FR-M2-24 cho phép nhận CSV export/API hãng qua station agent với máy "kết nối được" ngay trong v1.0 — xem Appendix B, OQ-03.)*
- Mã DataMatrix trên từng dụng cụ đơn lẻ — trường dữ liệu sẵn sàng (FR-M1-02, Should), quét từng dụng cụ triển khai giai đoạn 2.
- Kế toán tổng hợp bệnh viện, mua sắm đấu thầu — chỉ xuất đề nghị mua và số liệu giá thành (xuất Excel/CSV).
- Quản lý đồ vải theo từng chiếc (RFID/mã chiếc).
- **Dịch vụ tiệt khuẩn cho khách hàng ngoài bệnh viện** (khách hàng ngoài, bảng giá dịch vụ, hóa đơn) — [v1.11, SC-02 phương án (a)] hệ thống chỉ xuất giá thành tái xử lý (FR-M7-06) làm căn cứ định giá; không quản lý khách hàng ngoài.
- **Chất thải y tế lỏng và khí** (nước thải, khí thải) — [v1.11, SC-01] M10 chỉ quản lý chất thải rắn; lỏng/khí theo hệ thống xử lý nước thải/khí thải của bệnh viện.
- Các module ERPNext không dùng: Selling, CRM, Projects, Support, Webshop, Payments, Education, Lending, Healthcare (#12 §5.2).

#### 1.2.3 Ranh giới MVP / thứ tự phát triển (từ cover.md, #01 §6)

| Sprint | Phạm vi | Ghi chú |
| --- | --- | --- |
| 1 | M1 danh mục (ảnh thực tế, BOM, Set ID GS1, ngưỡng bảo dưỡng); M9 khu/trạm/người dùng/audit; đăng nhập thẻ | Nền tảng |
| 2 | M2 chuỗi 8 trạm (cấu hình mặc định, A-64) với cổng kiểm soát, mã lô/mã mẻ tự sinh, nhập tay có xác nhận, Cycle ID, 2 loại nhãn; M8 cơ số/ghi đè | Lõi truy xuất |
| 3 | M3 đồ vải; M4 nhân sự – năng lực | |
| 4 | M5 thiết bị – chương trình – test ngày – khóa máy; M6 kho vật tư – tiêu hao theo mẻ | |
| 5 | M7 chi phí – giá thành; báo cáo; sổ tiệt khuẩn điện tử; offline trạm (Must từ v1.11) | |
| 5 (đề xuất) | M10 chất thải y tế (thu gom – lưu giữ – bàn giao – báo cáo); FR-M9-08..16 | [v1.11, đề xuất] vị trí sprint do Medcons PM chốt khi lập kế hoạch |

### 1.3 Goals & success metrics

#### 1.3.1 Mục tiêu dự án SMART (O1–O7, từ #01 §2)

| # | Mục tiêu | Chỉ số đo | Thời điểm |
| --- | --- | --- | --- |
| O1 | Truy xuất 100% bộ dụng cụ tái xử lý tới bệnh nhân và mẻ tiệt khuẩn | Tỷ lệ gói có đủ chuỗi 8 trạm (cấu hình mặc định, A-64) ≥ 99%; thời gian tra cứu thu hồi < 5 phút | Go-live + 3 tháng |
| O2 | Loại bỏ sổ giấy tiệt khuẩn và sổ cấp phát | Sổ tiệt khuẩn điện tử in được theo mẫu; 0 sổ giấy song song | Go-live + 1 tháng |
| O3 | Kiểm soát vòng đời dụng cụ theo cơ số IFU | 0 bộ dụng cụ vượt cơ số được cấp phát mà không có phê duyệt ghi đè | Go-live |
| O4 | Tính được giá thành tái xử lý từng bộ dụng cụ | 100% mẻ có bảng giá thành; sai lệch so với kế toán ≤ 5% | Go-live + 2 tháng |
| O5 | Giảm tỷ lệ mẻ lỗi và thiếu dụng cụ | Mẻ lỗi ≤ 1%; thiếu dụng cụ khi lắp ráp giảm 50% so với AS-IS | Go-live + 6 tháng |
| O6 | Quản lý đồ vải minh bạch theo khoa | Chênh lệch thu – trả theo khoa ≤ 5%/tháng; báo cáo kg/khoa hằng ngày | Go-live + 1 tháng |
| O7 | Đảm bảo nhân sự đủ năng lực vận hành trạm | 0 phiên trạm được mở bởi người thiếu chứng chỉ/năng lực | Go-live |

#### 1.3.2 Mục tiêu nghiệp vụ (BO-1..5, từ #02 §2)

| # | Mục tiêu | Kết quả mong đợi |
| --- | --- | --- |
| BO-1 | An toàn người bệnh | Mọi bộ dụng cụ dùng cho bệnh nhân đều truy xuất được mẻ tiệt khuẩn đạt; thu hồi đầy đủ khi có sự cố. |
| BO-2 | Tuân thủ kiểm tra KSNK | Sổ tiệt khuẩn điện tử, hồ sơ chỉ thị, hồ sơ nhân sự và thiết bị sẵn sàng cho đoàn kiểm tra. |
| BO-3 | Hiệu quả vận hành | Giảm thời gian tìm kiếm bộ, giảm thiếu dụng cụ, tăng số mẻ/ngày nhờ dữ liệu theo trạm. |
| BO-4 | Kiểm soát chi phí | Biết giá thành từng bộ; tối ưu chương trình, bao gói, chỉ thị; căn cứ dịch vụ tiệt khuẩn cho bên ngoài. |
| BO-5 | Quản lý tài sản dụng cụ | Vòng đời và cơ số theo IFU; dự báo thay thế; loại bỏ dụng cụ quá hạn sử dụng. |

#### 1.3.3 KPI đo lường quy trình TO-BE (10 KPI, từ #03 §4)

| KPI | Công thức | Mục tiêu | Nguồn dữ liệu | Tần suất |
| --- | --- | --- | --- | --- |
| Tỷ lệ gói có chuỗi truy xuất đầy đủ | Gói có đủ 8 trạm (cấu hình mặc định, A-64) ÷ tổng gói đã dùng | ≥ 99% | DT-PACK, DT-USAGE | Tháng |
| Tỷ lệ mẻ không đạt | Mẻ Không đạt ÷ tổng mẻ | ≤ 1% | DT-LOAD | Tháng |
| Tỷ lệ bộ thiếu dụng cụ khi lắp ráp | Phiếu lắp ráp có thiếu ÷ tổng phiếu | ≤ 3% | DT-ASSEMBLY | Tuần |
| Thời gian chu trình trung bình | T8 (trả) → T7 (cấp phát tiếp theo) | ≤ 8 giờ (thường), ≤ 4 giờ (ưu tiên) | DT-PACK | Tuần |
| Tỷ lệ trả không sử dụng | Cycle ID hủy lý do Trả không dùng ÷ tổng cấp | ≤ 5% | DT-PACK | Tháng |
| Thời gian hoàn tất thu hồi | Từ mẻ Không đạt tới lệnh Đóng | ≤ 2 giờ | DT-RECALL | Sự kiện |
| Giá thành/bộ theo loại | Bảng giá thành | Giảm 10% sau 6 tháng | DT-COSTSHEET | Tháng |
| Chênh lệch đồ vải thu – trả | (Thu − trả − hủy) ÷ thu theo khoa | ≤ 5% | DT-LINENCOL, DT-LINENISS | Tháng |
| Tuân thủ test ngày | Ngày có test đạt ÷ ngày máy chạy | 100% | DT-DAILYTEST | Tháng |
| Bộ vượt cơ số được ghi đè | Số ghi đè ÷ số bộ đạt cơ số | ≤ 10% | DT-OVERRIDE | Tháng |

#### 1.3.4 Tiêu chí nghiệm thu dự án (từ #01 §9)

- 100% Use Case (33) có test case đạt tại UAT với thiết bị thật ở 3 khu.
- Sổ tiệt khuẩn điện tử in được theo mẫu, được Trưởng khoa KSNK ký xác nhận thay sổ giấy.
- Thử nghiệm thu hồi giả lập: liệt kê đủ gói của một mẻ trong < 5 phút.
- Thử nghiệm vượt cơ số: hệ thống chặn sinh Cycle ID và chỉ mở khi có phê duyệt R01.
- Bảng giá thành mẻ và giá thành bộ dụng cụ khớp số liệu kế toán ± 5%.

Tiêu chí nghiệm thu theo từng BR (BR-M1..BR-M9) xem #02 §7; được kế thừa làm acceptance criteria cấp phân hệ trong Part B.

### 1.4 Definitions, acronyms & abbreviations

Các thuật ngữ cốt lõi dùng xuyên suốt tài liệu (Glossary đầy đủ tại Appendix A):

| Thuật ngữ | Định nghĩa ngắn |
| --- | --- |
| **Set ID** | Mã định danh **vĩnh viễn** của một bộ dụng cụ vật lý; GS1 DataMatrix GIAI (AI 8004 — duy nhất, chốt 2026-10-17) với tiền tố GS1 của bệnh viện; không tái cấp, không sửa sau khi in thẻ. |
| **Cycle ID (mã vạch một lần)** | Mã sinh tự động khi KTV xác nhận hoàn thành đóng gói, gắn với bộ cho đúng một chu trình; hết hiệu lực khi dùng, quá hạn, mẻ không đạt, gói rách hoặc tiếp nhận về khu bẩn. Định dạng `CY-YYMMDD-NNNN`; nhãn GS1 DataMatrix (01)(11)(17)(21). |
| **Mã lô (lô rửa) / Mã mẻ (Load ID)** | Mã tự sinh khi Hoàn thành nạp máy rửa / máy tiệt khuẩn, chứa toàn bộ bộ/gói trong lô/mẻ; nơi gắn mọi dữ liệu máy. Load ID `ME-YYMMDD-NN`; lô rửa tiền tố `LR-`. |
| **Cổng kiểm soát (step gate)** | Kết quả Đạt/Không đạt của từng bước T1–T5 cho từng bộ trong chu trình; trạm kế tiếp từ chối quét nếu bước trước chưa Đạt; đủ 5 cổng Đạt → Vô khuẩn. |
| **Khu bẩn / khu sạch / khu vô khuẩn** | Ba khu vật lý một chiều: Decontamination (T1, T2) / Preparation & Packing (T3, T4, T5) / Sterile Storage & Dispatch (T5b, T6, T7). Khoa sử dụng là T8. |
| **T1–T8** (cấu hình mặc định, A-64: số trạm và chức năng do cấu hình) | T1 Tiếp nhận · T2 Rửa – khử khuẩn · T3 Kiểm tra – lắp ráp · T4 Đóng gói · T5 Nạp mẻ tiệt khuẩn (T5b Dỡ mẻ – giải phóng) · T6 Kho vô khuẩn · T7 Cấp phát · T8 Sử dụng. |
| **R01–R10** | 10 vai trò người dùng (xem §2.3). |
| **GS1 GIAI** | Global Individual Asset Identifier — định danh tài sản cá thể theo GS1, AI 8004; là AI duy nhất dùng cho Set ID (không dùng SGTIN (01)+(21)). |
| **Chất thải y tế (M10)** | Chất thải rắn phát sinh trong khuôn viên bệnh viện, phân loại theo TT 20/2021/TT-BYT: lây nhiễm (vàng), nguy hại không lây nhiễm (đen), thông thường (xanh), tái chế (trắng); mỗi túi/thùng mang mã QR hệ thống sinh (tiền tố `CT-`). |
| **BOM** | Bill of Materials — cấu trúc thành phần của một loại bộ dụng cụ (dụng cụ × số lượng), có phiên bản. |
| **FEFO** | First Expired, First Out — xuất trước gói/lô có hạn gần nhất. |
| **BI / CI** | Biological Indicator (chỉ thị sinh học, ISO 11138) / Chemical Indicator (chỉ thị hóa học, ISO 11140-1 loại 1, 2, 4, 5, 6). |
| **Bowie-Dick** | Test hằng ngày (CI loại 2) kiểm tra khả năng thấm hơi/loại khí của máy hấp. |
| **NC / CAPA** | Non-Conformance / Corrective and Preventive Action — không phù hợp / hành động khắc phục – phòng ngừa. |
| **Cơ số tái xử lý** | Số chu trình tối đa một dụng cụ/bộ/vật tư tái sử dụng được tái xử lý theo IFU; nhập tay bởi R01/R02; null = Chưa xác định. |
| **Cơ số tồn khoa** | Số bộ tối thiểu/tối đa một khoa được giữ (min/max/% vượt). |
| **IFU** | Instructions For Use — hướng dẫn của nhà sản xuất. |
| **CSSD / KSNK** | Central Sterile Services Department / Kiểm soát Nhiễm khuẩn. |
| **PDA** | Thiết bị cầm tay Android có máy quét tích hợp, chạy PWA. |
| **Station agent** | Dịch vụ Python nhỏ trên PC trạm: cầu nối cân RS-232/USB, máy in ZPL/TSPL, đọc dữ liệu máy kết nối được. |

### 1.5 References

#### 1.5.1 Văn bản pháp lý và tiêu chuẩn

| Tài liệu | Áp dụng cho |
| --- | --- |
| Thông tư 16/2018/TT-BYT — Quy định về kiểm soát nhiễm khuẩn trong các cơ sở khám bệnh, chữa bệnh | Hồ sơ nhân sự, đồ vải nhiễm, giám sát tuân thủ, lưu hồ sơ. |
| Quyết định 3671/QĐ-BYT — Hướng dẫn khử khuẩn, tiệt khuẩn dụng cụ trong các cơ sở khám bệnh, chữa bệnh | Chỉ thị hóa học/sinh học, Bowie-Dick, giải phóng mẻ, hạn lưu, thứ tự 8 trạm (cấu hình mặc định, A-64), thuật ngữ tiếng Việt. |
| Quy định kiểm định thiết bị áp lực | Khóa máy khi quá hạn kiểm định. |
| Thông tư 20/2021/TT-BYT — Quy định về quản lý chất thải y tế trong phạm vi khuôn viên cơ sở y tế | M10: phân loại & mã màu, bao bì/thùng, thời gian lưu giữ, bàn giao, báo cáo định kỳ (FR-M10-01..08). |
| Nghị định 08/2022/NĐ-CP — Quy định chi tiết một số điều của Luật Bảo vệ môi trường (chứng từ chất thải nguy hại, giấy phép môi trường) | M10: chứng từ chất thải nguy hại, đơn vị vận chuyển/xử lý có giấy phép (FR-M10-04, FR-M10-05). |
| ISO 11140-1 — Chemical indicators | Phân loại chỉ thị hóa học loại 1–6. |
| ISO 11138 — Biological indicators | Chỉ thị sinh học. |
| AAMI ST79 — Comprehensive guide to steam sterilization and sterility assurance | Cách ly mẻ cấy ghép chờ BI (BRU-REP-006). |
| GS1 General Specifications — GIAI (AI 8004), AI (01)(11)(17)(21), GS1 DataMatrix | Set ID, Cycle ID, nhãn. |
| ISO/IEC 25010 | Phân loại NFR. |
| ISO/IEC/IEEE 29148 | Cấu trúc SRS này. |

#### 1.5.2 Bộ tài liệu BA v1.10 (nguồn import)

| # | Mã | Tên | Trạng thái v1.10 |
| --- | --- | --- | --- |
| #00 | CHG | Theo dõi Cải tiến (đối sánh BA mới ↔ cũ) | Sửa |
| #01 | PID | Tài liệu Khởi tạo Dự án | Giữ nguyên |
| #02 | BRD | Tài liệu Yêu cầu Nghiệp vụ | Sửa |
| #03 | PRC | Quy trình AS-IS & TO-BE | Giữ nguyên |
| #04 | BRU | Quy tắc Nghiệp vụ (45 BRU) | Sửa |
| #05 | SRS | Đặc tả Yêu cầu Phần mềm (73 FR, 14 NFR) | Sửa |
| #06 | UC | Đặc tả Use Case (33 UC) | Sửa |
| #07 | US | User Story & Acceptance Criteria (33 US) | Sửa |
| #08 | DM | Mô hình Dữ liệu / ERD (40 DocType) | Sửa |
| #09 | UI | Đặc tả Giao diện & Hệ thống Thiết kế (37 SCR) | Sửa |
| #10 | PROTO | UI Prototype (hi-fi, bấm được) | Giữ nguyên |
| #11 | API | Đặc tả API (40 endpoint) | Sửa |
| #12 | ARCH | Kiến trúc & Tích hợp | Sửa |
| #13 | SEC | Ma trận Phân quyền & Bảo mật | Giữ nguyên |
| #14 | TC | Test Case & UAT Scenarios (66 TC) | Sửa |
| #15 | RTM | Ma trận Truy vết Yêu cầu | Sửa |
| #16 | WSS | Đặc tả Workflow & State Machine (9 WF, 48 trạng thái) | Sửa |
| #17 | — | Giao diện theo vai trò (phụ lục HTML) | Thêm |

---

## 2. Overall Description

### 2.1 Product perspective

TraceCore là hệ thống **độc lập, on-premise**, không tích hợp HIS/EMR/LIS. Ranh giới hệ thống và các tác nhân ngoài (từ #05 §1.1, #12 §1):

```
┌──────────────── Khoa sử dụng ────────────────┐   ┌──────── Web desktop ────────┐
│ PDA T8 (PWA)  · Cổng khoa (trình duyệt)       │   │ R01 R02 R09 R10: Desk        │
└───────────────┬───────────────────────────────┘   └──────────────┬──────────────┘
                │ HTTPS / REST+RPC (idempotent)                    │
┌───────────────▼───────────────────────────────────────────────────▼──────────────┐
│  TraceCore (Frappe/ERPNext v15 app)                                               │
│  DocType (40) · Workflow (9) · Server Script (BRU) · RPC cssd.v1.* · Reports      │
│  Scheduler · Print server (ZPL/TSPL) · Notification (email/push) · Audit hook      │
└───────────────▲───────────────────────────────────────────────────▲──────────────┘
                │ Wi-Fi nội bộ / LAN                                │
┌───────────────┴────────────┐ ┌────────────────────────┐ ┌────────┴────────────────┐
│ KHU BẨN  T1 T2             │ │ KHU SẠCH  T3 T4 T5     │ │ KHU VÔ KHUẨN T5b T6 T7  │
│ Trạm cảm ứng + PDA + agent │ │ Trạm + in nhãn + agent │ │ Trạm + PDA + agent      │
│ Máy quét · cân             │ │ Máy quét · in nhãn     │ │ Máy quét · in phiếu     │
│ Máy rửa 2 cửa ──────────► │ │ Máy hấp/plasma 2 cửa ─► │ │ Tủ ủ BI                 │
└────────────────────────────┘ └────────────────────────┘ └─────────────────────────┘
```

| Tác nhân ngoài | Tương tác vào hệ thống | Tương tác ra |
| --- | --- | --- |
| Nhân viên KSNK (R01–R07, R10) | Quét thẻ, quét mã, nhập dữ liệu trạm, cấu hình | Màn hình trạm, cảnh báo, báo cáo |
| Khoa sử dụng (R08) | Quét sử dụng, nhập mã bệnh nhân, trả đồ bẩn, nhận đồ vải | Phiếu cấp phát, thông báo thu hồi |
| Kế toán / Vật tư (R09) | Chi phí, giá, nhập kho | Giá thành, đề nghị mua |
| Máy in nhãn / máy quét / cân | Chuỗi quét, số cân | Lệnh in ZPL/TSPL |
| Máy rửa / máy tiệt khuẩn kết nối được | Dữ liệu mẻ CSV/API qua station agent | — |
| Cảm biến môi trường (tùy chọn) | Nhiệt độ, độ ẩm, áp suất chênh | — |
| Hệ thống email / SMS | — | Thông báo cảnh báo, thu hồi, chứng chỉ |
| Đơn vị xử lý chất thải (vận chuyển/xử lý có giấy phép) [v1.11] | Ký nhận bàn giao (chữ ký điện tử/ảnh biên bản), số chứng từ chất thải nguy hại | Phiếu bàn giao, chứng từ (PDF) |
| ERP bệnh viện (kế toán / mua sắm) | — | Xuất Excel/CSV (API giai đoạn sau) |
| HIS / EMR | **Không tích hợp** | — (API `cssd.v1` sẵn sàng mở) |

**Đặc thù nghiệp vụ quyết định kiến trúc** (từ #02 §1): mã vạch hai tầng; luồng một chiều 3 khu; chương trình theo máy; cơ số; đồ vải theo tổng hợp; [v1.11] chất thải theo tổng hợp khoa – loại – kg với mã QR túi/thùng.

### 2.2 Product functions (summary)

10 phân hệ, 39 Use Case, 90 FR gốc-cấp (73 FR từ #01 §3.1 + 9 FR-M9-08..16 + 8 FR-M10-01..08, duyệt 2026-10-17). Chi tiết FR tại §3.1.

| Mã | Viết tắt | Phân hệ | Phạm vi | UC | FR |
| --- | --- | --- | --- | --- | --- |
| `M1` | MD | Danh mục dụng cụ & bộ dụng cụ | Master data dụng cụ đơn lẻ, BOM bộ dụng cụ có phiên bản, Set ID vĩnh viễn, dụng cụ mượn, vật tư tái sử dụng, ngưỡng bảo dưỡng. | 4 (UC-01..04) | 9 (FR-M1-01..09) |
| `M2` | REP | Chuỗi tái xử lý & truy xuất | 8 trạm (cấu hình mặc định, A-64) quét; Cycle ID; lô rửa, mẻ tiệt khuẩn; cổng kiểm soát; dữ liệu máy; kho vô khuẩn FEFO; cấp phát; sử dụng; truy xuất; thu hồi; sự cố – CAPA. | 11 (UC-05..15) | 25 (FR-M2-01..25) |
| `M3` | LIN | Quản lý đồ vải | Thu gom – giặt – cấp phát theo khoa, loại, số lượng, cân nặng; đối chiếu thu – trả. | 3 (UC-16..18) | 6 (FR-M3-01..06) |
| `M4` | HR | Nhân sự & chứng chỉ | Hồ sơ, CCHN, chứng chỉ KSNK, ma trận năng lực gắn quyền trạm, phân ca. | 2 (UC-19..20) | 4 (FR-M4-01..04) |
| `M5` | EQP | Thiết bị & bảo trì | Hồ sơ thiết bị, chương trình xử lý theo máy, bảo trì – kiểm định, test hằng ngày, khóa máy. | 3 (UC-21..23) | 6 (FR-M5-01..06) |
| `M6` | INV | Kho vật tư tiêu hao | Nhập – xuất – tồn theo lô/hạn, FEFO, tiêu hao tự động theo mẻ, kiểm kê, tồn tối thiểu. | 3 (UC-24..26) | 6 (FR-M6-01..06) |
| `M7` | CST | Chi phí & giá thành tái xử lý | Chi phí đầu vào, bảng định giá có phiên bản, phân bổ theo mẻ, giá thành từng bộ. | 3 (UC-27..29) | 6 (FR-M7-01..06) |
| `M8` | PAR | Cơ số & kiểm soát vượt ngưỡng | Cơ số tái xử lý tối đa, cơ số tồn khoa, cảnh báo sớm, chặn sinh Cycle ID, ghi đè có phê duyệt. | 2 (UC-30..31) | 4 (FR-M8-01..04) |
| `M9` | RPT | Báo cáo, dashboard & quản trị | Dashboard, sổ tiệt khuẩn điện tử, báo cáo BYT, khu/trạm, môi trường, người dùng, audit trail, sinh mã đối tượng, offline trạm; [v1.11] phiên/đăng xuất, mật khẩu, thông báo, import/export, tìm kiếm, trạng thái màn hình, trợ giúp, xóa mềm. | 4 (UC-32..33, UC-38..39) | 16 (FR-M9-01..16) |
| `M10` | WST | Quản lý chất thải y tế [v1.11] | Danh mục loại chất thải & mã màu (TT 20/2021/TT-BYT), thu gom theo khoa – loại – số – kg, lưu giữ tạm & hạn lưu, bàn giao đơn vị xử lý có giấy phép + chứng từ (NĐ 08/2022/NĐ-CP), sự cố, báo cáo, định mức. Toàn bệnh viện, khoa KSNK giám sát; chỉ chất thải rắn. | 4 (UC-34..37) | 8 (FR-M10-01..08) |

### 2.3 User classes & characteristics

10 vai trò (R01–R10). Mô tả dưới đây tổng hợp từ #01 §5, #02 §4, #03 §3.1, #05 §1, #13 §1 và là **đầu vào cho `ux-foundations`** (persona, surface, thiết bị). Khối lượng vận hành tham chiếu (AS-IS, #03 §1.1): 120–200 bộ/ngày, 15–25 lô rửa/ngày, 10–16 mẻ/ngày, tồn 600–900 gói, 80–150 gói cấp phát/ngày, 60–120 ca mổ/ngày. Tổng ước tính **25–40 người dùng đồng thời** (#01 §1).

| Mã | Vai trò | Bối cảnh làm việc & nhu cầu chính | Surface / thiết bị | Cách đăng nhập | Tần suất dùng | BR liên quan |
| --- | --- | --- | --- | --- | --- | --- |
| **R01** | Trưởng khoa KSNK | Chủ sản phẩm nghiệp vụ. Phê duyệt cơ số, ghi đè cảnh báo vượt cơ số, duyệt thu hồi, giải phóng mẻ khẩn cấp, cấp gói cấy ghép trước BI, duyệt bảng giá; xem toàn bộ báo cáo và chi phí; xem mã bệnh nhân đầy đủ (có lý do, ghi audit). Làm việc chủ yếu tại văn phòng, cần tiếp nhận thông báo và phê duyệt nhanh (ghi đè trong 5 phút — BRK-05). | Web desktop (Frappe Desk); đọc mọi khu; nhận thông báo email/push | Thẻ + PIN (phê duyệt PIN 6 số); 2FA theo #13 §3 | Hằng ngày, theo sự kiện phê duyệt | BR-M7, BR-M8, BR-M9 |
| **R02** | Điều dưỡng trưởng / Giám sát CSSD | Đại diện người dùng chính, UAT, đào tạo nội bộ. Điều phối ca, giải phóng mẻ (có kiểm soát, PIN), quản lý cơ số, duyệt NC-CAPA, kiểm kê, xác nhận đóng gói thiếu, mở khóa máy tạm, chuyển trạng thái thủ công khi sự cố, gia hạn hạn lưu, xử lý xung đột đồng bộ offline, quản lý master data M1/M3/M4/M5. Di chuyển giữa 3 khu. | Web desktop + mọi trạm cảm ứng + PDA | Thẻ + PIN; 2FA | Liên tục trong ca | BR-M2, BR-M4, BR-M5, BR-M8 |
| **R03** | KTV khu bẩn | Tiếp nhận đồ bẩn (quét Set ID + thẻ nhân viên giao, xác nhận thành phần, ghi chú bất thường), tạo lô rửa (quét QR máy → quét từng bộ → Hoàn thành nạp), dỡ lô (quét QR máy + QR lô, nhập kết quả có xác nhận). Môi trường áp suất âm, **đeo găng, màn hình ướt**, thao tác 1–3 chạm, nhiều bộ nối tiếp (120–200 bộ/ngày). | Trạm cảm ứng T1, T2 (kiosk Chromium 15–22") + PDA Android; máy quét cố định; cân | Thẻ (phiên 8 giờ, tự khóa 10 phút); cần năng lực trạm T1/T2 còn hiệu lực | Liên tục trong ca | BR-M2 |
| **R04** | KTV khu sạch (kiểm tra – lắp ráp – đóng gói) | Kiểm đếm theo BOM có ảnh chụp thực tế, ghi thiếu/hỏng/thay, xử lý nhắc tra dầu, đóng gói: tick từng dụng cụ, quét lô chỉ thị hóa học, Xác nhận hoàn thành đóng gói → Cycle ID tự sinh, in nhãn đúng loại (hấp/plasma). Đề nghị ghi đè cơ số. Áp suất dương; cần màn hình lớn hiển thị ảnh/BOM, kính lúp. | Trạm cảm ứng T3, T4 với máy in nhãn (2 máy in hoặc 1 máy đổi cuộn), máy quét, máy hàn túi | Thẻ; năng lực T3/T4 | Liên tục trong ca | BR-M1, BR-M2, BR-M8 |
| **R05** | KTV tiệt khuẩn | Test hằng ngày (Bowie-Dick, leak test), tạo mẻ (quét QR máy → chọn chương trình → quét từng gói → Hoàn thành nạp → Load ID), nhập tay dữ liệu máy có xác nhận hoặc nhận tự động, dỡ mẻ, nhập chỉ thị, đề nghị giải phóng. Thao tác cả hai phía máy hai cửa (T5 khu sạch, T5b khu vô khuẩn). | Trạm cảm ứng T5/T5b + PDA; máy quét; tủ ủ BI; camera chụp bản in máy | Thẻ; năng lực T5 + chứng chỉ vận hành thiết bị áp lực | Theo mẻ (10–16 mẻ/ngày) | BR-M2, BR-M5, BR-M6 |
| **R06** | KTV kho vô khuẩn / cấp phát | Nhập kho vô khuẩn theo vị trí kệ (QR kệ), FEFO, xử lý gói hết hạn/hỏng, cấp phát cho khoa (quét gói + thẻ người nhận, kiểm tra cơ số khoa, ký điện tử, in phiếu). Môi trường 18–22°C, 35–60% RH. | Trạm cảm ứng T6, T7 + PDA; máy quét; máy in phiếu | Thẻ; năng lực T6/T7 | Liên tục; cao điểm đầu ca mổ | BR-M2, BR-M6 |
| **R07** | Nhân viên đồ vải & chất thải [v1.11 mở rộng] | Thu gom đồ vải theo khoa (chọn khoa, loại, số chiếc, cân — cân điện tử), phân luồng nhiễm/không nhiễm, tạo lô giặt theo kg, cấp phát đồ vải theo khoa, đối chiếu. [v1.11] Thu gom chất thải y tế tại khoa (quét thẻ người giao, loại, số túi, cân), nhập kho lưu giữ tạm, bàn giao đơn vị xử lý, ghi sự cố chất thải. Làm việc tại nhà giặt / kho chất thải, tay ướt, đeo găng. | Trạm đồ vải (cảm ứng) có cân RS-232/USB; trạm/PDA thu gom chất thải có cân | Thẻ | Hằng ngày, theo lượt thu gom/cấp phát/bàn giao | BR-M3; M10 (FR-M10-02..04, 06) |
| **R08** | Nhân viên khoa sử dụng (phòng mổ / khoa lâm sàng) | Nhận bộ dụng cụ, **quét sử dụng gắn mã bệnh nhân – ca mổ – PTV trước rạch da** (màn PDA 1 chạm), trả đồ bẩn, nhận đồ vải, xác nhận gói thu hồi. Người dùng không thuộc khoa KSNK, ít thời gian, rủi ro bỏ qua quét (RK-03/BRK-01); chỉ thấy dữ liệu khoa mình. | PDA Android (PWA) tại phòng mổ / máy tính phòng mổ (T8); Cổng khoa (trình duyệt web) | Thẻ (thẻ nhân viên do hệ thống sinh hoặc thẻ bệnh viện đã đăng ký) | Theo ca mổ (60–120 ca/ngày toàn viện) | BR-M2, BR-M3 |
| **R09** | Kế toán / Vật tư | Nhập chi phí theo khoản mục (khấu hao, điện, nước, hóa chất, nhân công, thuê ngoài…), bảng định giá vật tư có phiên bản, hóa đơn điện nước, nhập kho theo lô/hạn, xem giá thành, xuất Excel/CSV cho kế toán bệnh viện. Làm việc theo kỳ (tháng). | Web desktop | Tài khoản + 2FA | Theo kỳ (tháng/tuần) | BR-M6, BR-M7 |
| **R10** | Quản trị hệ thống (Phòng CNTT) | Cấu hình 3 khu một chiều, trạm, thiết bị ngoại vi (IP/cổng), người dùng, phân quyền, mẫu nhãn, chương trình, định mức, cơ số (cấu hình không code); xem toàn bộ audit trail; vô hiệu tài khoản nghỉ việc trong ngày; rà soát quyền hằng quý; nhận cảnh báo truy cập bất thường; hạ tầng, sao lưu. | Web desktop (Desk cấu hình) | Tài khoản + 2FA | Theo nhu cầu; hằng quý rà soát | BR-M9 |

**Đặc điểm chung của nhóm KTV trạm (R03–R07):** làm việc theo ca, đeo găng, tay/màn hình có thể ướt, thao tác lặp với số lượng lớn, cần phản hồi quét ≤ 1 giây, cảnh báo đỏ toàn màn khi bị chặn, tối đa 3 chạm cho thao tác chính, nút ≥ 48 px (NFR-USAB-01), tiếng Việt với thuật ngữ QĐ 3671 (NFR-USAB-02). Quyền vận hành trạm phụ thuộc năng lực + chứng chỉ còn hạn (BRU-HR-001); R02 có thể cấp quyền trạm tạm thời 24 giờ.

### 2.4 Operating environment

Từ #05 §1, #05 §4, #12 §2, §5.

| Lớp | Môi trường vận hành |
| --- | --- |
| **Giao diện người dùng (3 lớp)** | (1) **Web desktop** — Frappe Desk + JS tùy biến cho R01, R02, R09, R10 (quản trị, danh mục, kho, chi phí, báo cáo, dashboard). (2) **Trạm quét cảm ứng (kiosk)** — trang web full-screen Chromium kiosk trên mini PC Windows/Linux, màn cảm ứng 15–22", cho T1–T7 và trạm đồ vải. (3) **PDA Android PWA** — Android 12+, máy quét tích hợp, Service Worker + IndexedDB, hàng đợi offline, cho T1/T5/T7/T8. Kèm **Cổng khoa** (Website/Portal Page, Web Form) cho R08. |
| **Thiết bị ngoại vi** | Máy quét mã (HID keyboard wedge / serial); máy in nhãn nhiệt chuyển 300 dpi (ZPL/TSPL qua TCP 9100) với 2 loại nhãn hấp 134°C / plasma H2O2; cân điện tử RS-232/USB qua station agent; máy in phiếu; tủ ủ BI; cảm biến môi trường (Modbus/HTTP, tùy chọn). |
| **Thiết bị xử lý (tham chiếu, #01 §7)** | 2 máy hấp hơi nước hai cửa, 2 máy rửa khử khuẩn, 1 máy plasma H2O2, 1 máy hàn túi, 1 máy giặt, 1 máy sấy công nghiệp. Mỗi máy khai báo: kết nối API được hay không (`is_connected`), có bản in hay không (`has_printout`). |
| **Server** | On-premise tại bệnh viện; Ubuntu 22.04; 8 vCPU / 16 GB RAM cho ≤ 40 trạm; VM dự phòng. |
| **Nền tảng ứng dụng** | Frappe Framework v15 / ERPNext v15 (nhánh version-15), Python 3.11, Node 18; app tùy biến `tracecore`; Frappe HR (hrms) bắt buộc; Insights, Print Designer khuyến nghị; Raven, Wiki, Builder, Drive tùy chọn. |
| **CSDL / hạ tầng** | MariaDB 10.6 (binlog), Redis 7, Nginx + TLS nội bộ, CUPS/raw socket 9100 cho in, SMTP / SMS gateway, push (Firebase tùy chọn). |
| **Mạng** | Wi-Fi nội bộ phủ 3 khu + LAN; PDA chỉ kết nối SSID KSNK; máy in trong VLAN thiết bị; trạm kiosk khóa OS; PDA quản lý MDM. |
| **Giám sát / sao lưu** | Prometheus/Grafana hoặc Frappe Monitor; bench backup + rsync ngoại vi; binlog 15 phút. |
| **Phiên bản** | Mục tiêu ERPNext v15. Nếu Phòng CNTT chọn v16/v17 (phát hành 12/2025) phải kiểm tra từng app tùy chọn đã hỗ trợ nhánh tương ứng trước khi chốt (xem OQ-11). |

### 2.5 Constraints

Từ #01 §7 (Ràng buộc), #02 §5, #05 §4.

| Loại | Ràng buộc | Ảnh hưởng thiết kế |
| --- | --- | --- |
| Pháp lý | TT 16/2018/TT-BYT về kiểm soát nhiễm khuẩn | Hồ sơ nhân sự, đồ vải nhiễm, giám sát tuân thủ. |
| Pháp lý | QĐ 3671/QĐ-BYT hướng dẫn khử khuẩn, tiệt khuẩn | Chỉ thị hóa học/sinh học, Bowie-Dick, giải phóng mẻ, hạn lưu, thứ tự 8 trạm (cấu hình mặc định, A-64), thuật ngữ. |
| Pháp lý | Quy định kiểm định thiết bị áp lực | Khóa máy khi quá hạn kiểm định; không mở khóa tạm với quá hạn kiểm định áp lực (BRU-EQP-002). |
| Pháp lý | Hồ sơ tiệt khuẩn lưu ≥ 10 năm | Lưu trữ, audit không xóa, chỉ vô hiệu. |
| Pháp lý [v1.11] | TT 20/2021/TT-BYT quản lý chất thải y tế; NĐ 08/2022/NĐ-CP chứng từ chất thải nguy hại | M10: nhóm & mã màu cố định theo TT; thời gian lưu giữ tối đa tham số; chỉ bàn giao đơn vị có giấy phép còn hiệu lực; chứng từ bắt buộc với chất thải nguy hại. |
| Kỹ thuật | Không tích hợp HIS | Mã bệnh nhân nhập tay, mã hóa AES-256 tại trường; API `cssd.v1` để mở cho giai đoạn sau. |
| Kỹ thuật | Nền tảng Frappe v15+/ERPNext; MariaDB; Redis; Python 3.11; PWA cho PDA | Toàn bộ nghiệp vụ hiện thực bằng DocType, Workflow, Server Script, hook; không xây hệ thống riêng ngoài Frappe. |
| Kỹ thuật | Mã vạch (chốt 2026-10-17): Set ID = GS1 DataMatrix GIAI AI 8004 duy nhất (tiền tố GS1 bệnh viện); Cycle ID = GS1 DataMatrix (01)(11)(17)(21) duy nhất (không dùng Code-128 làm mã máy đọc; có thể in thêm dòng người đọc) | Thư viện mã hóa GS1 (pylibdmtx/python-barcode) hoặc mã hóa tại máy in. |
| Kỹ thuật | Nhãn phải chịu 134°C (hấp) và plasma H2O2; hai loại nhãn riêng, máy in/cuộn gán theo loại | Mẫu nhãn theo phương pháp; chặn in sai loại (BRU-REP-011). |
| Vận hành | Khoa một chiều 3 khu, máy hai cửa | Trạm thuộc đúng một khu; chặn thao tác ngược chiều; máy hai cửa khai báo cửa vào/ra. |
| Vận hành | Mọi chứng từ ở trạng thái Nháp trước khi ghi sổ; hủy tạo bản ghi hủy, không xóa | Workflow Frappe (Draft → Submitted → Cancelled). |
| Tài chính | Chi phí phải khớp kế toán quản trị | Bảng định giá có phiên bản; không tính lại giao dịch quá khứ (BRU-CST-002). |
| Ngôn ngữ | Tiếng Việt chính; thuật ngữ theo QĐ 3671; tiếng Anh cho nhãn | Bản dịch `vi` cho toàn bộ DocType/màn hình. |

### 2.6 Assumptions & dependencies

**Giả định (từ #01 §7):**

| # | Giả định |
| --- | --- |
| A-01 | Bệnh viện cung cấp danh mục dụng cụ, BOM, IFU và cơ số tái xử lý của nhà sản xuất trước Sprint 1. |
| A-02 | Mạng Wi-Fi phủ 3 khu; mỗi khu có ít nhất 1 trạm cố định và 1 PDA; nhãn chịu hấp và máy in được mua sắm trước UAT. |
| A-03 | Thiết bị mẫu: 2 máy hấp hơi nước hai cửa, 2 máy rửa khử khuẩn, 1 máy plasma H2O2, 1 máy hàn túi, 1 máy giặt, 1 máy sấy công nghiệp. |
| A-04 | Định mức điện – nước – tiêu hao theo chương trình dùng giá trị mặc định theo loại máy, hiệu chỉnh sau 2 tháng bằng đồng hồ đo (RK-04, BRK-04). |
| A-05 | Khi cơ số IFU không có cho dụng cụ cũ, cho phép để trống (Chưa xác định) hoặc cơ số mặc định theo nhóm; chỉ cảnh báo, không chặn (BRK-02). |

**Phụ thuộc — bàn giao từ bệnh viện trước Sprint 1 (từ cover.md):**

| # | Hạng mục bàn giao | Phụ thuộc của |
| --- | --- | --- |
| D-01 | Danh mục dụng cụ và BOM từng loại bộ kèm **ảnh chụp thực tế** (mỗi dụng cụ một ảnh; mỗi bộ 1–3 ảnh đã sắp xếp). | M1, FR-M1-01, FR-M1-03, FR-M2-05, FR-M2-07, FR-M2-23 |
| D-02 | Cơ số tái xử lý (theo IFU hoặc ước tính), ngưỡng bảo dưỡng tra dầu, hạn lưu theo loại gói — nhập tay. | M8, FR-M1-09, FR-M8-01, BRU-REP-009 |
| D-03 | Tiền tố GS1 của bệnh viện; mẫu 2 loại nhãn (hấp / plasma); máy in nhãn, máy quét, cân. | FR-M1-05, FR-M2-08, EI-HW-* |
| D-04 | Danh sách thiết bị: máy nào kết nối API được, máy nào có bản in. | FR-M2-10, FR-M2-24, EI-SW-001 |

**Phụ thuộc kỹ thuật:** Frappe/ERPNext/HRMS nhánh version-15; thư viện GS1 DataMatrix; firmware máy in hỗ trợ ZPL hoặc TSPL; driver/giao thức cân; SMTP/SMS gateway của bệnh viện; (tùy máy) định dạng CSV export hoặc API của hãng máy rửa/tiệt khuẩn.

---

## 3. Specific Requirements

### 3.1 Functional requirements

Cú pháp: EARS (xem `ears-guide.md`). Mẫu câu tiếng Việt dùng thống nhất trong toàn mục:

| Pattern EARS | Mẫu tiếng Việt |
| --- | --- |
| Ubiquitous | Hệ thống phải … |
| Event-driven | **Khi** <trigger>, hệ thống phải … |
| State-driven | **Trong khi** <trạng thái>, hệ thống phải … |
| Optional feature | **Khi tính năng** <X> **được bật**, hệ thống phải … |
| Unwanted behaviour | **Nếu** <điều kiện không mong muốn>, **thì** hệ thống phải … |

Quy ước ID: `FR-Mx-NN` là ID gốc (giữ nguyên từ SRS v1.10 d05; FR-M9-08..16 và FR-M10-01..08 là ID mới v1.11, duyệt 2026-10-17) và chứa câu EARS chính; `FR-Mx-NN.k` là các câu EARS con tách từ Tiêu chí chấp nhận, Xử lý lỗi/ngoại lệ và BRU áp dụng. Priority theo MoSCoW của FR gốc trừ khi ghi khác. Vai trò R01–R10 theo mục 1 d05. Trạm T1 Tiếp nhận, T2 Rửa, T3 Lắp ráp, T4 Đóng gói, T5 Tiệt khuẩn, T6 Kho vô khuẩn, T7 Cấp phát.

#### 3.1.1 M1 — Danh mục dụng cụ & bộ dụng cụ

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M1-01 | Khi người dùng lưu bản ghi Dụng cụ đơn lẻ với đủ mã, tên, hãng, model, ảnh chụp thực tế, phân loại Spaulding (thiết yếu/bán thiết yếu/không thiết yếu), file IFU, phương pháp tiệt khuẩn tương thích (hấp 121/134, plasma, EO), cơ số tái xử lý tối đa, giá trị và nhóm, hệ thống phải tạo bản ghi Dụng cụ ở trạng thái Đang dùng và đưa dụng cụ vào danh sách chọn khi lập BOM. | Must | Active | UC-01; SCR-01; API-M1-01, API-M1-06; phụ thuộc FR-M1-02, FR-M1-09. Nguồn: BR-M1 |
| FR-M1-01.1 | Nếu bản ghi Dụng cụ thiếu mã, tên, phân loại Spaulding hoặc phương pháp tiệt khuẩn tương thích, thì hệ thống phải từ chối lưu và chỉ rõ trường thiếu. | Must | Active | TCCN 1 |
| FR-M1-01.2 | Khi bản ghi Dụng cụ được lưu với cơ số tái xử lý tối đa để trống, hệ thống phải đánh dấu cơ số là Chưa xác định và đưa dụng cụ vào báo cáo cần bổ sung. | Must | Active | TCCN 2 |
| FR-M1-01.3 | Khi người dùng sửa phương pháp tiệt khuẩn tương thích của một Dụng cụ, hệ thống phải tạo phiên bản mới của Dụng cụ, giữ lịch sử phiên bản cũ và phát cảnh báo tới mọi BOM đang dùng dụng cụ đó. | Must | Active | TCCN 3; xem A-06 (I1, I3, tạm): không thêm DocType phiên bản, `version_no` + Audit Log, cảnh báo không chặn |
| FR-M1-01.4 | Nếu mã dụng cụ nhập vào trùng với mã đã tồn tại, thì hệ thống phải báo lỗi trùng mã và gợi ý mã kế tiếp còn trống. | Must | Active | Xử lý lỗi |
| FR-M1-01.5 | Nếu file IFU tải lên lớn hơn 20 MB, thì hệ thống phải từ chối file và thông báo giới hạn dung lượng. | Must | Active | Xử lý lỗi |
| FR-M1-01.6 | Trong khi ảnh chụp thực tế dụng cụ đã được tải lên, hệ thống phải hiển thị ảnh đó tại các trạm T1, T3 và T4 khi dụng cụ xuất hiện trong BOM của bộ đang xử lý. | Must | Active | Đầu vào; liên kết FR-M2-23, FR-M2-05 |
| FR-M1-02 | Khi tính năng mã DataMatrix dụng cụ đơn lẻ được bật, hệ thống phải cho phép ghi nhận trên mỗi Dụng cụ chuỗi DataMatrix khắc laser (GS1 GIAI, cùng tiền tố GS1 với Set ID), ngày khắc và vị trí khắc. | Should | Active | UC-01; SCR-01; API-M1-01, API-M1-06; phụ thuộc FR-M1-01, FR-M1-09. Nguồn: BR-M1; xem A-06 (I7, I8, tạm): cờ `TraceCore Settings`, mã `<prefix>I-########` |
| FR-M1-02.1 | Hệ thống phải coi trường mã đơn lẻ là tùy chọn và, khi có giá trị, phải bảo đảm giá trị đó duy nhất trên toàn hệ thống. | Should | Active | TCCN 1 |
| FR-M1-02.2 | Khi tính năng mã dụng cụ đơn lẻ được bật và người dùng quét mã đơn lẻ tại trạm lắp ráp T3, hệ thống phải tự tick dòng BOM tương ứng của bộ đang lắp. | Should | Active | TCCN 2; liên kết FR-M2-05; A-06 (I17): chuyển sang FEAT-020 |
| FR-M1-02.3 | Khi quản trị viên bật hoặc tắt tính năng mã dụng cụ đơn lẻ trong cấu hình, hệ thống phải áp dụng thay đổi mà không làm gián đoạn luồng tái xử lý chính (T1→T7). | Should | Active | TCCN 3 |
| FR-M1-02.4 | Nếu mã đơn lẻ được quét tại T3 không thuộc BOM của bộ đang lắp, thì hệ thống phải cảnh báo Dụng cụ lạ và ghi một NC. | Should | Active | Xử lý lỗi; liên kết FR-M2-21; A-06 (I17): chuyển sang FEAT-020 |
| FR-M1-03 | Khi người dùng tạo Loại bộ dụng cụ với tên loại bộ, khoa sở hữu, danh sách dụng cụ × số lượng, ảnh chụp thực tế bộ đã sắp xếp hoàn chỉnh trong khay (tải lên, có thể nhiều góc, không phải sơ đồ vẽ), loại gói mặc định, phương pháp tiệt khuẩn, hạn lưu, cờ cấy ghép và thời gian lắp ráp chuẩn (phút), hệ thống phải tạo Loại bộ có BOM phiên bản 1 và sinh phiếu kiểm đếm in được (PDF). | Must | Active | UC-02; SCR-02; API-M1-02; phụ thuộc FR-M1-04. Nguồn: BR-M1 |
| FR-M1-03.1 | Nếu BOM không có dụng cụ nào, thì hệ thống phải từ chối lưu Loại bộ. | Must | Active | TCCN 1 |
| FR-M1-03.2 | Khi phiếu kiểm đếm được in, hệ thống phải hiển thị tổng số dụng cụ của BOM, ảnh chụp thực tế bộ đã sắp xếp và thứ tự xếp dụng cụ trên phiếu. | Must | Active | TCCN 1, 3 |
| FR-M1-03.3 | Nếu phương pháp tiệt khuẩn của Loại bộ không tương thích với một dụng cụ bất kỳ trong BOM, thì hệ thống phải báo lỗi trên từng dòng dụng cụ không tương thích và không cho lưu. | Must | Active | TCCN 2; xem A-09 (S5, tạm): chặn theo họ phương pháp `Steam`/`Plasma`, lỗi từng dòng cùng lúc |
| FR-M1-03.4 | Khi người dùng nhập hạn lưu cho Loại bộ, hệ thống phải lấy mặc định từ hạn lưu nhập tay của Loại gói đã chọn và chỉ cho phép ghi đè bằng giá trị ngắn hơn. | Must | Active | Đầu vào; BRU-REP-009; xem A-09 (S7, tạm): `shelf_life_days` là ghi đè, chỉ nhận giá trị ngắn hơn hạn loại gói |
| FR-M1-03.5 | Nếu Loại gói được chọn chưa có hạn lưu, thì hệ thống phải không cho chọn Loại gói đó. | Must | Active | BRU-REP-009 (hệ thống không có giá trị hạn lưu mặc định cứng); xem A-09 (S7, tạm): loại gói là Item Packaging còn dùng có `tc_shelf_life_days` > 0 |
| FR-M1-03.6 | Nếu người dùng thêm vào BOM mới một dụng cụ đã ở trạng thái Ngừng sử dụng, thì hệ thống phải từ chối dòng đó. | Must | Active | Xử lý lỗi |
| FR-M1-04 | Khi người dùng lưu thay đổi BOM (thêm/bớt dòng, sửa số lượng) kèm ngày hiệu lực và lý do, hệ thống phải tạo phiên bản BOM mới tăng số phiên bản và không sửa đè phiên bản cũ. | Must | Active | UC-02; SCR-02; API-M1-02; phụ thuộc FR-M1-03. Nguồn: BR-M1; xem A-09 (S1, S4, tạm): không thêm DocType phiên bản, phiên bản bất biến, tạo qua `bom_versions` kèm lý do |
| FR-M1-04.1 | Trong khi một bộ vật lý đang ở trong chu trình tái xử lý, hệ thống phải giữ phiên bản BOM cũ cho bộ đó cho tới khi bộ được tiếp nhận lại tại T1. | Must | Active | TCCN 2; xem A-09 (S3, tạm): ghim `Set Unit.cycle_bom_version` trong `step_gate.start_cycle` |
| FR-M1-04.2 | Khi một bộ vật lý được tiếp nhận tại T1 sau ngày hiệu lực của phiên bản BOM mới, hệ thống phải áp dụng phiên bản BOM mới cho chu trình kế tiếp của bộ. | Must | Active | Đầu ra; xem A-09 (S3, tạm): "sau ngày hiệu lực" hiểu là từ ngày hiệu lực (≥) |
| FR-M1-04.3 | Khi người dùng chọn hai phiên bản BOM của một Loại bộ, hệ thống phải hiển thị màn so sánh khác biệt giữa hai phiên bản. | Must | Active | TCCN 3 |
| FR-M1-04.4 | Nếu ngày hiệu lực của phiên bản BOM mới nằm trong quá khứ, thì hệ thống phải chặn lưu. | Must | Active | Xử lý lỗi; xem A-09 (S2, tạm): hôm nay được, quá khứ bị chặn, ngày theo `Asia/Ho_Chi_Minh` |
| FR-M1-05 | Khi người dùng yêu cầu tạo bộ vật lý với loại bộ, số lượng bộ, tiền tố mã và mẫu thẻ, hệ thống phải cấp cho mỗi bộ một Set ID duy nhất theo chuẩn GS1 DataMatrix GIAI (AI 8004 — duy nhất, chốt 2026-10-17) với tiền tố GS1 của bệnh viện, tạo bản ghi Set Unit ở trạng thái Mới tạo và sinh bản in thẻ kim loại/nhãn khay. | Must | Active | UC-03; SCR-03; API-M1-03, API-M1-04; BRU-ID-001, BRU-ID-006; phụ thuộc FR-M1-06. Nguồn: BR-M1; A-13 (G4–G8): Set Unit chỉ tạo qua cấp Set ID, "tiền tố mã" là cấu hình site, "mẫu thẻ" = chọn loại bản in (thẻ kim loại / nhãn khay) |
| FR-M1-05.1 | Khi tạo hàng loạt tới 100 bộ trong một lần, hệ thống phải bảo đảm không sinh Set ID trùng. | Must | Active | TCCN 1; A-13 (G1–G3): 1–100 bộ/lần, nguyên tử, GIAI không check digit, chặn hết dải và tiền tố demo |
| FR-M1-05.2 | Hệ thống phải không cho sửa Set ID sau khi đã cấp và không tái cấp Set ID cho bộ khác, kể cả khi bộ đã Thanh lý. | Must | Active | TCCN 2; BRU-ID-001 |
| FR-M1-05.3 | Khi người dùng in lại thẻ Set ID, hệ thống phải yêu cầu lý do và ghi số lần in. | Must | Active | TCCN 3; A-13 (G10, G11): lý do 1–500 ký tự, số lần in suy ra từ Print Job |
| FR-M1-05.4 | Nếu máy in không phản hồi khi in thẻ, thì hệ thống phải lưu Set ID đã cấp, cho phép in lại sau và không tạo mã mới. | Must | Active | Xử lý lỗi; A-13 (G9): một Print Job cho mỗi nhãn, gửi cả lô bằng một RQ job |
| FR-M1-05.5 | Khi tạo bộ mượn, hệ thống phải cấp Set ID với tiền tố LN và ngày hết hiệu lực khi trả hãng. | Must | Active | BRU-ID-001 ngoại lệ; liên kết FR-M1-07 |
| FR-M1-06 | Khi nhận sự kiện từ các trạm T1–T7 hoặc từ mẻ giải phóng, hệ thống phải cập nhật trạng thái Set Unit (Mới tạo / Đang lưu hành / Đang xử lý / Xử lý lại / Vô khuẩn / Tại khoa / Chờ tiếp nhận / Hết vòng đời / Thanh lý) và ghi lịch sử vòng đời. | Must | Active | UC-03; SCR-03; API-M1-03, API-M1-04; BRU-ID-001, BRU-ID-006; phụ thuộc FR-M1-05. Nguồn: BR-M1; A-13 (G13, G14): 9 giá trị của `Set Unit.status`; lịch sử từ Audit Log kèm sự kiện step gate; hook `tracecore_after_set_status` khi trạng thái đổi; thao tác Thanh lý hoãn sang FEAT-032 |
| FR-M1-06.1 | Khi mẻ chứa bộ được giải phóng Đạt, hệ thống phải tăng bộ đếm chu trình của Set Unit đúng 1, kể cả khi chu trình đó là tái xử lý lại do mẻ lỗi. | Must | Active | TCCN 1; BRU-PAR-001 |
| FR-M1-06.2 | Khi người dùng mở màn hình Set Unit, hệ thống phải hiển thị số chu trình đã dùng, cơ số tối đa, số chu trình còn lại và Cycle ID đang hiệu lực. | Must | Active | TCCN 2; A-13 (G6, G13): hiển thị thêm nguồn số chu trình (Thực tế / Ước tính) và phiên bản BOM |
| FR-M1-06.3 | Khi số chu trình đã dùng của Set Unit đạt cơ số tối đa, hệ thống phải tự chuyển Set Unit sang Hết vòng đời – chờ thanh lý. | Must | Active | TCCN 3; theo FR-M8-03, BRU-PAR-002 |
| FR-M1-06.4 | Nếu các sự kiện trạm đến sai thứ tự (do đồng bộ offline), thì hệ thống phải xếp lại sự kiện theo dấu thời gian của trạm trước khi cập nhật vòng đời. | Must | Active | Xử lý lỗi; liên kết FR-M9-06 |
| FR-M1-07 | Khi người dùng nhập bộ mượn với hãng cho mượn, tên bộ, BOM mượn (nhập nhanh hoặc file), ngày nhận, ngày trả dự kiến và IFU, hệ thống phải cấp Set ID tạm tiền tố LN và sinh biên bản nhận (PDF). | Should | Active | UC-04; SCR-04; API-M1-05; phụ thuộc FR-M1-08. Nguồn: BR-M1 |
| FR-M1-07.1 | Trong khi bộ mượn chưa hoàn tất chuỗi tái xử lý đầy đủ (T1→T5), hệ thống phải không cho bộ mượn được cấp phát sử dụng lần đầu. | Should | Active | TCCN 1 |
| FR-M1-07.2 | Khi người dùng lập biên bản trả bộ mượn, hệ thống phải yêu cầu bộ đã qua chuỗi tái xử lý đầy đủ sau lần dùng cuối và liệt kê thiếu/hỏng so với BOM mượn trên biên bản trả (PDF). | Should | Active | TCCN 1, 2 |
| FR-M1-07.3 | Khi biên bản trả được xác nhận, hệ thống phải chuyển Set ID tạm LN sang Hết hiệu lực và không cho dùng lại. | Should | Active | TCCN 3 |
| FR-M1-07.4 | Nếu bộ mượn quá ngày trả dự kiến mà chưa có biên bản trả, thì hệ thống phải gửi cảnh báo tới R02 mỗi ngày cho tới khi trả. | Should | Active | Xử lý lỗi |
| FR-M1-08 | Trong khi bộ mượn ở trạng thái Mới nhận, hệ thống phải không cho sinh Cycle ID và không hiển thị bộ tại trạm đóng gói T4. | Should | Active | UC-04; SCR-04; API-M1-05; phụ thuộc FR-M1-07. Nguồn: BR-M1 |
| FR-M1-08.1 | Khi bộ mượn hoàn tất rửa (T2 Đạt) và lắp ráp (T3 Đạt), hệ thống phải cho phép đóng gói bộ mượn theo cùng luồng với bộ thường. | Should | Active | TCCN 2 |
| FR-M1-08.2 | Khi in nhãn Cycle ID cho bộ mượn, hệ thống phải in thêm dòng LOANER trên nhãn. | Should | Active | TCCN 3 |
| FR-M1-08.3 | Nếu Set ID tiền tố LN được quét tại T4 khi bộ chưa qua rửa, thì hệ thống phải báo lỗi kèm trạng thái hiện tại của bộ. | Should | Active | Xử lý lỗi |
| FR-M1-09 | Khi người dùng khai báo cho một Dụng cụ chu kỳ bảo dưỡng theo số chu trình và loại việc (tra dầu khớp, kiểm tra lưỡi, siết vít, thay pin), hệ thống phải lưu ngưỡng theo dụng cụ hoặc theo nhóm và khởi tạo bộ đếm chu trình từ lần bảo dưỡng gần nhất (DT-INSTRMAINT). | Must | Active | UC-01; SCR-01; API-M1-01, API-M1-06; BRU-REP-014; phụ thuộc FR-M1-01, FR-M1-02. Nguồn: BR-M1; xem A-06 (I5, I6, I16, tạm): ngưỡng theo `Instrument Group`, khởi tạo bộ đếm, hook tăng bộ đếm |
| FR-M1-09.1 | Khi ngưỡng bảo dưỡng của dụng cụ để trống, hệ thống phải không phát nhắc bảo dưỡng cho dụng cụ đó. | Must | Active | TCCN 1 |
| FR-M1-09.2 | Khi bộ đếm chu trình của Set tăng (mẻ giải phóng Đạt), hệ thống phải tăng đồng thời bộ đếm chu trình kể từ lần bảo dưỡng của từng dụng cụ trong BOM. | Must | Active | TCCN 2; BRU-PAR-001 |
| FR-M1-09.3 | Khi bộ đếm chu trình kể từ lần bảo dưỡng của một dụng cụ trong bộ đạt ngưỡng cấu hình, hệ thống phải hiển thị nhắc bảo dưỡng tại trạm T4 kèm ảnh dụng cụ và loại việc cần làm. | Must | Active | Mô tả; BRU-REP-014 |
| FR-M1-09.4 | Khi người đóng gói xác nhận Đã bảo dưỡng, hệ thống phải ghi người, thời điểm, lô dầu bôi trơn và đặt bộ đếm bảo dưỡng của dụng cụ về 0. | Must | Active | TCCN 3; BRU-REP-014 |
| FR-M1-09.5 | Khi người đóng gói chọn Hoãn bảo dưỡng, hệ thống phải yêu cầu lý do và ghi lại số lần hoãn. | Must | Active | BRU-REP-014 |
| FR-M1-09.6 | Nếu dụng cụ đã bị hoãn bảo dưỡng quá 3 chu trình, hoặc bộ đếm vượt ngưỡng cấu hình quá 20% mà chưa bảo dưỡng, thì hệ thống phải chặn sinh Cycle ID cho bộ cho tới khi dụng cụ được xác nhận Đã bảo dưỡng. | Must | Active | Xử lý lỗi (3 chu trình, R02 hoãn tối đa cho ca mổ khẩn); BRU-REP-014 (20%); xem A-02 (D5): chặn khi bộ đếm > ngưỡng × 1,2 hoặc số lần hoãn ≥ 3 |

#### 3.1.2 M2 — Chuỗi tái xử lý & truy xuất

Quy tắc chung của phân hệ (áp dụng cho mọi FR M2 từ FR-M2-01 đến FR-M2-18, nguồn BRU-FLOW-002/003):

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M2-00.1 | Khi Set ID hoặc Cycle ID được quét tại một trạm, hệ thống phải chỉ chấp nhận nếu trạng thái hiện tại của bộ/gói hợp lệ với trạm đó (ví dụ trạm cấp phát T7 chỉ nhận gói ở trạng thái Trong kho vô khuẩn). | Must | Active | BRU-FLOW-002 (chặn thao tác ngược chiều); áp dụng UC-05..UC-13 |
| FR-M2-00.2 | Nếu trạng thái của bộ/gói không hợp lệ với trạm đang quét, thì hệ thống phải báo lỗi kèm lý do và ghi audit. | Must | Active | BRU-FLOW-002 |
| FR-M2-00.3 | Khi R02 chuyển trạng thái bộ/gói thủ công trong tình huống sự cố hệ thống, hệ thống phải yêu cầu lý do và mã ticket sự cố, ghi audit và tạo NC. | Must | Active | BRU-FLOW-002 ngoại lệ; d04 mục 3 |
| FR-M2-00.4 | Hệ thống phải buộc mọi chu trình tái xử lý đi qua đủ thứ tự chức năng Tiếp nhận → Rửa → Lắp ráp → Đóng gói → Tiệt khuẩn → Kho vô khuẩn → Cấp phát → Sử dụng và không cho bỏ qua chức năng; số lượng và số thứ tự trạm thực hiện mỗi chức năng do cấu hình (A-64). | Must | Active | BRU-FLOW-003 |
| FR-M2-00.5 | Khi bộ bị phát hiện hư hỏng tại trạm lắp ráp T3, hệ thống phải cho phép rẽ nhánh bộ sang Sửa chữa/Thanh lý thay cho các trạm kế tiếp. | Must | Active | BRU-FLOW-003 ngoại lệ; liên kết FR-M2-05 |

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M2-01 | Khi KTV khu bẩn tại T1 quét mã vạch bộ dụng cụ và mã thẻ nhân viên khoa giao, hệ thống phải suy ra khoa trả từ thẻ, ghi người nhận, người giao, khoa, thời điểm, trạm cho bộ, mở danh sách thành phần bộ để xác nhận (FR-M2-23) rồi quay lại chờ quét bộ kế tiếp trong cùng phiếu tiếp nhận. | Must | Active | UC-05; SCR-05, SCR-34; API-M2-01, API-M1-06; BRU-FLOW-002, BRU-FLOW-003, BRU-REP-001, BRU-REP-012; phụ thuộc FR-M2-02, FR-M2-23, FR-M4-03. Nguồn: BR-M2 |
| FR-M2-01.1 | Trong khi một phiếu tiếp nhận đang mở tại T1, hệ thống phải chỉ chấp nhận hai loại mã quét: mã bộ dụng cụ và mã thẻ nhân viên; thẻ nhân viên giao quét một lần cho cả phiếu và không cho chọn khoa bằng tay khi đã có thẻ. | Must | Active | TCCN 1; BRU-REP-012 |
| FR-M2-01.2 | Khi bộ kế tiếp được quét trong cùng phiếu, hệ thống phải ghi nhận không cần thao tác thêm và hiển thị trên phiếu số bộ đã nhận và số bộ có ghi chú bất thường. | Must | Active | TCCN 2 |
| FR-M2-01.3 | Nếu Set ID được tiếp nhận còn Cycle ID hiệu lực chưa quét sử dụng, thì hệ thống phải hủy hiệu lực Cycle ID đó với lý do Trả không sử dụng và ghi nhận vào thống kê lãng phí. | Must | Active | TCCN 3; BRU-REP-001; BRU-ID-003 |
| FR-M2-01.4 | Khi phiếu tiếp nhận được ghi sổ, hệ thống phải lưu cho mỗi bộ người, thời điểm, trạm, khoa và kết quả kiểm đếm, chuyển Set Unit sang Chờ rửa và ghi cổng T1 Đạt. | Must | Active | TCCN 4; Đầu ra; BRU-FLOW-004 |
| FR-M2-01.5 | Nếu mã quét tại T1 không tồn tại trong hệ thống, thì hệ thống phải báo Mã không hợp lệ và ghi log. | Must | Active | Xử lý lỗi; BRU-ID-006 |
| FR-M2-01.6 | Nếu một bộ được quét trùng trong cùng phiếu tiếp nhận, thì hệ thống phải cảnh báo trùng và không ghi thêm dòng. | Must | Active | Xử lý lỗi |
| FR-M2-01.7 | Nếu nhân viên khoa giao không có thẻ (người mới), thì hệ thống phải cho phép chọn khoa và ghi tên người giao bằng tay, và đánh dấu để R02 cấp thẻ sau. | Must | Active | BRU-REP-012 ngoại lệ |
| FR-M2-02 | Khi Set ID được quét tại T1, hệ thống phải chỉ chấp nhận tiếp nhận nếu Set Unit đang ở trạng thái Mới tạo, Tại khoa hoặc Chờ tiếp nhận (và Đã sử dụng nếu hệ thống thực sự tạo trạng thái này). | Must | Active | UC-05; SCR-05, SCR-34; API-M2-01, API-M1-06; BRU-FLOW-002, BRU-FLOW-003; phụ thuộc FR-M2-01, FR-M2-23, FR-M4-03. Nguồn: BR-M2 |
| FR-M2-02.1 | Nếu Set Unit được quét tại T1 ở trạng thái khác Tại khoa/Đã sử dụng, thì hệ thống phải từ chối tiếp nhận, hiển thị lý do và trạm hiện tại của bộ, và ghi audit kèm người quét. | Must | Active | TCCN 2; Xử lý lỗi |
| FR-M2-02.2 | Khi R02 chọn tiếp nhận cưỡng bức một bộ bị từ chối, hệ thống phải yêu cầu lý do, cho phép tiếp nhận và tự tạo NC. | Must | Active | TCCN 3 |
| FR-M2-23 | Khi mã bộ được quét tại T1, hệ thống phải hiển thị danh sách từng loại dụng cụ trong bộ theo đúng thứ tự BOM phiên bản áp dụng kèm tên, số lượng, ảnh chụp thực tế từng dụng cụ (DT-INSTR) và ảnh bộ đã sắp xếp (DT-SETTYPE), với ô tick từng dòng, nút Xác nhận tất cả và ô Ghi chú bất thường (văn bản tự do, ảnh tùy chọn). | Must | Active | UC-05; SCR-05, SCR-34; API-M2-01, API-M1-06; BRU-REP-012; phụ thuộc FR-M2-01, FR-M2-02. Nguồn: BR-M2 |
| FR-M2-23.1 | Khi người nhận bấm Xác nhận tất cả, hệ thống phải đánh dấu đã xác nhận mọi dòng BOM trong một chạm. | Must | Active | TCCN 1 |
| FR-M2-23.2 | Khi người nhận ghi bất thường (thiếu, hỏng, vật lạ, sắc nhọn), hệ thống phải chỉ yêu cầu nội dung ghi chú (kèm ảnh tùy chọn), không yêu cầu nhập số lượng thực nhận, và không lưu dữ liệu số lượng thực nhận ở bước này. | Must | Active | TCCN 2; Đầu ra; BRU-REP-012 |
| FR-M2-23.3 | Khi bộ có ghi chú bất thường được xác nhận, hệ thống phải gắn cờ Cần xem xét cho bộ, in ghi chú kèm phiếu tiếp nhận và hiển thị ghi chú màu đỏ tại trạm T3 để kiểm tra chi tiết, ghi hỏng/thất lạc và tạo NC tại T3. | Must | Active | TCCN 2; BRU-REP-012 |
| FR-M2-23.4 | Khi người nhận bấm Xác nhận bộ, hệ thống phải chuyển Set Unit sang Chờ rửa và lưu dòng xác nhận thành phần (dòng, đã xác nhận, ghi chú) gắn phiếu. | Must | Active | TCCN 3 |
| FR-M2-23.5 | Trong khi phiếu tiếp nhận chưa được ghi sổ, hệ thống phải cho phép sửa xác nhận và ghi chú của các bộ trong phiếu. | Must | Active | TCCN 3 |
| FR-M2-23.6 | Nếu còn dòng BOM chưa tick và không có ghi chú khi người nhận bấm Xác nhận bộ, thì hệ thống phải nhắc trước khi cho xác nhận. | Must | Active | TCCN 3 |
| FR-M2-23.7 | Nếu dụng cụ hoặc loại bộ chưa có ảnh chụp thực tế, thì hệ thống phải hiển thị khung Chưa có ảnh và cảnh báo thiếu ảnh danh mục (ảnh phải tải lên tại Dụng cụ UC-01 và Loại bộ UC-02). | Must | Active | Xử lý lỗi |
| FR-M2-03 | Khi người vận hành T2 quét QR máy rửa khử khuẩn, chọn chương trình thuộc máy, chọn hóa chất theo lô/hạn, quét nối tiếp Set ID từng bộ đưa vào máy rồi thực hiện Hoàn thành nạp (quét mã HOÀN-THÀNH hoặc bấm nút), hệ thống phải tự sinh mã lô rửa định dạng LR-YYMMDD-NN chứa toàn bộ bộ dụng cụ, máy, chương trình, hóa chất, thời gian, người vận hành, in nhãn QR lô và đặt lô ở trạng thái Đang chạy. | Must | Active | UC-06; SCR-06; API-M2-02, API-M2-03, API-M2-17; BRU-FLOW-002/003/004, BRU-REP-002, BRU-REP-015, BRU-REP-016; phụ thuộc FR-M2-24, FR-M2-25, FR-M2-04, FR-M4-03. Nguồn: BR-M2 |
| FR-M2-03.1 | Trong khi chưa quét QR máy rửa, hệ thống phải khóa ô quét bộ tại T2. | Must | Active | TCCN 1; BRU-REP-016 |
| FR-M2-03.2 | Hệ thống phải không cho nhập tay mã lô rửa và chỉ sinh mã lô tại thời điểm Hoàn thành nạp. | Must | Active | TCCN 2; BRU-REP-016 |
| FR-M2-03.3 | Khi mã lô rửa được quét, hệ thống phải hiển thị đủ danh sách bộ, máy, chương trình, hóa chất, người và giờ của lô. | Must | Active | TCCN 2 |
| FR-M2-03.4 | Khi chọn máy và chương trình cho lô rửa, hệ thống phải chỉ cho chọn máy ở trạng thái Sẵn sàng và chương trình thuộc máy đó. | Must | Active | TCCN 3; liên kết FR-M5-06 |
| FR-M2-03.5 | Khi chọn hóa chất cho lô rửa, hệ thống phải gợi ý lô hóa chất theo FEFO và chặn lô đã hết hạn. | Must | Active | TCCN 3; BRU-INV-001 |
| FR-M2-03.6 | Nếu Set ID quét vào lô rửa chưa qua cổng T1 (chưa kiểm đếm tiếp nhận) hoặc đang thuộc lô rửa khác, thì hệ thống phải từ chối và ghi audit. | Must | Active | TCCN 4; Xử lý lỗi; BRU-FLOW-004 |
| FR-M2-24 | Khi nhận dữ liệu chu trình (tham số, biểu đồ, bản in, cảnh báo, kết quả test) của máy rửa khử khuẩn hoặc máy tiệt khuẩn, hệ thống phải đính dữ liệu vào đúng mã lô/mã mẻ (không lưu theo bộ) kèm nguồn dữ liệu — Tự động qua station agent (CSV/API) hoặc Nhập tay có xác nhận (FR-M2-10) — và người xác nhận, thời điểm. | Must | Active | UC-06; SCR-06; API-M2-02, API-M2-03, API-M2-17; BRU-REP-015, BRU-REP-016, BRU-FLOW-004; phụ thuộc FR-M2-03, FR-M2-25, FR-M2-04. Nguồn: BR-M2; xem A-12: FEAT-021 chỉ có nguồn Nhập tay có xác nhận, nguồn Tự động qua agent thuộc FEAT-024 |
| FR-M2-24.1 | Khi tạo lô rửa hoặc mẻ tiệt khuẩn, hệ thống phải sinh mã lô/mã mẻ ngay khi Hoàn thành nạp, in nhãn mẻ có QR và gắn mã mẻ cho mọi bộ/gói quét vào. | Must | Active | BRU-REP-015 |
| FR-M2-24.2 | Khi mã mẻ được quét, hệ thống phải mở hồ sơ mẻ hiển thị danh sách bộ/gói, chỉ thị và dữ liệu máy kèm nguồn dữ liệu; hồ sơ bộ/gói phải tham chiếu mã mẻ để truy xuất. | Must | Active | TCCN 1; Đầu ra |
| FR-M2-24.3 | Trong khi mẻ chưa có dữ liệu chu trình ở cả hai nguồn (kể cả nhập tay chưa tick xác nhận), hệ thống phải không cho kết luận Đạt và khóa nút Đóng lô/Giải phóng. | Must | Active | TCCN 2; BRU-REP-015 |
| FR-M2-24.4 | Khi có cảnh báo máy trong lúc chạy (tự động hoặc do người vận hành ghi nhận), hệ thống phải đính cảnh báo vào mẻ và hiển thị cảnh báo đó tại màn giải phóng. | Must | Active | TCCN 3 |
| FR-M2-24.5 | Nếu máy không kết nối và không có bản in (máy cũ), thì hệ thống phải cho nhập tay tối thiểu chương trình + giờ bắt đầu/kết thúc có xác nhận và yêu cầu R02 xác nhận thêm khi giải phóng. | Must | Active | Xử lý lỗi; BRU-REP-015 ngoại lệ |
| FR-M2-25 | Khi bộ/gói được quét tại trạm T2–T6 trong một chu trình, hệ thống phải kiểm tra kết quả bước liền trước của chính bộ đó trong chu trình hiện tại (DT-STEPGATE): T2 cần T1 đã kiểm đếm; T3 cần lô rửa Đạt; T4 cần lắp ráp Đạt; T5 cần đóng gói Đạt (đủ dụng cụ, chỉ thị, bảo dưỡng); T6 cần mẻ Đã giải phóng Đạt. | Must | Active | UC-06; SCR-06; API-M2-02, API-M2-03, API-M2-17; BRU-FLOW-004; phụ thuộc FR-M2-03, FR-M2-24, FR-M2-04. Nguồn: BR-M2 |
| FR-M2-25.1 | Nếu bước liền trước của bộ chưa Đạt khi quét tại trạm kế tiếp, thì hệ thống phải hiển thị cảnh báo đỏ toàn màn, không ghi nhận thao tác và ghi audit. | Must | Active | TCCN 1 |
| FR-M2-25.2 | Khi một bước X bị ghi Không đạt cho bộ, hệ thống phải chuyển bộ về hàng đợi Xử lý lại của bước X (rửa lại, lắp ráp lại, đóng gói lại với Cycle ID mới, tiệt khuẩn lại), giữ các bước sau ở trạng thái chưa Đạt, đếm số lần xử lý lại và lặp cho tới khi Đạt. | Must | Active | TCCN 2; Đầu ra |
| FR-M2-25.3 | Khi và chỉ khi 5 cổng T1..T5 của bộ đều Đạt trong cùng chu trình, hệ thống phải gán trạng thái Vô khuẩn cho bộ và cho phép quét vào kho T6. | Must | Active | TCCN 3 |
| FR-M2-25.4 | Khi người dùng mở hồ sơ bộ, hệ thống phải hiển thị bảng cổng 5 bước của chu trình hiện tại và số lần xử lý lại. | Must | Active | Đầu ra |
| FR-M2-25.5 | Nếu mẻ tiệt khuẩn Không đạt, thì hệ thống phải mặc định đưa các bộ trong mẻ về Xử lý lại từ T4 (gói mới, chỉ thị mới, Cycle ID mới) và cho R02 chọn đưa về T2 khi nghi ướt gói/nhiễm bẩn. | Must | Active | Xử lý lỗi; BRU-FLOW-004 ngoại lệ |
| FR-M2-04 | Khi máy rửa kết thúc và người dỡ quét QR máy rửa và QR mã lô, hệ thống phải hiển thị toàn bộ bộ trong lô và nhận một kết quả chu trình Đạt/Không đạt (kèm test làm sạch TOSI/soil test và ảnh) để ghi đồng thời cho mọi bộ trong lô: lô → Đạt/Không đạt; cổng T2 của mọi bộ → Đạt/Không đạt; bộ → Chờ lắp ráp hoặc Xử lý lại (T2). | Must | Active | UC-06; SCR-06; API-M2-02, API-M2-03, API-M2-17; BRU-REP-002, BRU-REP-016, BRU-FLOW-004; phụ thuộc FR-M2-03, FR-M2-24, FR-M2-25, FR-M4-03. Nguồn: BR-M2 |
| FR-M2-04.1 | Trong khi chưa quét đủ QR máy và QR mã lô, hệ thống phải không mở màn kết quả dỡ lô. | Must | Active | TCCN 1 |
| FR-M2-04.2 | Nếu QR máy quét khi dỡ không khớp máy của mã lô, thì hệ thống phải từ chối dỡ. | Must | Active | TCCN 1; BRU-REP-016 |
| FR-M2-04.3 | Hệ thống phải ghi kết quả lô cho mọi bộ trong lô cùng lúc và không cho ghi lẻ kết quả từng bộ. | Must | Active | TCCN 2 |
| FR-M2-04.4 | Nếu lô rửa Không đạt, thì hệ thống phải chuyển mọi Set ID trong lô về Chờ rửa/Xử lý lại (T2), không cho quét tại trạm lắp ráp và tự tạo NC. | Must | Active | TCCN 2; BRU-REP-002 |
| FR-M2-04.5 | Khi máy rửa kết nối API, hệ thống phải tự điền kết quả chu trình và chỉ yêu cầu người dỡ xác nhận dỡ; khi máy không kết nối, hệ thống phải yêu cầu chọn Đạt/Không đạt và tick xác nhận. | Must | Active | TCCN 3 |
| FR-M2-04.6 | Nếu thiếu kết quả test làm sạch hoặc thiếu dữ liệu chu trình, thì hệ thống phải không cho đóng lô. | Must | Active | Xử lý lỗi; BRU-REP-015 |
| FR-M2-04.7 | Khi máy rửa là máy hai cửa, hệ thống phải cho thao tác dỡ thực hiện tại cửa ra (khu sạch) bởi nhân viên khu đó. | Must | Active | BRU-REP-016 ngoại lệ; BRU-FLOW-001 |
| FR-M2-04.8 | Khi chương trình rửa bật bắt buộc chỉ thị và người dỡ đã quét đủ QR máy và QR mã lô, hệ thống phải chuyển lô sang Chờ đọc chỉ thị, giải phóng máy và không ghi cổng T2 của bộ nào cho đến khi có kết quả. | Must | Active | A-77 |
| FR-M2-04.9 | Nếu chỉ thị rửa thiếu vật tư, lô hoặc hạn dùng, đã hết hạn tại ngày lô bắt đầu chạy, hoặc thiếu ảnh khi chương trình bắt buộc ảnh, thì hệ thống phải không cho ghi Đạt. | Must | Active | A-77 |
| FR-M2-04.10 | Hệ thống phải ghi kết quả chỉ thị rửa theo lô gồm vật tư, lô, hạn dùng, kết quả, ảnh, người đọc, giờ đọc; kết quả Không đạt áp dụng như FR-M2-04.4; truy vết theo Set ID phải hiện các thông tin này. | Must | Active | A-77 |
| FR-M2-05 | Khi Set ID được quét tại T3, hệ thống phải hiển thị BOM phiên bản áp dụng kèm ảnh chụp thực tế từng dụng cụ, ảnh bộ đã sắp xếp hoàn chỉnh và ghi chú bất thường từ tiếp nhận (cờ Cần xem xét), cho phép tick/nhập số lượng thực tế từng dòng, đánh dấu hỏng, thay dụng cụ từ kho dự phòng, đính ảnh, và lập phiếu lắp ráp cùng phiếu kiểm đếm in kèm gói. | Must | Active | UC-07; SCR-07; API-M2-04; BRU-FLOW-002/003/004, BRU-REP-003; phụ thuộc FR-M2-06, FR-M4-03. Nguồn: BR-M2 |
| FR-M2-05.1 | Khi số lượng thực tế được nhập, hệ thống phải hiển thị đủ/thiếu/thừa từng dòng bằng màu và đối chiếu với ghi chú kiểm đếm tại tiếp nhận. | Must | Active | TCCN 1 |
| FR-M2-05.2 | Khi dụng cụ được đánh dấu hỏng và thay từ kho dự phòng, hệ thống phải ghi dụng cụ thay thế vào bộ và chuyển dụng cụ hỏng sang Sửa chữa/Thanh lý. | Must | Active | TCCN 2 |
| FR-M2-05.3 | Khi số chu trình còn lại của bộ hoặc của một dụng cụ trong bộ ≤ ngưỡng cảnh báo sớm (mặc định 10% hoặc 5 lần), hệ thống phải hiển thị cảnh báo màu cam tại T3. | Must | Active | TCCN 3; BRU-PAR-003 |
| FR-M2-05.4 | Nếu bộ quét tại T3 chưa qua lô rửa Đạt, thì hệ thống phải chặn thao tác. | Must | Active | Xử lý lỗi; BRU-FLOW-004 |
| FR-M2-05.5 | Khi Set ID được quét tại T3, hệ thống phải hiển thị mọi dòng ở trạng thái Chưa đếm với số lượng trống, và phải không có thao tác xác nhận tất cả dòng, trên giao diện lẫn RPC. | Must | Active | A-79; #1820 |
| FR-M2-05.6 | Nếu số lượng thực tế khác định mức mà thiếu lựa chọn Thiếu/Hỏng (khi thiếu) hoặc thiếu ghi chú, thì hệ thống phải chặn ghi dòng và chặn ghi nhận kiểm đếm. | Must | Active | A-79; #1820 |
| FR-M2-06 | Nếu kết quả kiểm đếm tại T3 có dòng thiếu (số lượng thực tế < BOM) chưa được R02 xác nhận, thì hệ thống phải khóa nút Đóng gói, hiển thị danh sách thiếu và yêu cầu bổ sung từ kho dự phòng hoặc xác nhận của R02. | Must | Active | UC-07; SCR-07; API-M2-04; BRU-REP-003; phụ thuộc FR-M2-05, FR-M4-03. Nguồn: BR-M2 |
| FR-M2-06.1 | Khi R02 xác nhận đóng gói thiếu bằng thẻ/PIN kèm lý do, hệ thống phải mở khóa đóng gói và in trên nhãn dòng THIẾU + tên dụng cụ thiếu. | Must | Active | TCCN 2; BRU-REP-003 |
| FR-M2-06.2 | Khi kiểm đếm phát hiện thiếu dụng cụ, hệ thống phải tự tạo NC loại Thiếu dụng cụ. | Must | Active | TCCN 3; liên kết FR-M2-21 |
| FR-M2-06.3 | Nếu PIN xác nhận của R02 bị nhập sai 3 lần liên tiếp, thì hệ thống phải khóa chức năng xác nhận trong 5 phút. | Must | Active | Xử lý lỗi |
| FR-M2-07 | Khi KTV khu sạch (R04) tại T4 bấm Xác nhận hoàn thành đóng gói sau khi đã tick xác nhận từng loại dụng cụ theo BOM (đối chiếu ảnh thực tế), quét lô chỉ thị hóa học đặt vào bộ và xử lý nhắc bảo dưỡng, hệ thống phải tự động (không có bước sinh mã riêng) sinh một Cycle ID mới, duy nhất, dùng một lần, gắn với bộ đó và mang Set ID, tên bộ, phiên bản BOM, ngày giờ đóng gói, người đóng gói, hạn sử dụng, phương pháp tiệt khuẩn, loại gói, lô chỉ thị; in nhãn ngay và chuyển Pack sang Đã đóng gói. | Must | Active | UC-08; SCR-08; API-M2-05, API-M2-06, API-M1-06; BRU-ID-002, BRU-ID-004, BRU-REP-009, BRU-REP-013, BRU-REP-014, BRU-REP-011, BRU-FLOW-004; phụ thuộc FR-M2-08, FR-M8-03, FR-M4-03. Nguồn: BR-M2 |
| FR-M2-07.1 | Khi nhãn Cycle ID được in, hệ thống phải mã hóa GS1 DataMatrix với (01) loại bộ, (11) ngày đóng gói, (17) hạn dùng, (21) Cycle ID; các thông tin còn lại in chữ trên nhãn và tra cứu được khi quét. | Must | Active | Đầu ra; BRU-ID-002 |
| FR-M2-07.2 | Nếu chưa tick đủ các loại dụng cụ trong BOM hoặc chưa quét lô chỉ thị hóa học (loại 5/6 theo phương pháp), thì hệ thống phải khóa Xác nhận hoàn thành đóng gói và hiển thị mục còn thiếu. | Must | Active | TCCN 1; BRU-REP-013 |
| FR-M2-07.3 | Khi Cycle ID được sinh, hệ thống phải ghi lô chỉ thị hóa học vào gói để truy xuất và trừ tiêu hao. | Must | Active | BRU-REP-013; liên kết FR-M6-03 |
| FR-M2-07.4 | Khi dụng cụ trong bộ đạt ngưỡng bảo dưỡng, hệ thống phải hiển thị nhắc kèm ảnh tại T4; xác nhận Đã tra dầu phải đặt lại bộ đếm; nếu vượt ngưỡng quá 20% mà chưa bảo dưỡng, thì hệ thống phải chặn sinh Cycle ID. | Must | Active | TCCN 2; BRU-REP-014; chi tiết FR-M1-09 |
| FR-M2-07.5 | Khi Xác nhận hoàn thành đóng gói được bấm, hệ thống phải kiểm tra cơ số tái xử lý (FR-M8-03) và quy tắc một Set ID chỉ có một Cycle ID hiệu lực trước khi sinh mã. | Must | Active | TCCN 3; BRU-ID-004, BRU-PAR-002 |
| FR-M2-07.6 | Nếu Set ID còn một Cycle ID ở trạng thái hiệu lực, thì hệ thống phải không sinh Cycle ID mới cho tới khi Cycle ID cũ được hủy hiệu lực. | Must | Active | BRU-ID-004 |
| FR-M2-07.7 | Khi Cycle ID được sinh, hệ thống phải tính hạn sử dụng = ngày đóng gói + hạn lưu nhập tay của loại gói đang áp dụng (không dùng giá trị mặc định cứng). | Must | Active | TCCN 3; BRU-REP-009; xem A-02 (D4): hạn lưu áp dụng = min(hạn loại gói, hạn ghi đè của loại bộ), snapshot vào Pack |
| FR-M2-07.8 | Khi R02 cập nhật hạn lưu của một loại gói, hệ thống phải áp dụng giá trị mới chỉ cho các gói đóng sau thời điểm sửa. | Must | Active | BRU-REP-009 ngoại lệ; xem A-09 (S7, tạm): RPC `set_pack_shelf_life` cho R02/R10/System Manager, có lý do và Audit Log |
| FR-M2-07.9 | Khi Cycle ID được quét, hệ thống phải hiển thị đủ ngày đóng gói, người đóng gói, hạn dùng, phương pháp và lô chỉ thị. | Must | Active | TCCN 3 |
| FR-M2-07.10 | Nếu bộ chưa có Cycle ID hiệu lực được quét tại T5, thì hệ thống phải từ chối đưa bộ vào mẻ tiệt khuẩn. | Must | Active | TCCN 3; BRU-ID-002 |
| FR-M2-07.11 | Nếu mất kết nối mạng tại T4, thì hệ thống phải sinh Cycle ID offline theo dải mã dành riêng cho trạm và đồng bộ khi có mạng. | Must | Active | Xử lý lỗi; liên kết FR-M9-06 |
| FR-M2-07.12 | Nếu lô chỉ thị hóa học quét vào đã hết hạn, thì hệ thống phải chặn và yêu cầu lô khác. | Must | Active | Xử lý lỗi; BRU-INV-001 |
| FR-M2-07.13 | Khi đóng gói hoặc ghi sổ lắp ráp tại trạm, hệ thống phải ghi nhân viên của phiên trạm (người quét thẻ) vào chứng từ, và nhãn gói phải in tên nhân viên đó. | Must | Active | A-81; #1841 |
| FR-M2-08 | Khi in nhãn cho gói tại T4, hệ thống phải chọn loại nhãn, máy in/cuộn nhãn theo phương pháp tiệt khuẩn của gói — gói Hấp 121/134 in trên nhãn hấp hơi nước nhiệt độ cao (VT-NHAN-HAP), gói Plasma H2O2 in trên nhãn plasma (VT-NHAN-PLASMA) — và in nhãn (ZPL/TSPL) gồm Set ID, Cycle ID, tên bộ, khoa, người đóng gói, ngày, hạn, phương pháp và dòng cảnh báo. | Must | Active | UC-08; SCR-08; API-M2-05, API-M2-06, API-M1-06; BRU-REP-011, BRU-ID-005; phụ thuộc FR-M2-07, FR-M4-03. Nguồn: BR-M2 |
| FR-M2-08.1 | Nếu phương pháp của gói không khớp loại nhãn đang nạp trên máy in/cuộn, hoặc trạm không có cuộn nhãn đúng loại, thì hệ thống phải chặn in và hiển thị lý do. | Must | Active | TCCN 1; BRU-REP-011 |
| FR-M2-08.2 | Khi khai báo máy in/cuộn nhãn tại trạm, hệ thống phải lưu loại nhãn đang nạp cho từng máy in/cuộn và cho phép một trạm có 2 máy in hoặc 1 máy in đổi cuộn có xác nhận. | Must | Active | TCCN 2 |
| FR-M2-08.3 | Khi nhãn được in, hệ thống phải trừ tiêu hao và tính giá thành theo đúng loại nhãn đã dùng. | Must | Active | Đầu ra; BRU-REP-011 |
| FR-M2-08.4 | Khi R10 chỉnh mẫu nhãn theo phương pháp, hệ thống phải cho cấu hình mẫu nhãn mà không cần thay đổi mã nguồn. | Must | Active | TCCN 3 |
| FR-M2-08.5 | Khi nhãn hỏng trong quá trình in và người dùng yêu cầu in lại trong vòng 10 phút kể từ khi sinh Cycle ID, hệ thống phải cho in lại cùng Cycle ID và yêu cầu ghi lý do. | Must | Active | TCCN 3; BRU-ID-005; 10 phút tính từ lúc tạo Pack (giờ server), không từ `packed_at` (A-02, ruling Task 8) |
| FR-M2-08.6 | Nếu yêu cầu in lại nhãn vượt quá 10 phút kể từ khi sinh Cycle ID, thì hệ thống phải yêu cầu hủy Cycle ID cũ và sinh Cycle ID mới. | Must | Active | BRU-ID-005 |
| FR-M2-08.7 | Hệ thống phải dùng vật liệu nhãn và mã hóa sao cho nhãn quét được sau chu trình hấp 134°C và sau chu trình plasma (kiểm chứng tại UAT). | Must | Active | TCCN 3 |
| FR-M2-08.8 | Nếu máy in đúng loại nhãn bị lỗi, thì hệ thống phải giữ Cycle ID, đưa lệnh in vào hàng đợi và không cho in tạm trên loại nhãn khác. | Must | Active | Xử lý lỗi |
| FR-M2-08.9 | Khi gói EO được cấu hình dùng nhãn plasma, hệ thống phải yêu cầu R02 xác nhận IFU nhãn cho phép tại thời điểm cấu hình. | Must | Active | BRU-REP-011 ngoại lệ |
| FR-M2-09 | Khi KTV tiệt khuẩn (R05) quét QR máy tiệt khuẩn, chọn chương trình, quét nối tiếp Cycle ID của từng gói đưa vào máy rồi thực hiện Hoàn thành nạp, hệ thống phải tự sinh mã mẻ định dạng ME-YYMMDD-NN chứa toàn bộ gói/bộ, thiết bị, chương trình, người vận hành; in nhãn QR mẻ; chuyển Load sang Đang chạy và Pack sang Trong mẻ. [A-83] Danh sách chọn ở Nạp máy không có chương trình test; chương trình test và chương trình không khai loại gói không nhận gói. [A-86] Máy còn mẻ chưa dỡ (kể cả đã có dữ liệu chu trình) không nhận mẻ mới. | Must | Active | UC-09; SCR-09, SCR-35; API-M2-07, API-M2-08, API-M2-17; BRU-REP-004, BRU-REP-015, BRU-REP-016, BRU-FLOW-004; phụ thuộc FR-M2-10, FR-M4-03. Nguồn: BR-M2 |
| FR-M2-09.1 | Trong khi chưa quét QR máy tiệt khuẩn, hệ thống phải khóa ô quét gói; hệ thống phải không cho nhập tay mã mẻ và chỉ sinh mã mẻ khi Hoàn thành nạp. | Must | Active | TCCN 1; BRU-REP-016 |
| FR-M2-09.2 | Khi mã mẻ được quét, hệ thống phải hiển thị danh sách gói/bộ, chương trình và chỉ thị của mẻ. | Must | Active | TCCN 1 |
| FR-M2-09.3 | Khi chọn máy tiệt khuẩn cho mẻ, hệ thống phải chỉ cho chọn máy ở trạng thái Sẵn sàng, có test ngày Đạt (nếu thuộc diện bắt buộc, A-70) và kiểm định/hiệu chuẩn còn hạn. | Must | Active | TCCN 2; BRU-EQP-001, BRU-EQP-002; liên kết FR-M5-06 |
| FR-M2-09.4 | Nếu gói quét vào mẻ có phương pháp tiệt khuẩn không tương thích với chương trình máy (gói nhiệt độ thấp vào máy hấp hoặc ngược lại), hoặc bộ chưa qua cổng T4 Đạt, thì hệ thống phải từ chối gói kèm lý do. | Must | Active | TCCN 2; BRU-REP-004, BRU-FLOW-004 |
| FR-M2-09.5 | Nếu số gói trong mẻ vượt dung tích máy cấu hình, thì hệ thống phải từ chối quét thêm gói. | Must | Active | TCCN 3 |
| FR-M2-09.6 | Nếu gói quét vào đang thuộc mẻ khác, thì hệ thống phải từ chối. | Must | Active | Xử lý lỗi |
| FR-M2-10 | Khi người vận hành nhập tay dữ liệu chu trình cho mã lô/mã mẻ của máy không kết nối, hệ thống phải hiển thị mẫu nhập theo chương trình đã chọn (máy hấp: nhiệt độ, áp suất, thời gian pha; máy rửa: nhiệt độ, A0/thời gian, nồng độ hóa chất; plasma: chu trình, kết quả máy), cho đính ảnh bản in/biểu đồ và ghi nhận cảnh báo máy quan sát được, yêu cầu tick xác nhận đúng với máy và quét thẻ người vận hành, rồi đính dữ liệu vào mã mẻ với nguồn Nhập tay, người xác nhận và thời điểm. | Must | Active | UC-09; SCR-09, SCR-35; API-M2-07, API-M2-08, API-M2-17; BRU-REP-015; phụ thuộc FR-M2-09. Nguồn: BR-M2 |
| FR-M2-10.1 | Nếu thiếu tham số bắt buộc của chương trình hoặc chưa tick xác nhận, thì hệ thống phải không lưu dữ liệu nhập tay. | Must | Active | TCCN 1 |
| FR-M2-10.2 | Khi thiết bị được khai báo là có bản in, hệ thống phải bắt buộc đính ảnh bản in/biểu đồ; khi thiết bị không có bản in, hệ thống phải không bắt buộc ảnh. | Must | Active | TCCN 2 |
| FR-M2-10.3 | Nếu tham số nhập tay nằm ngoài dải của chương trình, thì hệ thống phải cảnh báo đỏ, vẫn lưu, đánh dấu mẻ Cần xem xét và chặn kết luận Đạt; người vận hành sửa dữ liệu nếu nhập sai hoặc kết luận Không đạt (A-89 sửa). Khi máy không đẩy dữ liệu, form điền sẵn theo chương trình, người vận hành kiểm tra, sửa và xác nhận; hệ thống lưu giá trị mặc định và trường đã sửa. | Must | Active | TCCN 3 |
| FR-M2-10.4 | Nếu máy kết nối được nhưng mất dữ liệu chu trình, thì hệ thống phải cho phép chuyển sang nhập tay có xác nhận và yêu cầu ghi lý do. | Must | Active | Xử lý lỗi |
| FR-M2-11 | Khi máy tiệt khuẩn kết thúc và người dỡ quét QR máy và QR mã mẻ, hệ thống phải liệt kê toàn bộ gói/bộ trong mẻ, nhận một kết quả chu trình Đạt/Không đạt (nhập tay có xác nhận hoặc tự động qua API máy) ghi đồng thời cho mọi gói, nhận kết quả Bowie-Dick (ngày), chỉ thị loại 5/6 (từng gói hoặc theo mẻ), chỉ thị sinh học (lô, tủ ủ, giờ đọc, người đọc) và cập nhật Load → Đã giải phóng / Cách ly / Không đạt cùng cổng T5 của mọi bộ. [A-86] Ghi người dỡ theo nhân viên của phiên trạm; màn dỡ hiện thời lượng so với chuẩn. | Must | Active | UC-10; SCR-10; API-M2-09, API-M2-10; BRU-REP-005, BRU-REP-006, BRU-REP-015, BRU-REP-016, BRU-FLOW-004; phụ thuộc FR-M2-12. Nguồn: BR-M2; A-70: máy ngoài diện test hằng ngày thì Bowie-Dick không bắt buộc, Không đạt vẫn chặn giải phóng |
| FR-M2-11.1 | Trong khi chưa quét đủ QR máy và QR mã mẻ, hệ thống phải không mở màn dỡ mẻ. | Must | Active | TCCN 1 |
| FR-M2-11.2 | Nếu QR máy quét khi dỡ không khớp máy của mã mẻ, thì hệ thống phải từ chối dỡ. | Must | Active | TCCN 1; BRU-REP-016 |
| FR-M2-11.3 | Khi máy tiệt khuẩn kết nối API, hệ thống phải tự điền kết quả chu trình và yêu cầu người dỡ xác nhận; khi máy không kết nối, hệ thống phải yêu cầu chọn Đạt/Không đạt và tick xác nhận. | Must | Active | TCCN 2 |
| FR-M2-11.4 | Khi R02 xác thực bằng thẻ/PIN và tham số chu trình Đạt, chỉ thị hóa học Đạt, hệ thống phải cho giải phóng mẻ; hệ thống phải không cho vai trò khác giải phóng mẻ. | Must | Active | TCCN 3; BRU-REP-005 |
| FR-M2-11.5 | Nếu thiếu kết quả chỉ thị hóa học của mẻ, thì hệ thống phải không cho giải phóng. | Must | Active | TCCN 4 |
| FR-M2-11.6 | Trong khi mẻ chưa được giải phóng, hệ thống phải không cho nhập các gói của mẻ vào kho vô khuẩn T6. | Must | Active | Mô tả; BRU-REP-005 |
| FR-M2-11.7 | Khi kết quả BI được đọc sau khi mẻ đã giải phóng, hệ thống phải cho cập nhật kết quả BI vào mẻ; nếu BI dương tính, thì hệ thống phải kích hoạt lệnh thu hồi (FR-M2-20). | Must | Active | TCCN 5; BRU-REP-007 |
| FR-M2-11.8 | Khi R01 giải phóng khẩn cấp một mẻ (tham số Đạt, chỉ thị hóa học Đạt), hệ thống phải yêu cầu lý do, ghi audit và phát cảnh báo. | Must | Active | Xử lý lỗi; BRU-REP-005 ngoại lệ |
| FR-M2-11.9 | Khi máy tiệt khuẩn là máy hai cửa, hệ thống phải cho thao tác dỡ thực hiện tại cửa ra (khu vô khuẩn) bởi nhân viên khu đó. | Must | Active | BRU-REP-016 ngoại lệ |
| FR-M2-12 | Trong khi mẻ chứa gói cấy ghép hoặc chương trình yêu cầu BI chưa có kết quả BI âm tính, hệ thống phải giữ mẻ ở trạng thái Cách ly chờ BI và không cho cấp phát các gói của mẻ. | Must | Active | UC-10; SCR-10; API-M2-09, API-M2-10; BRU-REP-006, BRU-REP-007; phụ thuộc FR-M2-11. Nguồn: BR-M2 |
| FR-M2-12.1 | Khi R01 phê duyệt cấp gói cấy ghép trước kết quả BI (ca mổ không thể hoãn), hệ thống phải yêu cầu lý do, ghi audit và theo dõi kết quả BI của mẻ đó. | Must | Active | TCCN 1; BRU-REP-006 ngoại lệ |
| FR-M2-12.2 | Nếu mẻ bị kết luận Không đạt, thì hệ thống phải chuyển mọi gói chưa dùng của mẻ sang Hết hiệu lực và Tái xử lý lại, đưa mọi gói đã cấp/đã dùng vào lệnh thu hồi và tự tạo NC loại Mẻ không đạt. | Must | Active | TCCN 2, 3; BRU-REP-007; BRU-ID-003 |
| FR-M2-12.3 | Nếu BI dương tính sau khi gói của mẻ đã được dùng, thì hệ thống phải gửi thông báo tới R01 và khoa liên quan trong vòng 1 phút. | Must | Active | Xử lý lỗi |
| FR-M2-13 | Khi KTV kho vô khuẩn (R06) quét Cycle ID của gói và quét mã vị trí kệ/ngăn, hệ thống phải chuyển Pack sang Trong kho vô khuẩn và cập nhật tồn theo vị trí. | Must | Active | UC-11; SCR-11; API-M2-11, API-M2-17; BRU-REP-008, BRU-FLOW-004; phụ thuộc FR-M2-14. Nguồn: BR-M2 |
| FR-M2-13.1 | Nếu gói quét vào kho chưa thuộc mẻ Đã giải phóng Đạt, thì hệ thống phải từ chối nhập kho. | Must | Active | TCCN 1; BRU-FLOW-004 |
| FR-M2-13.2 | Hệ thống phải hiển thị trên dashboard kho danh sách gói sắp hết hạn trong 7 ngày tới. | Must | Active | TCCN 2 |
| FR-M2-13.3 | Khi người dùng yêu cầu lấy gói theo loại bộ để cấp phát, hệ thống phải gợi ý gói có hạn sớm nhất (FEFO). | Must | Active | TCCN 3; BRU-REP-008 |
| FR-M2-13.4 | Nếu người dùng chọn gói có hạn xa hơn khi còn gói hạn gần cùng loại, thì hệ thống phải cảnh báo; khi khoa yêu cầu theo Set ID cụ thể, hệ thống phải chấp nhận kèm ghi chú. | Must | Active | BRU-REP-008 và ngoại lệ |
| FR-M2-13.5 | Nếu mã vị trí quét không tồn tại, thì hệ thống phải từ chối. | Must | Active | Xử lý lỗi |
| FR-M2-14 | Khi gói trong kho vô khuẩn quá hạn sử dụng (lúc 00:00 ngày sau hạn) hoặc được quét báo rách/mở kèm lý do, hệ thống phải chuyển Pack sang Hết hiệu lực và Set Unit sang Chờ tiếp nhận để đưa về khu bẩn tái xử lý. | Must | Active | UC-11; SCR-11; API-M2-11, API-M2-17; BRU-ID-003; phụ thuộc FR-M2-13. Nguồn: BR-M2 |
| FR-M2-14.1 | Trong khi gói ở trạng thái Hết hiệu lực, hệ thống phải không cho quét gói tại trạm cấp phát. | Must | Active | TCCN 2 |
| FR-M2-14.2 | Khi người dùng yêu cầu, hệ thống phải in được danh sách gói cần đưa về khu bẩn. | Must | Active | TCCN 3 |
| FR-M2-14.3 | Khi R02 gia hạn hạn lưu cho gói còn nguyên vẹn, hệ thống phải chỉ cho gia hạn trong phạm vi IFU bao gói, yêu cầu lý do và ghi audit; hệ thống phải không cho vai trò khác gia hạn. | Must | Active | Xử lý lỗi; BRU-ID-003 ngoại lệ |
| FR-M2-15 | Khi KTV cấp phát (R06) quét các gói và quét thẻ người nhận của khoa, hệ thống phải lập một phiếu cấp phát nhiều gói cho một khoa, thu chữ ký điện tử (thẻ hoặc chữ ký cảm ứng), chuyển Pack sang Đã cấp phát, trừ tồn kho vô khuẩn và cộng tồn khoa. | Must | Active | UC-12; SCR-12, SCR-36; API-M2-12; BRU-FLOW-002/003, BRU-PAR-005; phụ thuộc FR-M2-16. Nguồn: BR-M2 |
| FR-M2-15.1 | Khi phiếu cấp phát được ký, hệ thống phải cho in phiếu và, khi được cấu hình, gửi phiếu qua email cho khoa. | Must | Active | TCCN 3 |
| FR-M2-15.2 | Nếu người nhận quét thẻ không thuộc khoa nhận, thì hệ thống phải cảnh báo. | Must | Active | Xử lý lỗi |
| FR-M2-16 | Khi cấp phát cho khoa, hệ thống phải so sánh tồn khoa hiện tại + số gói cấp với cơ số tối đa và tối thiểu của khoa cho loại bộ đó. | Must | Active | UC-12; SCR-12, SCR-36; API-M2-12; BRU-PAR-005; phụ thuộc FR-M2-15. Nguồn: BR-M2 |
| FR-M2-16.1 | Nếu tồn khoa + số cấp > cơ số tối đa, thì hệ thống phải cảnh báo và yêu cầu R02 phê duyệt ngay tại màn hình cấp phát. | Must | Active | TCCN 1; BRU-PAR-005 |
| FR-M2-16.2 | Nếu tồn khoa < cơ số tối thiểu, thì hệ thống phải gợi ý cấp bổ sung. | Must | Active | TCCN 2; BRU-PAR-005 |
| FR-M2-16.3 | Khi khoa cấp cứu được cấu hình cho phép vượt cơ số và mức vượt ≤ 20%, hệ thống phải cho phép cấp không cần phê duyệt và ghi log. | Must | Active | TCCN 3; BRU-PAR-005 ngoại lệ |
| FR-M2-16.4 | Nếu khoa chưa có cơ số cấu hình, thì hệ thống phải cho phép cấp và cảnh báo thiếu cấu hình. | Must | Active | Xử lý lỗi |
| FR-M2-17 | Khi nhân viên khoa (R08) quét Cycle ID khi mở gói dùng cho bệnh nhân và nhập mã bệnh nhân, mã ca mổ, phẫu thuật viên, phòng, hệ thống phải tạo Usage Record, chuyển Pack sang Đã sử dụng (Cycle ID hết hiệu lực) và Set Unit sang Chờ tiếp nhận. | Must | Active | UC-13; SCR-13, SCR-37; API-M2-13; BRU-ID-003, BRU-REP-010; phụ thuộc FR-M2-18. Nguồn: BR-M2 |
| FR-M2-17.1 | Khi lưu mã bệnh nhân, hệ thống phải lưu dạng mã hóa và hiển thị ẩn 4 ký tự giữa. | Must | Active | TCCN 1 |
| FR-M2-17.2 | Khi ca là cấp cứu, hệ thống phải cho phép nhập mã bệnh nhân trong vòng 24 giờ sau khi quét sử dụng. | Must | Active | TCCN 2; BRU-REP-010 ngoại lệ |
| FR-M2-17.3 | Hệ thống phải cho phép gắn nhiều gói vào một mã ca mổ. | Must | Active | TCCN 3 |
| FR-M2-17.4 | Nếu gói được quét sử dụng thuộc khoa khác với khoa của người quét, thì hệ thống phải cảnh báo và cho tiếp tục khi có lý do. | Must | Active | Xử lý lỗi |
| FR-M2-17.5 | Khi gói được trả về T1 mà chưa quét sử dụng, hệ thống phải tính gói là Trả không sử dụng. | Must | Active | BRU-REP-010; liên kết FR-M2-01.3 |
| FR-M2-18 | Nếu Cycle ID được quét tại trạm sử dụng ở trạng thái Đã dùng, Quá hạn, Thu hồi hoặc Hết hiệu lực (gồm thuộc mẻ không đạt), thì hệ thống phải chặn 100% và hiển thị lý do kèm ngày phát sinh trạng thái. | Must | Active | UC-13; SCR-13, SCR-37; API-M2-13; BRU-ID-003; phụ thuộc FR-M2-17, FR-M8-03. Nguồn: BR-M2 |
| FR-M2-18.1 | Nếu Cycle ID được quét thuộc bộ đã vượt cơ số (kể cả khi ghi đè đã hết hạn), thì hệ thống phải chặn. | Must | Active | TCCN 2; BRU-PAR-002 |
| FR-M2-18.2 | Khi một lần quét bị chặn, hệ thống phải ghi audit lần quét đó. | Must | Active | TCCN 3 |
| FR-M2-18.3 | Hệ thống phải không cung cấp ngoại lệ hay ghi đè nào tại trạm sử dụng để kích hoạt lại Cycle ID hết hiệu lực. | Must | Active | Xử lý lỗi; BRU-ID-003 (không kích hoạt lại) |
| FR-M2-19 | Khi người dùng tra cứu theo mã bệnh nhân, Set ID, Cycle ID, Load ID, máy, nhân viên hoặc khoảng ngày, hệ thống phải trả về chuỗi sự kiện đầy đủ theo thời gian theo hai chiều (bệnh nhân → Cycle ID → Set ID → mẻ → máy → người, và ngược lại) và cho xuất PDF. | Must | Active | UC-14; SCR-14; API-M2-14, API-M2-15; BRU-REP-007; phụ thuộc FR-M2-20. Nguồn: BR-M2 |
| FR-M2-19.1 | Khi tra cứu từ mã bệnh nhân, hệ thống phải trả về mọi gói và mẻ liên quan trong dưới 5 giây. | Must | Active | TCCN 1 |
| FR-M2-19.2 | Khi tra cứu từ Load ID, hệ thống phải trả về mọi gói trong mẻ kèm trạng thái và bệnh nhân (nếu đã dùng). | Must | Active | TCCN 2 |
| FR-M2-19.3 | Khi hiển thị chuỗi sự kiện, hệ thống phải hiển thị cho mỗi sự kiện người – thời điểm – trạm – thiết bị. | Must | Active | TCCN 3 |
| FR-M2-19.4 | Nếu tra cứu không có kết quả, thì hệ thống phải thông báo và gợi ý tiêu chí tìm khác. | Must | Active | Xử lý lỗi |
| FR-M2-20 | Khi mẻ bị kết luận Không đạt hoặc BI dương tính sau khi đã cấp phát, hoặc khi R01/R02 lập lệnh thu hồi theo Load ID hoặc lô vật tư/BI kèm lý do, hệ thống phải tự lập lệnh thu hồi gồm mọi Cycle ID bị ảnh hưởng (không nhập tay), hiển thị trạng thái từng gói và gửi thông báo tới khoa liên quan và R01. | Must | Active | UC-14; SCR-14; API-M2-14, API-M2-15; BRU-REP-007; phụ thuộc FR-M2-19. Nguồn: BR-M2 |
| FR-M2-20.1 | Trong khi lệnh thu hồi đang mở, hệ thống phải hiển thị trạng thái từng gói: Trong kho (khóa, không cấp phát), Đã cấp (chờ thu), Đã dùng (báo bác sĩ). | Must | Active | TCCN 2 |
| FR-M2-20.2 | Nếu chưa đủ 100% gói trong lệnh được xác nhận xử lý, thì hệ thống phải không cho đóng lệnh thu hồi. | Must | Active | TCCN 3 |
| FR-M2-20.3 | Khi lệnh thu hồi chứa gói đã dùng, hệ thống phải hiển thị cho R01 tên bệnh nhân ẩn một phần. | Must | Active | Xử lý lỗi |
| FR-M2-21 | Khi người dùng ghi nhận sự cố/NC với loại (thiếu dụng cụ, mẻ không đạt, gói hỏng, sự cố máy, khác), mức độ, liên kết đối tượng, ảnh và mô tả, hệ thống phải tạo Incident ở trạng thái Mới và thông báo R02. | Must | Active | UC-15; SCR-15; API-M2-16; phụ thuộc FR-M2-22. Nguồn: BR-M2 |
| FR-M2-21.1 | Khi lô rửa Không đạt, mẻ Không đạt hoặc kiểm đếm thiếu dụng cụ được ghi nhận, hệ thống phải tự tạo Incident tương ứng. | Must | Active | TCCN 1 |
| FR-M2-21.2 | Nếu Incident không liên kết với ít nhất một đối tượng (mẻ/máy/bộ/người), thì hệ thống phải không cho lưu. | Must | Active | TCCN 2 |
| FR-M2-21.3 | Khi Incident có mức Cao được tạo, hệ thống phải thông báo R01 ngay. | Must | Active | TCCN 3 |
| FR-M2-21.4 | Hệ thống phải không cho xóa Incident; khi người dùng hủy Incident, hệ thống phải yêu cầu lý do. | Must | Active | Xử lý lỗi |
| FR-M2-22 | Khi người phụ trách nhập nguyên nhân gốc, hành động khắc phục/phòng ngừa, người phụ trách, hạn và kết quả kiểm tra, hệ thống phải chuyển Incident qua các trạng thái Phân tích → CAPA → Kiểm tra → Đóng. | Should | Active | UC-15; SCR-15; API-M2-16; phụ thuộc FR-M2-21. Nguồn: BR-M2 |
| FR-M2-22.1 | Nếu CAPA quá hạn, thì hệ thống phải nhắc người phụ trách và R02. | Should | Active | TCCN 1 |
| FR-M2-22.2 | Khi R01 hoặc R02 đóng Incident, hệ thống phải chỉ cho đóng sau bước Kiểm tra hiệu quả; hệ thống phải không cho vai trò khác đóng. | Should | Active | TCCN 2 |
| FR-M2-22.3 | Khi người dùng yêu cầu, hệ thống phải xuất báo cáo NC theo tháng, loại và thiết bị. | Should | Active | TCCN 3 |
| FR-M2-22.4 | Nếu Incident chưa có người phụ trách, thì hệ thống phải không cho chuyển sang trạng thái CAPA. | Should | Active | Xử lý lỗi |

#### 3.1.3 M3 — Quản lý đồ vải

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M3-01 | Khi nhân viên đồ vải (R07) nhập lượt thu gom với khoa, ngày giờ, người giao, người nhận và từng dòng loại đồ vải, số chiếc, cân nặng (kg), cờ nhiễm/không nhiễm, hệ thống phải ghi sổ Linen Collection. | Must | Active | UC-16; SCR-16; API-M3-01; BRU-LIN-001; phụ thuộc FR-M3-02. Nguồn: BR-M3 |
| FR-M3-01.1 | Nếu một giao dịch đồ vải thiếu khoa, loại đồ vải, số chiếc hoặc cân nặng, thì hệ thống phải không cho ghi sổ; hệ thống phải không quản lý mã từng chiếc đồ vải (trừ bộ săng mổ tiệt khuẩn quản lý theo gói với Cycle ID). | Must | Active | BRU-LIN-001 và ngoại lệ |
| FR-M3-01.2 | Khi người dùng nhấn Lấy cân, hệ thống phải đọc số từ cân điện tử (RS-232/USB) và điền vào ô kg của dòng đang chọn. | Must | Active | TCCN 1 |
| FR-M3-01.3 | Khi chỉ một trong hai giá trị số chiếc hoặc kg được nhập, hệ thống phải tự tính giá trị còn lại theo khối lượng chuẩn/chiếc của loại đồ vải. | Must | Active | TCCN 2; BRU-LIN-002 |
| FR-M3-01.4 | Nếu chênh lệch giữa giá trị nhập và giá trị quy đổi lớn hơn 15%, thì hệ thống phải cảnh báo và cho phép người dùng giữ giá trị nhập kèm ghi chú. | Must | Active | Xử lý lỗi; BRU-LIN-002 |
| FR-M3-01.5 | Khi lượt thu gom được ghi sổ, hệ thống phải cho in biên nhận thu gom. | Must | Active | TCCN 3 |
| FR-M3-02 | Khi người dùng khai báo loại đồ vải với khối lượng chuẩn/chiếc, định mức theo khoa (tối thiểu/tối đa) và giá trị/chiếc, hệ thống phải lưu vào danh mục dùng cho thu gom, cấp phát và đối chiếu. | Must | Active | UC-16; SCR-16; API-M3-01; BRU-LIN-001, BRU-LIN-002; phụ thuộc FR-M3-01. Nguồn: BR-M3 |
| FR-M3-02.1 | Nếu khối lượng chuẩn/chiếc ≤ 0, thì hệ thống phải không cho lưu loại đồ vải. | Must | Active | TCCN 1 |
| FR-M3-02.2 | Khi người dùng ngừng một loại đồ vải, hệ thống phải ẩn loại khỏi danh sách chọn nhưng giữ toàn bộ lịch sử giao dịch. | Must | Active | TCCN 3 |
| FR-M3-02.3 | Nếu tên loại đồ vải trùng với tên đã có, thì hệ thống phải chặn lưu. | Must | Active | Xử lý lỗi |
| FR-M3-03 | Khi người vận hành tạo lô giặt với máy giặt/sấy Sẵn sàng, chương trình, kg, cờ nhiễm, hóa chất, nhiệt độ và người vận hành, hệ thống phải tạo Laundry Batch ở trạng thái Đang chạy và cho ghi kết quả Đạt/Không đạt khi kết thúc. | Must | Active | UC-17; SCR-17; API-M3-02; BRU-LIN-001, BRU-LIN-003; phụ thuộc FR-M3-04. Nguồn: BR-M3 |
| FR-M3-03.1 | Nếu lô giặt chứa đồ vải vừa nhiễm vừa không nhiễm, thì hệ thống phải từ chối tạo lô. | Must | Active | TCCN 1; BRU-LIN-003 |
| FR-M3-03.2 | Nếu lô giặt được đánh dấu Nhiễm mà chương trình giặt có nhiệt độ dưới 71°C và không có hóa chất khử khuẩn, thì hệ thống phải từ chối tạo lô. | Must | Active | TCCN 2; BRU-LIN-003 |
| FR-M3-03.3 | Nếu kg của lô vượt tải máy cấu hình, thì hệ thống phải từ chối tạo lô. | Must | Active | TCCN 3 |
| FR-M3-03.4 | Trong khi máy giặt/sấy ở trạng thái Khóa, hệ thống phải không cho chọn máy đó khi tạo lô giặt. | Must | Active | Xử lý lỗi; BRU-EQP-002 |
| FR-M3-04 | Khi lô giặt chuyển sang Hoàn tất, hệ thống phải trừ tồn hóa chất theo định mức chương trình × kg và tính chi phí/kg của lô gồm điện, nước, hóa chất, nhân công, hiển thị ngay khi hoàn tất. | Should | Active | UC-17; SCR-17; API-M3-02; BRU-INV-002, BRU-LIN-001; phụ thuộc FR-M3-03. Nguồn: BR-M3 |
| FR-M3-04.1 | Khi người dùng yêu cầu, hệ thống phải xuất báo cáo chi phí/kg theo tháng. | Should | Active | TCCN 3 |
| FR-M3-04.2 | Nếu chương trình giặt thiếu định mức, thì hệ thống phải cảnh báo và vẫn cho hoàn tất lô. | Should | Active | Xử lý lỗi |
| FR-M3-05 | Khi nhân viên đồ vải ghi cấp phát (trả) đồ vải cho khoa với người nhận và từng dòng loại, số chiếc, kg, hệ thống phải tạo Linen Issue, cập nhật tồn khoa đồ vải và hiển thị ngay đối chiếu cấp phát so với thu gom của cùng khoa. | Must | Active | UC-18; SCR-18; API-M3-03, API-M3-04; BRU-LIN-001, BRU-LIN-004; phụ thuộc FR-M3-06. Nguồn: BR-M3 |
| FR-M3-05.1 | Khi Linen Issue được xác nhận, hệ thống phải thu chữ ký nhận điện tử của người nhận và cho in biên nhận. | Must | Active | TCCN 2, 3 |
| FR-M3-05.2 | Nếu số cấp phát vượt định mức tối đa của khoa cho loại đồ vải, thì hệ thống phải cảnh báo. | Must | Active | Xử lý lỗi |
| FR-M3-06 | Khi cuối ngày hoặc khi cấp phát, hệ thống phải tính chênh lệch (thu − trả − hủy) theo khoa/loại/kỳ, lập bảng chênh lệch và cảnh báo vượt định mức hoặc dưới tối thiểu. | Must | Active | UC-18; SCR-18; API-M3-03, API-M3-04; BRU-LIN-004; phụ thuộc FR-M3-05. Nguồn: BR-M3 |
| FR-M3-06.1 | Nếu chênh lệch trong tháng lớn hơn 5% số chiếc, thì hệ thống phải cảnh báo R02. | Must | Active | TCCN 1; BRU-LIN-004 |
| FR-M3-06.2 | Khi người dùng ghi hủy đồ vải, hệ thống phải yêu cầu lý do và ảnh. | Must | Active | TCCN 2 |
| FR-M3-06.3 | Khi người dùng yêu cầu, hệ thống phải xuất bảng chênh lệch ra Excel theo khoa. | Must | Active | TCCN 3 |
| FR-M3-06.4 | Nếu kỳ được chọn không có dữ liệu, thì hệ thống phải hiển thị giá trị 0 thay cho lỗi. | Must | Active | Xử lý lỗi |

#### 3.1.4 M4 — Nhân sự & chứng chỉ

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M4-01 | Khi người dùng tạo hồ sơ nhân viên với họ tên, mã NV, chức danh, khu vực làm việc, mã thẻ, ngày vào, khám sức khỏe, tiêm chủng (viêm gan B) và ảnh, hệ thống phải tạo Employee liên kết User và tự sinh mã nhân viên duy nhất tiền tố NV- in được thẻ QR/DataMatrix. | Must | Active | UC-19; SCR-19; API-M4-01; BRU-ID-006; phụ thuộc FR-M4-02. Nguồn: BR-M4 |
| FR-M4-01.1 | Khi thẻ nhân viên được quét tại trạm, hệ thống phải mở phiên trạm cho nhân viên đó (sau kiểm tra năng lực FR-M4-03). | Must | Active | TCCN 1 |
| FR-M4-01.2 | Khi bệnh viện có thẻ nhân viên sẵn, hệ thống phải cho đăng ký mã thẻ đó làm mã thẻ đăng nhập nếu mã duy nhất và quét được. | Must | Active | BRU-ID-006 ngoại lệ |
| FR-M4-01.3 | Nếu mã thẻ nhập trùng với mã thẻ đã có, thì hệ thống phải chặn lưu. | Must | Active | TCCN 1; Xử lý lỗi |
| FR-M4-01.4 | Khi khám sức khỏe hoặc tiêm chủng của nhân viên tới ngày hết hạn, hệ thống phải nhắc nhân viên và R02. | Must | Active | TCCN 2 |
| FR-M4-01.5 | Khi nhân viên được đánh dấu Nghỉ việc, hệ thống phải vô hiệu thẻ ngay nhưng vẫn giữ tra cứu lịch sử của nhân viên. | Must | Active | TCCN 3; BRU-ID-006 |
| FR-M4-02 | Khi người dùng ghi chứng chỉ (loại tự điền, có gợi ý từ các loại đã dùng, ví dụ CCHN, KSNK, tiệt khuẩn, vận hành thiết bị áp lực; A-59) với số, nơi cấp, ngày cấp, hạn và file scan, hệ thống phải tạo bản ghi Certificate gắn nhân viên. | Must | Active | UC-19; SCR-19; API-M4-01; BRU-HR-002; phụ thuộc FR-M4-01. Nguồn: BR-M4 |
| FR-M4-02.1 | Khi còn 60, 30 và 7 ngày trước hạn chứng chỉ, và khi chứng chỉ hết hạn, hệ thống phải gửi thông báo cho nhân viên và R02. | Must | Active | TCCN 1; BRU-HR-002 |
| FR-M4-02.2 | Khi chứng chỉ hết hạn, hệ thống phải tự vô hiệu mọi năng lực trạm yêu cầu chứng chỉ đó. | Must | Active | TCCN 2; BRU-HR-002 |
| FR-M4-02.3 | Khi chứng chỉ được gia hạn, hệ thống phải tạo bản ghi Certificate mới và giữ lịch sử bản ghi cũ. | Must | Active | TCCN 3 |
| FR-M4-02.4 | Khi chứng chỉ không có hạn (vĩnh viễn), hệ thống phải đánh dấu Không hết hạn và không phát cảnh báo. | Must | Active | Xử lý lỗi |
| FR-M4-03 | Khi R02 gán năng lực cho nhân viên theo trạm với chứng chỉ yêu cầu, người đánh giá, ngày và hiệu lực, hệ thống phải tạo Competency dùng để kiểm tra khi đăng nhập trạm. | Must | Active | UC-20; SCR-20; API-M4-02; BRU-HR-001; phụ thuộc FR-M4-04. Nguồn: BR-M4 |
| FR-M4-03.1 | Khi nhân viên đăng nhập trạm, hệ thống phải chỉ cho phép nếu nhân viên có năng lực của trạm đó và mọi chứng chỉ bắt buộc của trạm còn hạn. | Must | Active | BRU-HR-001; A-71: ngoại lệ khi có cho phép tạm NS-001 còn hiệu lực do R01/R02 duyệt, tối đa 24 giờ, có lý do, không tự duyệt |
| FR-M4-03.2 | Nếu nhân viên thiếu năng lực hoặc chứng chỉ hết hạn khi đăng nhập trạm, thì hệ thống phải từ chối, hiển thị rõ lý do và ghi audit. | Must | Active | TCCN 1; Xử lý lỗi |
| FR-M4-03.3 | Khi R02 cấp quyền trạm tạm thời cho tình huống thiếu người, hệ thống phải giới hạn hiệu lực 24 giờ và ghi audit. | Must | Active | TCCN 2; BRU-HR-001 ngoại lệ |
| FR-M4-03.4 | Khi người dùng mở ma trận năng lực, hệ thống phải hiển thị toàn bộ nhân viên × trạm trên một màn hình. | Must | Active | TCCN 3 |
| FR-M4-04 | Khi R02 xếp lịch ca theo khu với ca, khu, nhân viên và ngày, hệ thống phải lưu lịch ca và tính sản lượng (số bộ xử lý, số mẻ) theo người và ca từ sự kiện trạm. | Should | Active | UC-20; SCR-20; API-M4-02; BRU-HR-001; phụ thuộc FR-M4-03. Nguồn: BR-M4 |
| FR-M4-04.1 | Nếu nhân viên được xếp vào ca của khu mà nhân viên thiếu năng lực trạm của khu đó, thì hệ thống phải không cho xếp. | Should | Active | TCCN 1 |
| FR-M4-04.2 | Khi người dùng yêu cầu, hệ thống phải xuất lịch ca theo tuần. | Should | Active | TCCN 3 |
| FR-M4-04.3 | Nếu một nhân viên bị xếp trùng ca, thì hệ thống phải cảnh báo. | Should | Active | Xử lý lỗi |

#### 3.1.5 M5 — Thiết bị & bảo trì

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M5-01 | Khi người dùng khai báo thiết bị với mã, tên, loại, hãng, model, serial, khu vực, cửa vào/ra (máy hai cửa), ngày đưa vào sử dụng, nguyên giá, năm khấu hao và dung tích, hệ thống phải tạo Equipment ở trạng thái Sẵn sàng, tự sinh mã thiết bị duy nhất tiền tố TB- và in được QR thiết bị để quét chọn máy. | Must | Active | UC-21; SCR-21; API-M5-01; BRU-ID-006, BRU-EQP-003; phụ thuộc FR-M5-02. Nguồn: BR-M5; xem A-04 (Q4, Q5, Q7): mã `TB-` ghi `Code Registry`, in QR thuộc FEAT-005, trạng thái đổi qua `equipment.status.set_status` |
| FR-M5-01.1 | Khi thiết bị là máy hai cửa, hệ thống phải yêu cầu khai báo khu của cửa vào và khu của cửa ra (khu kế tiếp). | Must | Active | TCCN 1; BRU-FLOW-001 ngoại lệ; xem A-04 (Q8): `core.zones.check_pass_through` |
| FR-M5-01.2 | Khi thiết bị được lưu, hệ thống phải tính khấu hao/mẻ từ nguyên giá, năm khấu hao và số mẻ kế hoạch/năm. | Must | Active | TCCN 2; BRU-CST-001; xem A-04 (Q2, tạm — chờ chủ đầu tư duyệt): nguyên giá ÷ (năm khấu hao × số mẻ kế hoạch/năm) |
| FR-M5-01.3 | Nếu số serial trùng với thiết bị đã có, thì hệ thống phải chặn lưu. | Must | Active | Xử lý lỗi; xem A-04 (Q8): serial không phân biệt hoa/thường và khoảng trắng đầu/cuối |
| FR-M5-02 | Khi người dùng khai báo chương trình xử lý cho máy với nhiệt độ, thời gian, áp suất, hóa chất, phút chu trình, định mức điện (kWh)/nước (lít)/hơi, chỉ thị/test, loại gói tương thích và yêu cầu BI, hệ thống phải tạo Program dùng khi tạo lô/mẻ và cung cấp định mức cho tiêu hao và giá thành. [A-83] Chương trình máy tiệt khuẩn phân loại Thường/Test; chương trình thường đang dùng phải có ít nhất một loại gói (Item nhóm Packaging). | Must | Active | UC-21; SCR-21; API-M5-01; BRU-EQP-003; phụ thuộc FR-M5-01. Nguồn: BR-M5; xem A-04 (Q6, Q7): `param_schema` là bảng con `Program Parameter`, quyền ghi |
| FR-M5-02.1 | Nếu chương trình thiếu định mức điện, nước, hóa chất, chỉ thị hoặc thời gian chu trình, thì hệ thống phải hiển thị cảnh báo và không tính giá thành cho mẻ dùng chương trình đó; hệ thống phải cho phép tạm dùng định mức mặc định theo loại máy. | Must | Active | TCCN 1; BRU-EQP-003 và ngoại lệ; xem A-04 (Q1, tạm — chờ chủ đầu tư duyệt): `norm_status` Complete/Missing/Default, `Equipment Type Norm`, `use_default_norms` chỉ R10/System Manager (P1) |
| FR-M5-02.2 | Khi tạo lô/mẻ, hệ thống phải chỉ hiển thị các chương trình thuộc máy đã chọn. | Must | Active | TCCN 2 |
| FR-M5-02.3 | Khi chương trình bị ngừng, hệ thống phải giữ nguyên dữ liệu các mẻ đã dùng chương trình đó. | Must | Active | TCCN 3 |
| FR-M5-02.4 | Nếu tham số chương trình nằm ngoài dải an toàn của máy, thì hệ thống phải cảnh báo. | Must | Active | Xử lý lỗi; xem A-04 (Q3, tạm — chờ chủ đầu tư duyệt): `safe_temp_min/max`, `safe_pressure_max` trên Equipment, chỉ cảnh báo |
| FR-M5-03 | Khi người dùng lập kế hoạch bảo trì/kiểm định/hiệu chuẩn với chu kỳ, ngày kế hoạch, đơn vị thực hiện, chứng nhận, hạn hiệu lực và chi phí, hệ thống phải tạo Maintenance Record, nhắc trước 30 và 7 ngày và cập nhật hạn hiệu lực của thiết bị. | Must | Active | UC-22; SCR-22; API-M5-03; BRU-EQP-002; phụ thuộc FR-M5-04. Nguồn: BR-M5 |
| FR-M5-03.1 | Nếu hạn kiểm định của thiết bị đã qua, thì hệ thống phải tự chuyển thiết bị sang Khóa. | Must | Active | TCCN 1; BRU-EQP-002; liên kết FR-M5-06 |
| FR-M5-03.2 | Khi một Maintenance Record được hoàn tất, hệ thống phải tự tạo lịch kế tiếp theo chu kỳ. | Must | Active | TCCN 2 |
| FR-M5-03.3 | Nếu hồ sơ kiểm định không có chứng nhận đính kèm hoặc thiếu hạn hiệu lực, thì hệ thống phải không cho đóng hồ sơ. | Must | Active | TCCN 3; Xử lý lỗi |
| FR-M5-04 | Khi người dùng ghi sự cố thiết bị với thời điểm, thời gian dừng, phụ tùng, chi phí, nhà cung cấp và mẻ bị ảnh hưởng, hệ thống phải chuyển máy sang Đang sửa chữa và, khi đóng sự cố, trở về Sẵn sàng. | Must | Active | UC-22; SCR-22; API-M5-03; BRU-EQP-002; phụ thuộc FR-M5-03. Nguồn: BR-M5 |
| FR-M5-04.1 | Trong khi máy ở trạng thái Đang sửa chữa, hệ thống phải không cho chọn máy khi tạo lô/mẻ. | Must | Active | TCCN 1; BRU-EQP-002 |
| FR-M5-04.2 | Khi sự cố được ghi cho máy đang có mẻ chạy, hệ thống phải tự đánh dấu mẻ đó Cần xem xét. | Must | Active | TCCN 2 |
| FR-M5-04.3 | Khi chi phí sửa chữa được ghi, hệ thống phải tạo Cost Entry tương ứng trong M7. | Must | Active | TCCN 3; liên kết FR-M7-01 |
| FR-M5-04.4 | Nếu sự cố được đóng mà chưa có kết quả kiểm tra sau sửa, thì hệ thống phải không cho đóng. | Must | Active | Xử lý lỗi |
| FR-M5-05 | Khi người vận hành ghi test hằng ngày cho máy (Bowie-Dick, leak test, test máy plasma; test làm sạch máy rửa là tự nguyện, A-70) với kết quả, ảnh, lô test, người và giờ, hệ thống phải tạo Daily Test và mở khóa máy nếu kết quả Đạt. [A-84] Test chạy máy ghi bắt đầu và kết thúc; trong lúc chạy máy hiện Đang test và không nạp được; kết quả chỉ ghi sau khi kết thúc. | Must | Active | UC-23; SCR-23; API-M5-02; BRU-EQP-001; phụ thuộc FR-M5-06. Nguồn: BR-M5 |
| FR-M5-05.1 | Khi tạo mẻ trên máy tiệt khuẩn thuộc diện bắt buộc theo `TraceCore Settings` (Không bắt buộc / Tất cả máy tiệt khuẩn / Chỉ máy được chọn; A-70), hệ thống phải yêu cầu test bắt buộc Đạt trong ngày: máy hấp là Bowie-Dick và leak test (nếu viện yêu cầu). Máy rửa và thiết bị khác không bao giờ bị yêu cầu test hằng ngày. | Must | Active | TCCN 1, 2; BRU-EQP-001 |
| FR-M5-05.2 | Khi máy là plasma H2O2, hệ thống phải không yêu cầu Bowie-Dick, phải yêu cầu chỉ thị hóa học từng mẻ và, nếu máy thuộc diện bắt buộc và viện bật test plasma, phải yêu cầu test hằng ngày máy plasma Đạt trong ngày (A-70). | Must | Active | TCCN 3; BRU-EQP-001 ngoại lệ |
| FR-M5-05.3 | Nếu test hằng ngày bắt buộc của máy Không đạt, thì hệ thống phải chuyển máy sang Khóa và tự tạo NC; test tự nguyện của máy ngoài diện không khóa máy (A-70). | Must | Active | Xử lý lỗi |
| FR-M5-06 | Nếu máy thuộc diện bắt buộc chưa có test ngày Đạt (A-70), quá hạn kiểm định/hiệu chuẩn hoặc đang Sửa chữa, thì hệ thống phải khóa tạo mẻ/lô trên máy đó và hiển thị lý do khóa tại màn tạo mẻ. | Must | Active | UC-23; SCR-23; API-M5-02; BRU-EQP-001, BRU-EQP-002; phụ thuộc FR-M5-05. Nguồn: BR-M5 |
| FR-M5-06.1 | Khi R02 mở khóa tạm một máy, hệ thống phải yêu cầu lý do và thời hạn ≤ 24 giờ, ghi audit; hệ thống phải không cho vai trò khác mở khóa. | Must | Active | TCCN 2, 3; BRU-EQP-002 |
| FR-M5-06.2 | Nếu máy bị khóa do quá hạn kiểm định thiết bị áp lực, thì hệ thống phải không cho bất kỳ vai trò nào mở khóa tạm. | Must | Active | TCCN 2; Xử lý lỗi; BRU-EQP-002 |
| FR-M5-07 | Trong khi loại máy yêu cầu lô hóa chất mà máy chưa khai báo lô đang dùng hoặc lô đã hết hạn, hệ thống phải chặn tạo lô/mẻ trên máy đó và hiển thị HC-003 hoặc HC-001 kèm mã máy, mã lô; hệ thống phải cảnh báo HC-002 khi lô còn dưới số ngày cấu hình. | Must | Active | A-71; BRU-INV-001 |

#### 3.1.6 M6 — Kho vật tư tiêu hao

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M6-01 | Khi R09 nhập kho vật tư với vật tư, lô, hạn dùng, số lượng, đơn giá, nhà cung cấp và chứng từ, hệ thống phải tạo Stock Entry Đã ghi sổ, cập nhật tồn theo lô và tính lại giá bình quân gia quyền. | Must | Active | UC-24; SCR-24; API-M6-01; phụ thuộc FR-M6-02. Nguồn: BR-M6; xem A-07 (V1–V6, V11 tạm — chờ chủ đầu tư duyệt) |
| FR-M6-01.1 | Nếu vật tư thuộc nhóm chỉ thị hóa học, chỉ thị sinh học hoặc hóa chất mà không có hạn dùng, thì hệ thống phải không cho ghi sổ nhập kho. | Must | Active | TCCN 1 |
| FR-M6-01.2 | Khi người dùng tải file Excel theo mẫu, hệ thống phải nhập kho hàng loạt từ file đó. | Must | Active | TCCN 3; xem A-07 (V12) |
| FR-M6-01.3 | Nếu hạn dùng của lô nhập nhỏ hơn ngày hiện tại, thì hệ thống phải chặn nhập. | Must | Active | Xử lý lỗi |
| FR-M6-02 | Khi người dùng khai báo vật tư tiêu hao với mã, tên, nhóm, đơn vị, quy cách, tồn tối thiểu theo kho, NCC, cờ có hạn dùng và — với nhóm Nhãn — phương pháp tương thích (Hấp/Plasma), hệ thống phải tạo Item dùng cho định mức, kho và định giá. | Must | Active | UC-24; SCR-24; API-M6-01; phụ thuộc FR-M6-01. Nguồn: BR-M6; xem A-07 (V1–V6, V11 tạm — chờ chủ đầu tư duyệt) |
| FR-M6-02.1 | Hệ thống phải giới hạn nhóm vật tư trong danh sách cố định: chỉ thị hóa học loại 1–6, chỉ thị sinh học, test, bao gói, túi, hộp lọc, nhãn (2 loại: nhãn hấp VT-NHAN-HAP, nhãn plasma VT-NHAN-PLASMA), hóa chất, khác. | Must | Active | TCCN 1; BRU-REP-011; xem A-07 (V1–V3, tạm): giữ thêm nhóm `Lubricant`, chỉ thị hóa học thêm lớp 3 |
| FR-M6-02.2 | Khi Item được dùng trong tính giá, hệ thống phải liên kết Item với đơn giá của phiên bản định giá hiện hành. | Must | Active | TCCN 3; FR-M7-03 |
| FR-M6-02.3 | Nếu mã vật tư trùng với mã đã có, thì hệ thống phải chặn lưu. | Must | Active | Xử lý lỗi |
| FR-M6-03 | Khi lô rửa, mẻ tiệt khuẩn hoặc lô giặt chuyển sang Hoàn tất, hệ thống phải tạo Stock Entry tiêu hao tự động trừ tồn theo định mức chương trình × số gói (hoặc kg) và ghi lô vật tư đã dùng vào hồ sơ mẻ để truy xuất và tính chi phí mẻ. | Must | Active | UC-25; SCR-25; API-M6-01; BRU-INV-002; phụ thuộc FR-M6-04, FR-M5-02, FR-M7-04. Nguồn: BR-M6 |
| FR-M6-03.1 | Trong khi lô/mẻ chưa Hoàn tất, hệ thống phải cho người vận hành điều chỉnh số thực dùng kèm lý do. | Must | Active | TCCN 3; BRU-INV-002 ngoại lệ |
| FR-M6-03.2 | Nếu tồn không đủ để trừ tiêu hao, thì hệ thống phải cảnh báo, vẫn cho hoàn tất mẻ và đánh dấu tồn âm cần xử lý. | Must | Active | Xử lý lỗi |
| FR-M6-03.3 | Khi trừ tiêu hao tự động trên site nhiều Company, hệ thống phải chỉ lấy lô của một Company xác định theo máy, lô đã ghim, Company duy nhất có tồn hoặc người vận hành; nếu không xác định được thì phải báo lỗi rõ và không xuất. | Must | Active | A-78; #1816 |
| FR-M6-03.4 | Khi R09/R02 xử lý lại tiêu hao bị lỗi của lô rửa, mẻ tiệt khuẩn hoặc lô giặt, hệ thống phải không trừ trùng, phải ghi sổ phiếu Nháp còn sót thay vì coi là đã xuất, và phải đóng các cảnh báo lỗi tiêu hao của nguồn đó khi đã có phiếu đã ghi sổ. | Must | Active | A-78; #1816 |
| FR-M6-04 | Khi người dùng xuất kho thủ công với vật tư, số lượng, lý do và người, hệ thống phải tạo Stock Entry xuất và gợi ý lô có hạn gần nhất (FEFO). | Must | Active | UC-25; SCR-25; API-M6-01; BRU-INV-001; phụ thuộc FR-M6-03. Nguồn: BR-M6 |
| FR-M6-04.1 | Nếu lô được chọn xuất đã quá hạn, thì hệ thống phải chặn xuất. | Must | Active | TCCN 2; BRU-INV-001 |
| FR-M6-04.2 | Khi chỉ thị sinh học được dùng cho mẻ, hệ thống phải kiểm tra lô còn hạn tại thời điểm dùng. | Must | Active | BRU-INV-001 |
| FR-M6-04.3 | Nếu xuất thủ công không có lý do, thì hệ thống phải không cho ghi sổ. | Must | Active | TCCN 3 |
| FR-M6-04.4 | Nếu người dùng chọn lô hạn xa khi còn lô hạn gần, thì hệ thống phải cảnh báo. | Must | Active | Xử lý lỗi |
| FR-M6-04.5 | Nếu vật tư xuất thủ công có tồn ở nhiều Company mà không xác định được Company của phiếu, hoặc lô chọn tay thuộc nhiều Company, thì hệ thống phải chặn và nêu cách xử lý. | Must | Active | A-78; #1816 |
| FR-M6-05 | Khi R09 lập phiếu kiểm kê với kho, ngày và số thực tế, hệ thống phải tạo Stock Count, hiển thị chênh lệch theo lô và cho in phiếu kiểm kê. | Should | Active | UC-26; SCR-26; API-M6-02; phụ thuộc FR-M6-06. Nguồn: BR-M6 |
| FR-M6-05.1 | Khi điều chỉnh tồn từ kết quả kiểm kê, hệ thống phải yêu cầu phê duyệt của R02 hoặc R09 trước khi ghi sổ. | Should | Active | TCCN 2 |
| FR-M6-05.2 | Trong khi một phiếu kiểm kê của kho đang mở, hệ thống phải khóa xuất nhập của kho đó. | Should | Active | Xử lý lỗi |
| FR-M6-06 | Khi tồn một vật tư xuống dưới tồn tối thiểu của kho, hệ thống phải cảnh báo trên dashboard và qua email. | Must | Active | UC-26; SCR-26; API-M6-02; phụ thuộc FR-M6-05. Nguồn: BR-M6 |
| FR-M6-06.1 | Khi một lô vật tư sẽ hết hạn trong 30 ngày, hệ thống phải cảnh báo trên dashboard và qua email. | Must | Active | TCCN 2 |
| FR-M6-06.2 | Khi người dùng bấm tạo đề nghị mua từ một cảnh báo, hệ thống phải tạo đề nghị mua trong một chạm. | Must | Active | TCCN 3 |
| FR-M6-06.3 | Nếu vật tư chưa có tồn tối thiểu, thì hệ thống phải không cảnh báo tồn và ghi vật tư vào danh sách thiếu cấu hình. | Must | Active | Xử lý lỗi |

#### 3.1.7 M7 — Chi phí & giá thành tái xử lý

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M7-01 | Khi R09 nhập chi phí với khoản mục (khấu hao, bảo trì, sửa chữa, phụ tùng, điện, nước máy, nước RO, hơi, khí nén, nhân công, đồ bảo hộ, thuê ngoài), số tiền, kỳ, chứng từ và nguồn (hóa đơn/định mức/đồng hồ), hệ thống phải tạo Cost Entry. | Must | Active | UC-27; SCR-27; API-M7-01; phụ thuộc FR-M7-02. Nguồn: BR-M7 |
| FR-M7-01.1 | Hệ thống phải cung cấp danh mục khoản mục cố định theo BRD (12 loại) và cho phép R09 mở rộng. | Must | Active | TCCN 1 |
| FR-M7-01.2 | Khi chi phí được nhập theo tháng, hệ thống phải cho phân bổ theo ngày trong kỳ. | Must | Active | TCCN 2 |
| FR-M7-01.3 | Khi nguồn là đồng hồ điện/nước, hệ thống phải nhận chỉ số đầu và cuối kỳ và tính lượng tiêu thụ. | Must | Active | TCCN 3 |
| FR-M7-01.4 | Nếu số tiền hoặc chỉ số nhập là số âm, thì hệ thống phải chặn lưu. | Must | Active | Xử lý lỗi |
| FR-M7-02 | Khi R09 gắn một Cost Entry với đối tượng phân bổ (thiết bị, khu vực hoặc chương trình) theo tỷ lệ, hệ thống phải lưu liên kết để sẵn sàng phân bổ theo mẻ. | Must | Active | UC-27; SCR-27; API-M7-01; phụ thuộc FR-M7-01. Nguồn: BR-M7 |
| FR-M7-02.1 | Nếu tổng tỷ lệ phân bổ của một khoản chi phí khác 100%, thì hệ thống phải chặn lưu. | Must | Active | TCCN 1; Xử lý lỗi |
| FR-M7-02.2 | Khi tính chi phí mẻ, hệ thống phải phân bổ chi phí gắn khu vực cho các mẻ theo số mẻ trong kỳ. | Must | Active | TCCN 2 |
| FR-M7-02.3 | Khi người dùng yêu cầu, hệ thống phải xuất báo cáo chi phí theo thiết bị và kỳ. | Must | Active | TCCN 3 |
| FR-M7-03 | Khi R09 lưu đơn giá vật tư/nhân công/điện/nước với hiệu lực từ ngày và phê duyệt, hệ thống phải tạo Cost Rate Version mới và giữ lịch sử mọi phiên bản để tra cứu. | Must | Active | UC-28; SCR-28; API-M7-01; BRU-CST-002; phụ thuộc FR-M7-04. Nguồn: BR-M7 |
| FR-M7-03.1 | Khi tính giá thành cho một giao dịch, hệ thống phải dùng phiên bản định giá có hiệu lực tại ngày giao dịch và không tính lại giao dịch quá khứ khi giá thay đổi. | Must | Active | TCCN 2; BRU-CST-002 |
| FR-M7-03.2 | Khi R09 tính lại giá thành quá khứ theo yêu cầu của R01, hệ thống phải yêu cầu ghi chú phiên bản giá và lưu kết quả thành bảng giá thành phiên bản mới. | Must | Active | BRU-CST-002 ngoại lệ |
| FR-M7-03.3 | Nếu khoảng hiệu lực của phiên bản mới chồng lấn phiên bản đã có, thì hệ thống phải chặn lưu. | Must | Active | Xử lý lỗi |
| FR-M7-04 | Khi R09 khai báo định mức tiêu hao (chỉ thị, test, bao gói, nhãn) theo chương trình hoặc theo loại gói với số lượng/mẻ hoặc /gói, hệ thống phải lưu định mức phân biệt rõ theo mẻ và theo gói làm cơ sở tiêu hao tự động và tính giá. | Must | Active | UC-28; SCR-28; API-M7-01; BRU-CST-002, BRU-EQP-003; phụ thuộc FR-M7-03. Nguồn: BR-M7 |
| FR-M7-04.1 | Khi định mức thay đổi, hệ thống phải không thay đổi tiêu hao và chi phí của các mẻ đã Hoàn tất. | Must | Active | TCCN 2 |
| FR-M7-04.2 | Nếu một chương trình chưa có định mức, thì hệ thống phải cảnh báo. | Must | Active | TCCN 3 |
| FR-M7-04.3 | Nếu định mức nhập bằng 0, thì hệ thống phải cảnh báo. | Must | Active | Xử lý lỗi |
| FR-M7-05 | Khi mẻ được giải phóng, hệ thống phải lập Cost Sheet mẻ với chi phí mẻ = khấu hao máy/mẻ + điện + nước + hóa chất + chỉ thị + nhân công (phút chuẩn × đơn giá) + bảo trì phân bổ, và chia cho các gói theo số gói (mặc định) hoặc theo thể tích gói (tùy chọn). | Must | Active | UC-29; SCR-29; API-M7-02; BRU-CST-001; phụ thuộc FR-M7-06, FR-M5-02, FR-M7-04. Nguồn: BR-M7 |
| FR-M7-05.1 | Khi mẻ bị kết luận Không đạt, hệ thống phải vẫn ghi nhận chi phí mẻ và tính vào chi phí chất lượng. | Must | Active | TCCN 3; BRU-CST-001 ngoại lệ |
| FR-M7-05.2 | Nếu thiếu đơn giá cho một khoản của mẻ, thì hệ thống phải ghi Cost Sheet là Chưa định giá và cảnh báo. | Must | Active | Xử lý lỗi |
| FR-M7-06 | Khi tính giá thành tái xử lý của một bộ cho một chu trình, hệ thống phải cộng dồn chi phí gói qua 8 trạm (cấu hình mặc định, A-64) và khấu hao dụng cụ/chu trình = giá trị bộ ÷ cơ số tái xử lý tối đa. | Must | Active | UC-29; SCR-29; API-M7-02; BRU-CST-001, BRU-CST-003; phụ thuộc FR-M7-05. Nguồn: BR-M7 |
| FR-M7-06.1 | Khi người dùng yêu cầu, hệ thống phải xuất báo cáo giá thành theo bộ, Cycle ID, khoa, phương pháp và tháng, kèm so sánh với tháng trước. | Must | Active | TCCN 2, 3 |
| FR-M7-06.2 | Khi bộ là bộ mượn, hệ thống phải không tính khấu hao dụng cụ và tính phí mượn nếu có. | Must | Active | Xử lý lỗi; BRU-CST-003 ngoại lệ |

#### 3.1.8 M8 — Cơ số & kiểm soát vượt ngưỡng

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M8-01 | Khi R01 hoặc R02 nhập tay cơ số tái xử lý tối đa cho dụng cụ, loại bộ hoặc vật tư tái sử dụng kèm nguồn (IFU/Ước tính) và ngưỡng cảnh báo sớm (% hoặc số lần), hệ thống phải lưu Par Level và không tự lấy cơ số từ IFU. | Must | Active | UC-30; SCR-30; API-M8-01; phụ thuộc FR-M8-02. Nguồn: BR-M8 |
| FR-M8-01.1 | Khi cơ số để trống, hệ thống phải đánh dấu Chưa xác định, chỉ cảnh báo và không chặn sinh Cycle ID. | Must | Active | TCCN 1 |
| FR-M8-01.2 | Khi loại bộ không đặt cơ số riêng, hệ thống phải lấy cơ số bộ = min cơ số của các dụng cụ trong BOM. | Must | Active | TCCN 2 |
| FR-M8-01.3 | Khi cơ số được thay đổi, hệ thống phải ghi lịch sử người – thời điểm – giá trị cũ/mới. | Must | Active | TCCN 3 |
| FR-M8-01.4 | Nếu cơ số nhập ≤ số chu trình đã dùng của đối tượng, thì hệ thống phải cảnh báo trước khi lưu. | Must | Active | Xử lý lỗi |
| FR-M8-02 | Khi R01/R02 cấu hình cơ số tồn khoa với khoa, loại bộ/đồ vải, tối thiểu, tối đa và % cho phép vượt, hệ thống phải lưu Par Level khoa và áp dụng khi cấp phát (FR-M2-16). | Must | Active | UC-30; SCR-30; API-M8-01; BRU-PAR-005; phụ thuộc FR-M8-01. Nguồn: BR-M8 |
| FR-M8-02.1 | Khi khoa cấp cứu được cấu hình, hệ thống phải cho đặt % cho phép vượt là 20% không cần duyệt. | Must | Active | TCCN 2; BRU-PAR-005 |
| FR-M8-02.2 | Khi người dùng yêu cầu, hệ thống phải xuất báo cáo tồn khoa so với cơ số. | Must | Active | TCCN 3 |
| FR-M8-02.3 | Nếu tối thiểu > tối đa, thì hệ thống phải chặn lưu. | Must | Active | Xử lý lỗi |
| FR-M8-03 | Khi mẻ chứa gói được giải phóng Đạt, hệ thống phải tăng bộ đếm chu trình của Set ID và của từng dụng cụ trong BOM thêm 1 (chu trình tái xử lý lại do mẻ lỗi vẫn tính 1). | Must | Active | UC-31; SCR-31; API-M8-02; BRU-PAR-001; phụ thuộc FR-M8-04. Nguồn: BR-M8 |
| FR-M8-03.1 | Khi số chu trình còn lại của bộ hoặc dụng cụ ≤ ngưỡng cảnh báo sớm (mặc định 10% hoặc 5 lần), hệ thống phải hiển thị cảnh báo màu cam tại trạm lắp ráp T3 và trên dashboard, và đưa bộ vào báo cáo dự báo thay thế. | Must | Active | TCCN 1; BRU-PAR-003 |
| FR-M8-03.2 | Nếu số chu trình đã dùng ≥ cơ số tối đa của bộ hoặc của bất kỳ dụng cụ nào trong bộ, thì hệ thống phải không sinh Cycle ID, hiển thị dụng cụ vượt, chuyển Set Unit sang Hết vòng đời – chờ thanh lý và chặn quét sử dụng. | Must | Active | TCCN 2, 3; BRU-PAR-002 |
| FR-M8-03.3 | Khi bộ đã vượt cơ số có ghi đè còn hiệu lực (FR-M8-04), hệ thống phải cho sinh Cycle ID trong phạm vi số chu trình và thời hạn ghi đè. | Must | Active | Xử lý lỗi; BRU-PAR-004 |
| FR-M8-04 | Khi người đề nghị lập yêu cầu ghi đè cơ số cho một Set Unit với lý do, số chu trình thêm và thời hạn, hệ thống phải tạo Override ở trạng thái Đề nghị và chuyển cho R01 (hoặc R02 được ủy quyền) Duyệt/Từ chối. | Must | Active | UC-31; SCR-31; API-M8-02; BRU-PAR-004; phụ thuộc FR-M8-03. Nguồn: BR-M8 |
| FR-M8-04.1 | Hệ thống phải chỉ cho R01 hoặc R02 được ủy quyền duyệt Override. | Must | Active | TCCN 1; BRU-PAR-004 |
| FR-M8-04.2 | Khi Override được duyệt, hệ thống phải lưu audit (DT-OVERRIDE) và tự hết hiệu lực ghi đè khi đạt số chu trình thêm hoặc hết ngày thời hạn. | Must | Active | TCCN 2; BRU-PAR-004 |
| FR-M8-04.3 | Khi hết tháng, hệ thống phải xuất báo cáo ghi đè cho QLCL. | Must | Active | TCCN 3 |
| FR-M8-04.4 | Nếu duyệt Override không có lý do, thì hệ thống phải chặn. | Must | Active | Xử lý lỗi |

#### 3.1.9 M9 — Báo cáo, dashboard & quản trị

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M9-01 | Khi người dùng mở dashboard, hệ thống phải hiển thị theo vai trò số bộ theo trạng thái, sản lượng theo trạm/người/máy (ngày/tuần/tháng), tỷ lệ mẻ lỗi, tồn kho vô khuẩn, gói sắp hết hạn và các cảnh báo cơ số, chứng chỉ, kiểm định, tồn kho trên một màn. | Must | Active | UC-32; SCR-32; API-M9-01; phụ thuộc FR-M9-02. Nguồn: BR-M9 |
| FR-M9-01.1 | Trong khi dashboard đang mở, hệ thống phải làm mới số bộ theo trạng thái trong ≤ 60 giây. | Must | Active | TCCN 1 |
| FR-M9-01.2 | Nếu một chỉ số không có dữ liệu, thì hệ thống phải hiển thị 0. | Must | Active | Xử lý lỗi |
| FR-M9-02 | Khi người dùng chọn kỳ, máy hoặc khoa, hệ thống phải xuất sổ tiệt khuẩn điện tử theo máy (đủ tham số, chỉ thị, người, giải phóng), báo cáo KSNK theo mẫu BYT in được, và dự báo dụng cụ hết vòng đời theo tháng kèm giá, dạng PDF/Excel. | Must | Active | UC-32; SCR-32; API-M9-01; phụ thuộc FR-M9-01; NFR-COMP-01. Nguồn: BR-M9 |
| FR-M9-02.1 | Nếu kỳ báo cáo chưa được khóa, thì hệ thống phải đóng dấu Tạm trên bản xuất. | Must | Active | Xử lý lỗi |
| FR-M9-03 | Khi R10 khai báo khu (bẩn, sạch, vô khuẩn), trạm quét, chức năng trạm và thiết bị ngoại vi (máy quét, in nhãn, cân; IP/cổng), hệ thống phải tạo Zone Station với mỗi trạm thuộc đúng một khu, chức năng giới hạn theo khu và thiết bị ngoại vi gán theo trạm. | Must | Active | UC-33; SCR-33; API-M9-02; BRU-FLOW-001, BRU-ID-006; phụ thuộc FR-M9-04, FR-M9-05, FR-M9-07, FR-M9-06. Nguồn: BR-M9; xem A-03 (E1–E8): khu `ZONE-.##`, chức năng trạm theo loại khu (`core.zones.STEPS_BY_ZONE_TYPE`), ngoại vi quét/cân là child `Station Peripheral`, máy in là DocType `Printer`, trạm chưa gán khu không hoạt động (`STATION_INACTIVE`) |
| FR-M9-03.1 | Khi trạm được tạo, hệ thống phải tự sinh mã trạm duy nhất tiền tố TR- và cho in nhãn QR trạm. | Must | Active | BRU-ID-006; xem A-03 (E1, E6): khu `ZONE-.##`, trạm `TR-.###` ghi `Code Registry`, nhãn QR trạm để FEAT-005 |
| FR-M9-03.2 | Khi thiết bị hai cửa được gán, hệ thống phải cho khai báo cửa vào ở khu này và cửa ra ở khu kế tiếp. | Must | Active | BRU-FLOW-001 ngoại lệ; xem A-03 (E5): `core.zones.check_pass_through`, cửa ra là khu kế tiếp theo chiều Bẩn → Sạch → Vô khuẩn; A-64: theo `Zone Type.next_zone_type` |
| FR-M9-03.3 | Nếu trạm chưa được gán khu, thì hệ thống phải không kích hoạt trạm. | Must | Active | Xử lý lỗi; xem A-03 (E2): trạm lưu được với `is_active = 0`, RPC từ chối `STATION_INACTIVE` |
| FR-M9-04 | Khi tính năng kiểm soát môi trường khu được bật, hệ thống phải ghi nhật ký nhiệt độ, độ ẩm, áp suất chênh theo khu từ nhập tay (2 lần/ngày) hoặc từ cảm biến, và xuất báo cáo tháng. | Should | Active | UC-33; SCR-33; API-M9-02; phụ thuộc FR-M9-03, FR-M9-05, FR-M9-07, FR-M9-06. Nguồn: BR-M9 |
| FR-M9-04.1 | Nếu một chỉ số môi trường vượt ngưỡng cấu hình, thì hệ thống phải cảnh báo R02. | Should | Active | TCCN 2 |
| FR-M9-04.2 | Nếu một ngày thiếu số liệu môi trường của khu, thì hệ thống phải nhắc người phụ trách. | Should | Active | Xử lý lỗi |
| FR-M9-05 | Khi R10 tạo tài khoản với vai trò (R01–R10) và thẻ, hệ thống phải tạo User cho phép đăng nhập bằng tài khoản hoặc quét thẻ. | Must | Active | UC-33; SCR-33; API-M9-02; phụ thuộc FR-M9-03, FR-M9-04, FR-M9-07, FR-M9-06; NFR-SEC-01, NFR-SEC-03. Nguồn: BR-M9 |
| FR-M9-05.1 | Khi bất kỳ thao tác nghiệp vụ nào được thực hiện, hệ thống phải ghi Audit Log gồm người, thời điểm, trạm và giá trị trước/sau. | Must | Active | TCCN 1 |
| FR-M9-05.2 | Hệ thống phải không cho xóa bản ghi nghiệp vụ hay audit; khi cần loại bỏ, hệ thống phải chỉ cho vô hiệu. | Must | Active | TCCN 2 |
| FR-M9-05.3 | Khi người dùng tra cứu audit theo đối tượng, người hoặc khoảng ngày, hệ thống phải trả về các bản ghi khớp. | Must | Active | TCCN 3 |
| FR-M9-05.4 | Nếu mật khẩu bị nhập sai 5 lần liên tiếp, thì hệ thống phải khóa tài khoản. | Must | Active | Xử lý lỗi; NFR-SEC-01 |
| FR-M9-07 | Khi một đối tượng cần quét được tạo mới — nhân viên (kể cả nhân viên khoa lâm sàng), bộ dụng cụ, thiết bị, vị trí kệ, trạm, cuộn nhãn, lô chỉ thị — hệ thống phải tự sinh mã duy nhất theo tiền tố đối tượng (NV-, GS1 GIAI cho bộ, TB-, KE-, TR-, CN-…), không cho nhập tay mã, cho in thẻ/nhãn QR hoặc DataMatrix ngay từ bản ghi và ghi vào sổ đăng ký mã. | Must | Active | UC-33; SCR-33; API-M9-02; BRU-ID-006; phụ thuộc FR-M9-03, FR-M9-04, FR-M9-05, FR-M9-06. Nguồn: BR-M9; xem A-05 (R1–R8): đường in từ Desk, nhãn 50 × 30 mm, cấp mã cuộn `CN-`, vô hiệu mã khi `Retired` |
| FR-M9-07.1 | Hệ thống phải không cho sửa và không cấp lại mã đã cấp. | Must | Active | TCCN 2; BRU-ID-006 |
| FR-M9-07.2 | Khi đối tượng ngừng hoạt động, hệ thống phải vô hiệu mã nhưng giữ nguyên lịch sử tra cứu. | Must | Active | TCCN 2 |
| FR-M9-07.3 | Nếu mã quét tại trạm không do hệ thống sinh và không phải thẻ bệnh viện đã đăng ký, thì hệ thống phải từ chối và ghi log. | Must | Active | TCCN 3 |
| FR-M9-07.4 | Khi thẻ nhân viên có sẵn của bệnh viện được đăng ký làm mã thẻ, hệ thống phải chỉ chấp nhận nếu mã duy nhất và quét được; nếu trùng, thì hệ thống phải chặn. | Must | Active | Xử lý lỗi; BRU-ID-006 ngoại lệ |
| FR-M9-06 | Khi tính năng offline tại trạm được bật và trạm mất kết nối mạng, hệ thống phải lưu sự kiện quét vào hàng đợi cục bộ và tiếp tục hoạt động ≥ 4 giờ. | Must | Active | UC-33; SCR-33; API-M9-02; phụ thuộc FR-M9-03, FR-M9-04, FR-M9-05, FR-M9-07; NFR-AVAIL-02. Nguồn: BR-M9. [v1.11] chốt Must theo NFR-AVAIL-02 (OQ-08 đã chốt 2026-10-17) |
| FR-M9-06.1 | Khi kết nối được khôi phục, hệ thống phải đồng bộ hàng đợi cục bộ theo thứ tự thời gian và chuyển các xung đột cho R02 xử lý. | Must | Active | TCCN 2; [v1.11] chốt Must theo NFR-AVAIL-02 |
| FR-M9-06.2 | Trong khi trạm offline, hệ thống phải sinh Cycle ID từ dải mã đã cấp trước cho trạm. | Must | Active | TCCN 3; liên kết FR-M2-07.11; [v1.11] chốt Must theo NFR-AVAIL-02 |
| FR-M9-06.3 | Nếu khi đồng bộ phát hiện xung đột trạng thái, thì hệ thống phải giữ bản server và ghi NC. | Must | Active | Xử lý lỗi; [v1.11] chốt Must theo NFR-AVAIL-02 |
| FR-M9-08 | Khi người dùng bấm Đăng xuất hoặc rút/quét lại thẻ tại trạm, hệ thống phải kết thúc phiên, xóa dữ liệu phiên trên thiết bị dùng chung và ghi audit. | Must | Active | UC-33; SCR-33; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Authentication — logout chưa là FR; NFR-SEC-01 chỉ nói khóa phiên 10 phút |
| FR-M9-08.1 | Nếu một thẻ nhân viên được quét vào trạm thứ hai khi phiên ở trạm thứ nhất còn mở, thì hệ thống phải kết thúc phiên cũ và ghi audit (một thẻ – một phiên trạm). | Should | Active | UC-33; SCR-33; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Session management (concurrent sessions) |
| FR-M9-09 | Khi người dùng (tài khoản web) yêu cầu đổi mật khẩu/PIN, hệ thống phải yêu cầu xác thực lại giá trị cũ, áp dụng chính sách độ dài/độ phức tạp (#13 SEC) và ghi audit. | Must | Active | UC-33; SCR-33; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Authentication — change password/PIN |
| FR-M9-09.1 | Khi người dùng quên mật khẩu, hệ thống phải cho phép R10 (hoặc R02 với thẻ/PIN trạm) đặt lại và bắt buộc đổi ở lần đăng nhập kế tiếp; không gửi mật khẩu qua email/SMS dạng rõ. | Must | Active | UC-33; SCR-33; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Forgot/reset password (bệnh viện không dùng self-service email) |
| FR-M9-09.2 | Khi R10 vô hiệu hóa tài khoản/thẻ nhân viên nghỉ việc, hệ thống phải chấm dứt mọi phiên đang mở và giữ nguyên lịch sử audit gắn tài khoản đó. | Must | Active | UC-33; SCR-33; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Account deactivation (bổ sung FR-M9-07 "mã vô hiệu") |
| FR-M9-10 | Khi phát sinh sự kiện cần thông báo (lệnh thu hồi, chứng chỉ sắp hết hạn 60/30/7 ngày, kiểm định sắp hạn, bộ sắp/đạt cơ số, tồn kho dưới tối thiểu, lô/mẻ không đạt, đề nghị ghi đè), hệ thống phải gửi thông báo tới các vai trò được cấu hình theo từng loại sự kiện qua kênh in-app/PDA và tùy chọn email/SMS, ghi trạng thái đã gửi/đã đọc. | Must | Active | UC-38; SCR-42; EI-SW-002; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Notifications — hiện rải rác trong 14 FR, chưa có FR gốc về kênh, cấu hình người nhận, trạng thái gửi |
| FR-M9-10.1 | Nếu gửi email/SMS thất bại, thì hệ thống phải giữ thông báo in-app, thử lại theo lịch và ghi log lỗi gửi. | Should | Active | UC-38; SCR-42; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Unwanted behaviour cho FR-M9-10 |
| FR-M9-11 | Khi R10/R02 nhập dữ liệu danh mục ban đầu (dụng cụ, loại bộ & BOM, nhân sự & chứng chỉ, thiết bị & chương trình, vật tư, cơ số, khoa), hệ thống phải cho phép tải mẫu Excel, import theo lô, kiểm tra từng dòng và trả báo cáo lỗi theo dòng trước khi ghi sổ. | Must | Active | UC-39; SCR-43; EI-SW-007; NFR-PORT-02; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Data import / migration-seed for launch — cover.md yêu cầu bệnh viện bàn giao danh mục trước Sprint 1; mới chỉ FR-M6-01 có "nhập từ Excel mẫu" |
| FR-M9-11.1 | Khi import ảnh chụp thực tế hàng loạt (theo mã dụng cụ/loại bộ), hệ thống phải gắn ảnh đúng bản ghi theo tên file = mã và liệt kê mã không khớp. | Should | Active | UC-39; SCR-43; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: File & media handling — FR-M1-01/03 yêu cầu ảnh bắt buộc cho hàng trăm dụng cụ |
| FR-M9-12 | Khi R01/R10 yêu cầu xuất hồ sơ tiệt khuẩn theo kỳ (mẻ, chỉ thị, dữ liệu máy, cấp phát, sử dụng, audit) cho đoàn kiểm tra, hệ thống phải xuất gói PDF + dữ liệu có cấu trúc (Excel/CSV) kèm dấu thời gian, phục vụ lưu ≥ 10 năm độc lập với hệ thống. | Must | Active | UC-39; SCR-43; OTH-RET-001; NFR-PORT-02; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Data export / retention — NFR-COMP-01 yêu cầu lưu 10 năm nhưng chưa có FR xuất/lưu trữ |
| FR-M9-13 | Hệ thống phải cung cấp tìm kiếm, lọc theo trường, sắp xếp và phân trang trên mọi danh sách (bộ, gói, mẻ, phiếu, vật tư, NC), với ô quét mã làm phím tắt tìm kiếm. | Must | Active | UC-32; SCR-32 (áp dụng mọi danh sách); [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Search/filter/pagination — catalog "pagination on every list"; chưa là FR dù Frappe cung cấp sẵn |
| FR-M9-14 | Khi một màn hình trạm/PDA không có dữ liệu, đang tải, hoặc gặp lỗi (mạng, máy in, thiết bị ngoại vi), hệ thống phải hiển thị trạng thái rõ ràng bằng tiếng Việt, kèm hành động kế tiếp (thử lại, chuyển offline, gọi R02). | Must | Active | — / mọi UC trạm (UC-05..13, UC-16..18, UC-34..36); mọi SCR trạm/PDA; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Empty/error/loading states as requirements |
| FR-M9-15 | Khi người dùng cần trợ giúp tại trạm, hệ thống phải hiển thị hướng dẫn thao tác theo trạm (3–5 bước, ảnh) và cho phép gửi phản hồi/báo lỗi phần mềm tới R10 kèm ảnh chụp màn hình. | Could | Active | — / mọi UC trạm (UC-05..13, UC-16..18, UC-34..36); mọi SCR trạm/PDA; [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Help & support |
| FR-M9-16 | Khi tạo/sửa/xóa bản ghi danh mục, hệ thống phải xóa mềm (vô hiệu) thay vì xóa cứng với mọi đối tượng đã có giao dịch; chỉ R10 mới xóa cứng bản ghi chưa có giao dịch. | Must | Active | UC-33; SCR-33 (áp dụng mọi danh mục M1, M3–M7, M10); [NEW v1.11] duyệt chủ đầu tư 2026-10-17. Catalog: Soft-delete vs hard-delete (catalog); mở rộng NFR-SEC-03 cho master data |
| FR-M9-17 | Hệ thống phải có sẵn danh mục mã lỗi `<NHÓM>-<3 số>` khi cài app, mỗi mã có tên, mô tả, điều kiện phát sinh, trạm áp dụng, mức độ, hành động hệ thống, cách gỡ và hướng dẫn xử lý; viện sửa được nội dung, nâng cấp không ghi đè. | Must | Active | A-71 |
| FR-M9-18 | Khi R10 đổi cấu hình mã lỗi (bật/tắt, mức độ, số ngày cảnh báo, vai trò duyệt), hệ thống phải áp dụng ngay; hệ thống phải từ chối đổi mức độ hoặc tắt mã bị khóa. | Must | Active | A-71; OTH-LEG-003 |
| FR-M9-19 | Khi chặn hoặc cảnh báo theo mã lỗi ở trạm hoặc màn đăng nhập trạm, hệ thống phải hiển thị [Mã] – Tên – đối tượng liên quan và cách mở Hướng dẫn xử lý của mã. | Must | Active | A-71 |
| FR-M9-20 | Khi một mã lỗi phát sinh, hệ thống phải ghi Nhật ký lỗi gồm mã, trạm, người dùng, đối tượng, thời điểm, trạng thái, người duyệt, thời hạn; hệ thống phải có báo cáo thống kê theo mã, trạm, thời gian cho R01. | Must | Active | A-71 |
| FR-M9-21 | Hệ thống phải in được Danh mục mã lỗi theo trạm, lọc theo trạm hoặc mã, kèm Hướng dẫn xử lý. | Must | Active | A-71 |

#### 3.1.10 M10 — Quản lý chất thải y tế [NEW v1.11]

Phạm vi: chất thải y tế **rắn** phát sinh trong khuôn viên bệnh viện (mọi khoa), khoa KSNK là đầu mối giám sát; chất thải lỏng/khí ngoài phạm vi (§1.2.2). Căn cứ pháp lý: Thông tư 20/2021/TT-BYT (quản lý chất thải y tế trong phạm vi khuôn viên cơ sở y tế); Nghị định 08/2022/NĐ-CP (chứng từ chất thải nguy hại, giấy phép môi trường). Quy tắc nghiệp vụ mới: BRU-WST-001 phân loại không trộn; BRU-WST-002 thời gian lưu giữ tối đa; BRU-WST-003 chỉ bàn giao đơn vị có giấy phép còn hiệu lực; BRU-WST-004 đối chiếu kg thu gom – bàn giao (định nghĩa tại Appendix A). Priority Must trừ khi ghi khác; Status Active. Vai trò chính: R07 Nhân viên đồ vải & chất thải; R08 giao tại khoa; R02 giám sát; R09 hợp đồng/đơn giá; R01 báo cáo.

| ID | Requirement (EARS) | Priority | Status | Notes / rules |
| --- | --- | --- | --- | --- |
| FR-M10-01 | Khi R02/R10 lưu bản ghi Loại chất thải với nhóm theo TT 20/2021/TT-BYT (lây nhiễm: sắc nhọn, không sắc nhọn, nguy cơ lây nhiễm cao, giải phẫu — màu vàng; nguy hại không lây nhiễm — màu đen; thông thường — màu xanh; tái chế — màu trắng), bao bì/thùng chuẩn, khối lượng chuẩn túi (kg), đơn giá xử lý/kg có phiên bản và thời gian lưu giữ tối đa (giờ), hệ thống phải tạo bản ghi Loại chất thải ở trạng thái Đang dùng và đưa vào danh sách chọn/quét tại trạm thu gom. | Must | Active | UC-34; SCR-38; BRU-WST-001, BRU-WST-002; BRU-ID-006; liên kết FR-M7-03 (đơn giá có phiên bản), FR-M6-02 (túi/thùng là vật tư tiêu hao). Nguồn: Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT |
| FR-M10-01.1 | Nếu bản ghi Loại chất thải thiếu nhóm, bao bì/thùng chuẩn hoặc thời gian lưu giữ tối đa, thì hệ thống phải từ chối lưu và chỉ rõ trường thiếu. | Must | Active | Xử lý lỗi |
| FR-M10-01.2 | Khi nhóm chất thải được chọn, hệ thống phải tự gán mã màu theo TT 20/2021/TT-BYT (vàng/đen/xanh/trắng) và không cho sửa mã màu khác nhóm. | Must | Active | TT 20/2021 Điều 6; BRU-WST-001 |
| FR-M10-01.3 | Khi người dùng nhập thời gian lưu giữ tối đa, hệ thống phải gợi ý giá trị mặc định ≤ 48 giờ (lưu thường) và ≤ 7 ngày khi lưu lạnh ≤ 8°C, cho phép ghi đè bằng giá trị nhập tay có lý do và không áp đặt giá trị cứng khác (tham số theo loại, giống hạn lưu gói BRU-REP-009). | Must | Active | BRU-WST-002; TT 20/2021 Điều 8 |
| FR-M10-01.4 | Khi người dùng sửa đơn giá xử lý/kg của một loại, hệ thống phải tạo phiên bản đơn giá mới có ngày hiệu lực, giữ phiên bản cũ và không tính lại các phiếu bàn giao đã ghi sổ. | Must | Active | BRU-CST-002; liên kết FR-M10-05.4 (đơn giá hợp đồng ưu tiên) |
| FR-M10-01.5 | Khi một túi/thùng chất thải được tạo tại thu gom, hệ thống phải tự sinh mã QR duy nhất tiền tố CT- cho túi/thùng theo BRU-ID-006, không cho nhập tay và cho in nhãn QR ngay tại trạm. | Must | Active | BRU-ID-006; FR-M9-07; EI-HW-002 |
| FR-M10-02 | Khi R07 tại trạm/PDA thu gom quét thẻ nhân viên khoa giao (R08), chọn hoặc quét loại chất thải, nhập số túi/thùng và khối lượng (lấy từ cân điện tử RS-232/USB qua station agent hoặc nhập tay có xác nhận), hệ thống phải tạo Phiếu thu gom chất thải theo khoa – loại – số túi/thùng – kg với nhiều dòng trên một phiếu, sinh mã QR cho từng túi/thùng (FR-M10-01.5) và ghi người thu gom, người giao, thời điểm, vị trí khoa. | Must | Active | UC-34; SCR-38; BRU-WST-001; BRU-ID-006; EI-HW-004; cùng cơ chế cân với FR-M3-01. Nguồn: Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT |
| FR-M10-02.1 | Nếu cân điện tử không phản hồi hoặc trạm không có cân, thì hệ thống phải cho nhập tay khối lượng, bắt buộc tick xác nhận và ghi nguồn Nhập tay kèm người nhập. | Must | Active | Xử lý lỗi; NFR-AVAIL-04 |
| FR-M10-02.2 | Khi người thu gom đính ảnh túi/thùng hoặc điểm tập kết của khoa, hệ thống phải lưu ảnh kèm dòng phiếu (tùy chọn, không bắt buộc). | Should | Active | EI-HW-006 |
| FR-M10-02.3 | Hệ thống phải không cho một túi/thùng mang nhiều hơn một loại chất thải: mỗi dòng phiếu ứng với đúng một loại và các túi/thùng của dòng đó. | Must | Active | BRU-WST-001 (phân loại không trộn) |
| FR-M10-02.4 | Nếu người thu gom đánh dấu Phân loại sai cho một túi/thùng tại khoa (trộn loại, sai màu, vật sắc nhọn ngoài thùng), thì hệ thống phải tạo NC loại Phân loại sai kèm khoa, loại chất thải, ảnh (FR-M10-06) và chỉ cho thu gom túi đó sau khi khoa phân loại lại hoặc R02 xác nhận. | Must | Active | BRU-WST-001; liên kết FR-M2-21 |
| FR-M10-02.5 | Nếu thẻ nhân viên giao không do hệ thống sinh/đăng ký hoặc không thuộc khoa đang chọn, thì hệ thống phải từ chối dòng phiếu và ghi log. | Must | Active | BRU-ID-006; FR-M9-07.3 |
| FR-M10-02.6 | Khi phiếu thu gom được xác nhận, hệ thống phải ghi sổ phiếu, chuyển các túi/thùng sang trạng thái Đã thu gom, cộng kg vào tổng kg/khoa/loại trong ngày và cho in hoặc ký điện tử biên nhận với khoa. | Must | Active | TCCN; liên kết FR-M10-07, EI-UI-008 |
| FR-M10-03 | Khi R07 quét mã QR túi/thùng ở trạng thái Đã thu gom và quét mã vị trí kho chất thải (KE-) tương ứng loại, hệ thống phải ghi nhận nhập kho lưu giữ tạm theo loại – vị trí, tính thời gian lưu giữ từ thời điểm thu gom và hiển thị tồn kho chất thải theo loại, vị trí và thời gian còn lại. | Must | Active | UC-35; SCR-39; BRU-WST-002; BRU-ID-006. Nguồn: Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT |
| FR-M10-03.1 | Nếu vị trí kho được quét không được cấu hình cho loại chất thải của túi/thùng (ví dụ túi vàng vào khu đen), thì hệ thống phải từ chối và báo lỗi kèm vị trí đúng. | Must | Active | Xử lý lỗi; BRU-WST-001 |
| FR-M10-03.2 | Khi tính năng theo dõi nhiệt độ kho lạnh được bật, hệ thống phải ghi nhiệt độ kho lạnh từ nhập tay (≥ 2 lần/ngày) hoặc cảm biến; nếu nhiệt độ > 8°C quá 2 giờ liên tục `[đề xuất]`, thì hệ thống phải cảnh báo R07/R02 và áp lại thời gian lưu giữ tối đa của các túi/thùng trong kho đó về ngưỡng lưu thường (≤ 48 giờ). | Must | Active | BRU-WST-002; EI-HW-005; tương tự FR-M9-04 |
| FR-M10-03.3 | Khi thời gian lưu giữ của túi/thùng đạt 80% thời gian lưu giữ tối đa `[đề xuất]`, hệ thống phải hiển thị cảnh báo Sắp quá hạn lưu trên dashboard chất thải và gửi thông báo tới R07, R02. | Must | Active | BRU-WST-002; FR-M9-10 |
| FR-M10-03.4 | Nếu túi/thùng quá thời gian lưu giữ tối đa, thì hệ thống phải cảnh báo Quá hạn lưu mức đỏ, tạo NC quá hạn lưu và đưa túi/thùng đó lên đầu danh sách đề xuất bàn giao. | Must | Active | BRU-WST-002; FR-M10-06 |
| FR-M10-03.5 | Khi R07 lập phiếu bàn giao, hệ thống phải đề xuất danh sách túi/thùng theo FIFO (thu gom sớm nhất trước) theo từng loại và cảnh báo nếu người dùng bỏ qua túi/thùng sớm hơn. | Must | Active | TCCN; tương tự FEFO BRU-REP-008 |
| FR-M10-04 | Khi R07 lập Phiếu bàn giao chất thải chọn đơn vị xử lý, quét các túi/thùng (hoặc chọn theo loại từ kho lưu giữ) và nhập khối lượng bàn giao theo loại (cân hoặc nhập tay có xác nhận), hệ thống phải tạo phiếu theo loại – số túi/thùng – kg, đối chiếu tổng kg thu gom của các túi/thùng với kg bàn giao, chuyển túi/thùng sang Đã bàn giao và tính chi phí xử lý = kg × đơn giá phiên bản hiệu lực của loại (hoặc đơn giá hợp đồng, FR-M10-05.4), ghi vào chi phí thuê ngoài M7. | Must | Active | UC-36; SCR-40; BRU-WST-003, BRU-WST-004; FR-M7-01, FR-M7-02; NĐ 08/2022/NĐ-CP. Nguồn: Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT |
| FR-M10-04.1 | Nếu chênh lệch giữa kg bàn giao và kg thu gom của phiếu vượt ngưỡng cấu hình (mặc định 5%, R02 nhập tay), thì hệ thống phải cảnh báo R02, yêu cầu lý do và tạo NC chênh lệch khối lượng trước khi cho ghi sổ. | Must | Active | BRU-WST-004; FR-M10-06 |
| FR-M10-04.2 | Khi phiếu bàn giao được xác nhận, hệ thống phải yêu cầu ký điện tử (quét thẻ hoặc chữ ký cảm ứng) của R07 và đại diện đơn vị xử lý, hoặc ảnh biên bản bàn giao có chữ ký, kèm thời điểm và biển số xe vận chuyển (nếu có). | Must | Active | EI-UI-008; EI-HW-006 |
| FR-M10-04.3 | Khi phiếu bàn giao có chất thải nguy hại (lây nhiễm hoặc nguy hại không lây nhiễm), hệ thống phải yêu cầu nhập số chứng từ chất thải nguy hại, đơn vị vận chuyển, đơn vị xử lý, số hợp đồng và đính bản scan chứng từ trước khi ghi sổ; chất thải thông thường/tái chế không bắt buộc chứng từ. | Must | Active | NĐ 08/2022/NĐ-CP; TT 20/2021 Điều 10 |
| FR-M10-04.4 | Nếu đơn vị xử lý được chọn không có giấy phép còn hiệu lực cho một loại chất thải trong phiếu, thì hệ thống phải chặn ghi sổ và chỉ rõ loại bị chặn. | Must | Active | BRU-WST-003; FR-M10-05 |
| FR-M10-04.5 | Khi phiếu bàn giao được ghi sổ, hệ thống phải tạo bản ghi chi phí thuê ngoài xử lý chất thải phân bổ cho các khoa phát sinh theo tỷ lệ kg thu gom (FR-M7-02) và cho in phiếu bàn giao PDF kèm chứng từ. | Must | Active | FR-M7-01/02; EI-HW-007 |
| FR-M10-04.6 | Nếu phiếu bàn giao cần sửa sau khi ghi sổ, thì hệ thống phải chỉ cho hủy (tạo bản ghi hủy) và lập phiếu điều chỉnh, không sửa đè. | Must | Active | OTH-LEG-002 |
| FR-M10-05 | Khi R09/R02 lưu bản ghi Đơn vị xử lý chất thải với tên, mã số thuế, số và hiệu lực giấy phép môi trường (vận chuyển/xử lý chất thải nguy hại), danh sách loại chất thải được phép, hợp đồng (số, hiệu lực, đơn giá/kg theo loại) và file đính kèm, hệ thống phải tạo bản ghi ở trạng thái Đang hiệu lực và đưa vào danh sách chọn khi lập phiếu bàn giao. | Must | Active | UC-36; SCR-40; BRU-WST-003; NĐ 08/2022/NĐ-CP. Nguồn: Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT |
| FR-M10-05.1 | Nếu bản ghi thiếu số giấy phép, hiệu lực giấy phép hoặc danh sách loại chất thải được phép, thì hệ thống phải từ chối lưu. | Must | Active | Xử lý lỗi |
| FR-M10-05.2 | Khi giấy phép hoặc hợp đồng của đơn vị xử lý còn 60/30/7 ngày hiệu lực, hệ thống phải gửi thông báo tới R02 và R09. | Must | Active | FR-M9-10; tương tự FR-M4-02 |
| FR-M10-05.3 | Nếu giấy phép hoặc hợp đồng hết hiệu lực, thì hệ thống phải tự chuyển đơn vị sang Hết hiệu lực cho các loại tương ứng và chặn chọn đơn vị đó khi bàn giao các loại đó. | Must | Active | BRU-WST-003 |
| FR-M10-05.4 | Khi hợp đồng của đơn vị xử lý có đơn giá hiệu lực cho một loại chất thải, hệ thống phải dùng đơn giá hợp đồng thay cho đơn giá mặc định của loại (FR-M10-01.4) khi tính chi phí phiếu bàn giao, có phiên bản theo ngày hiệu lực. | Must | Active | BRU-CST-002 |
| FR-M10-06 | Khi người dùng ghi nhận sự cố chất thải (tràn đổ, phơi nhiễm vật sắc nhọn, phân loại sai, quá hạn lưu, chênh lệch khối lượng), hệ thống phải tạo NC dùng chung cơ chế FR-M2-21/FR-M2-22 với loại sự cố chất thải, loại chất thải, khoa, vị trí, người liên quan, ảnh và mức độ, rồi mở CAPA theo dõi tới khi đóng. | Must | Active | UC-37; SCR-41; FR-M2-21, FR-M2-22; ERPNext Non Conformance/Quality Action. Nguồn: Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT |
| FR-M10-06.1 | Khi sự cố là phơi nhiễm vật sắc nhọn, hệ thống phải yêu cầu ghi mã nhân viên bị phơi nhiễm, thời điểm, nguồn phơi nhiễm, hiển thị nhắc quy trình xử lý sau phơi nhiễm theo TT 16/2018/TT-BYT và thông báo ngay R01, R02. | Must | Active | TT 16/2018; FR-M9-10; dữ liệu nhân sự theo OTH-PRIV-002 |
| FR-M10-06.2 | Nếu một khoa có NC phân loại sai lặp ≥ 3 lần trong 30 ngày `[đề xuất]`, thì hệ thống phải cảnh báo R01 và đưa khoa vào báo cáo tuân thủ phân loại (FR-M10-07). | Should | Active | BRU-WST-001 |
| FR-M10-06.3 | Khi NC được tạo tự động từ FR-M10-02.4, FR-M10-03.4 hoặc FR-M10-04.1, hệ thống phải tự điền loại sự cố, khoa, loại chất thải và mã phiếu nguồn vào NC. | Must | Active | TCCN |
| FR-M10-07 | Khi R01/R02 chọn kỳ (ngày/tháng/quý/năm), khoa hoặc loại chất thải, hệ thống phải hiển thị và xuất (PDF/Excel) báo cáo kg theo khoa/loại/ngày/tháng, chênh lệch kg thu gom – bàn giao, chi phí xử lý và chi phí/kg, tỷ lệ túi/thùng tuân thủ thời gian lưu giữ, danh sách sự cố, và mẫu báo cáo định kỳ quản lý chất thải y tế theo TT 20/2021/TT-BYT. | Must | Active | UC-37; SCR-41; FR-M9-01, FR-M9-02; NFR-COMP-01. Nguồn: Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT |
| FR-M10-07.1 | Khi dashboard FR-M9-01 được mở bởi R01/R02/R07, hệ thống phải hiển thị khối chất thải: kg hôm nay theo loại, túi/thùng sắp/quá hạn lưu, phiếu bàn giao chờ chứng từ, khoa phát sinh bất thường (FR-M10-08). | Must | Active | FR-M9-01 tích hợp |
| FR-M10-07.2 | Nếu kỳ báo cáo chưa được khóa, thì hệ thống phải đóng dấu Tạm trên bản xuất. | Must | Active | Tương tự FR-M9-02.1 |
| FR-M10-07.3 | Khi R08 mở Cổng khoa, hệ thống phải hiển thị kg chất thải theo loại của khoa mình theo ngày/tháng và các NC phân loại sai của khoa. | Should | Active | EI-UI-004; NFR-SEC-07 (chỉ khoa mình) |
| FR-M10-07.4 | Hệ thống phải lưu và cho tra cứu phiếu thu gom, phiếu bàn giao và chứng từ chất thải nguy hại theo số chứng từ, đơn vị xử lý, khoa và kỳ, cùng chính sách lưu trữ với hồ sơ KSNK (OTH-RET-001). | Must | Active | OTH-RET-001; NĐ 08/2022 |
| FR-M10-08 | Khi R02 cấu hình định mức túi/thùng theo khoa – loại (liên kết vật tư tiêu hao M6: túi theo màu, thùng sắc nhọn) và kg trung bình/giường/ngày tham chiếu, hệ thống phải lưu định mức theo khoa – loại có ngày hiệu lực và dùng định mức để so sánh với số liệu thu gom và cấp phát vật tư. | Must | Active | UC-37; SCR-41; FR-M6-02, FR-M6-04, FR-M6-06; tương tự định mức đồ vải FR-M3-06. Nguồn: Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT |
| FR-M10-08.1 | Khi phiếu thu gom được ghi sổ, hệ thống phải so sánh kg/ngày của khoa theo loại với trung bình 30 ngày gần nhất; nếu lệch quá ±30% (tham số, R02 nhập tay) thì hệ thống phải cảnh báo Phát sinh bất thường tới R02 và ghi vào báo cáo FR-M10-07. | Must | Active | TCCN |
| FR-M10-08.2 | Khi túi/thùng sắc nhọn được cấp cho khoa từ kho M6 (FR-M6-04), hệ thống phải đối chiếu số túi/thùng cấp với số túi/thùng thu gom của khoa theo kỳ và báo chênh lệch vượt 10% `[đề xuất]`. | Should | Active | FR-M6-04; FR-M6-06 |
| FR-M10-08.3 | Nếu khoa chưa có định mức, thì hệ thống phải chỉ cảnh báo Thiếu định mức trên báo cáo và không chặn thu gom. | Must | Active | Xử lý lỗi |
| FR-M10-08.4 | Khi dữ liệu lịch sử của khoa dưới 30 ngày, hệ thống phải tính trung bình trên số ngày hiện có và đánh dấu Chưa đủ dữ liệu trên cảnh báo. | Must | Active | Xử lý lỗi |

#### 3.1.11 Kiểm đếm

| Phân hệ | Số FR gốc (d05 §2.1 v1.10) | Số FR gốc trong mục 3.1 (v1.11) | Số câu EARS (gốc + con) |
| --- | --- | --- | --- |
| M1 Danh mục dụng cụ & bộ dụng cụ | 9 | 9 | 51 |
| M2 Chuỗi tái xử lý & truy xuất | 25 | 25 | 156 (gồm 5 câu quy tắc chung FR-M2-00.1–.5 từ BRU-FLOW-002/003) |
| M3 Quản lý đồ vải | 6 | 6 | 26 |
| M4 Nhân sự & chứng chỉ | 4 | 4 | 20 |
| M5 Thiết bị & bảo trì | 6 | 6 | 25 |
| M6 Kho vật tư tiêu hao | 6 | 6 | 23 |
| M7 Chi phí & giá thành tái xử lý | 6 | 6 | 23 |
| M8 Cơ số & kiểm soát vượt ngưỡng | 4 | 4 | 18 |
| M9 Báo cáo, dashboard & quản trị | 7 | 16 (+9 FR-M9-08..16, duyệt 2026-10-17) | 40 |
| M10 Quản lý chất thải y tế [NEW v1.11] | 0 | 8 (FR-M10-01..08) | 45 |
| **Tổng** | **73** | **90** | **427** |

**Bộ Số Chuẩn BA v1.10 → v1.11: N_MOD 9→10, N_FR 73→90, N_NFR 14→35, N_UC 33→39, N_SCR 37→43** (N_BRU 45→49 với BRU-WST-001..004). Bước sau cập nhật #00 CHG theo dòng này.

**BRU chưa được FR nào tham chiếu:** không có — toàn bộ 45 BRU của d04 (và 4 BRU-WST-001..004 mới của M10, tham chiếu tại FR-M10-01..06) (BRU-ID-001…006, BRU-FLOW-001…004, BRU-REP-001…016, BRU-PAR-001…005, BRU-LIN-001…004, BRU-HR-001…002, BRU-EQP-001…003, BRU-INV-001…002, BRU-CST-001…003) đều xuất hiện trong cột Notes / rules hoặc đã được gộp vào câu EARS. Các BRU chỉ truy vết tới UC mà không tới FR trong d04 (BRU-ID-004, BRU-FLOW-002, BRU-FLOW-003, BRU-REP-009, BRU-PAR-003, BRU-LIN-001, BRU-LIN-003) đã được gán FR ở đây: BRU-ID-004 → FR-M2-07.5/.6; BRU-FLOW-002/003 → FR-M2-00.1–.5; BRU-REP-009 → FR-M1-03.4/.5, FR-M2-07.7/.8; BRU-PAR-003 → FR-M2-05.3, FR-M8-03.1; BRU-LIN-001 → FR-M3-01.1; BRU-LIN-003 → FR-M3-03.1/.2.

**Điểm cần rà soát (mâu thuẫn hoặc chưa nhất quán giữa d05 và d04, chưa tự ý sửa):**

| # | Nội dung | Vị trí | Cách xử lý trong mục 3.1 |
| --- | --- | --- | --- |
| 1 | Ngưỡng chặn sinh Cycle ID khi chưa bảo dưỡng: d05 FR-M1-09 "hoãn quá 3 chu trình → chặn"; d04 BRU-REP-014 "quá ngưỡng 20% → chặn; R02 hoãn tối đa 3 chu trình cho ca mổ khẩn". | FR-M1-09, BRU-REP-014 | Gộp cả hai điều kiện (OR) tại FR-M1-09.6; cần BA xác nhận quy tắc cuối. **Amendment A-02 (2026-10-20, FEAT-018), tạm — trình CĐT 20/10/2026:** đến hạn khi bộ đếm ≥ ngưỡng; chặn sinh Cycle ID khi bộ đếm > ngưỡng × 1,2 **hoặc** số lần hoãn ≥ 3, trừ khi lần đóng gói này chọn Đã bảo dưỡng. Chi tiết: architecture.md, Revision History A-02 và §5.3.1 (M1). |
| 2 | Định dạng Set ID: BRU-ID-001 nói GIAI; FR-M1-05 nói "GIAI AI 8004 hoặc (01)+(21)" — (01)+(21) là GTIN + serial (SGTIN), không phải GIAI. | FR-M1-05, BRU-ID-001 | ✅ Đã chốt 2026-10-17: Set ID = GS1 GIAI (AI 8004) duy nhất; đã sửa FR-M1-05, §1.4, §2.5, EI-SW-003, Glossary. |
| 3 | Mã hóa Cycle ID: FR-M2-07/BRU-ID-002 nói GS1 DataMatrix (01)(11)(17)(21); NFR-COMP-02 nói "Code-128 hoặc DataMatrix". | FR-M2-07, NFR-COMP-02 | ✅ Đã chốt 2026-10-17: Cycle ID = GS1 DataMatrix (01)(11)(17)(21) duy nhất; đã sửa NFR-COMP-02, §2.5, OQ-06. |
| 4 | Trạng thái được tiếp nhận tại T1: FR-M2-02 chỉ cho "Tại khoa" hoặc "Đã sử dụng", nhưng FR-M2-14 và FR-M2-17 đặt Set Unit sang "Chờ tiếp nhận" — trạng thái này không có trong danh sách hợp lệ của FR-M2-02. | FR-M2-02, FR-M2-14, FR-M2-17 | Giữ nguyên câu chữ d05; cần bổ sung "Chờ tiếp nhận" vào FR-M2-02 hoặc thống nhất tên trạng thái. **Amendment A-10 (2026-10-22, FEAT-025), đã chốt (D1, chủ đầu tư/người dùng 22/10/2026):** thêm trạng thái Set Unit `Awaiting Receipt` (Chờ tiếp nhận), chỉ `core.step_gate.return_to_receipt` đặt; FR-M2-14 và FR-M2-17 dùng chung; T1 (FEAT-019) phải nhận trạng thái này khi tiếp nhận. Chi tiết: architecture.md, Revision History A-10 và §5.3.1 (M2). **A-13 (24/10/2026): FR-M2-02 đã sửa** nhận Mới tạo, Tại khoa, Chờ tiếp nhận. |
| 5 | Hạn sử dụng gói: FR-M2-07 "= ngày đóng gói + hạn nhập tay của loại gói"; FR-M1-03 cho phép Loại bộ ghi đè hạn lưu ngắn hơn. Chưa nói rõ giá trị nào thắng khi sinh Cycle ID. | FR-M2-07, FR-M1-03, BRU-REP-009 | FR-M2-07.7 viết "hạn lưu đang áp dụng"; cần chốt thứ tự ưu tiên (Loại bộ ghi đè < Loại gói). **Amendment A-02 (2026-10-20, FEAT-018), tạm — trình CĐT 20/10/2026:** hạn dùng = ngày đóng gói + min(hạn loại gói, hạn ghi đè của loại bộ); loại bộ không ghi đè (0 hoặc trống) thì dùng hạn loại gói; loại gói chưa có hạn lưu thì không chọn được; số ngày áp dụng và nguồn được snapshot vào Pack. Chi tiết: architecture.md, Revision History A-02 và §5.3.1 (M2). |
| 6 | Thời hạn mở khóa máy tạm: FR-M5-06 "≤ 24 giờ"; BRU-EQP-002 chỉ nói "có lý do và thời hạn". | FR-M5-06, BRU-EQP-002 | Theo d05 (24 giờ) vì cụ thể hơn. |
| 7 | Ngưỡng cảnh báo sớm mặc định "10% hoặc 5 lần" chỉ có ở BRU-PAR-003; FR-M8-01 không nêu mặc định. | FR-M8-01, FR-M8-03, BRU-PAR-003 | Đưa mặc định vào FR-M8-03.1 và FR-M2-05.3. |
| 8 | BRU-FLOW-002 ngoại lệ (R02 chuyển trạng thái thủ công) không được FR nào trong d05 mô tả; d04 §3 bổ sung điều kiện "sự cố có mã ticket" + "Audit + NC". | d04 §3 | Thêm FR-M2-00.3 (ID mới dạng .x, không phải FR gốc). |
| 9 | Trạng thái FR trong d05 là "Đang Review"; mục này đặt Status = Active theo yêu cầu import. | Toàn bộ | ✅ Chủ đầu tư duyệt toàn bộ 2026-10-17 (SRS v1.11 Finalized); FR-M9-08..16, FR-M10-01..08 và 21 NFR mới cũng Active. |
| 10 | FR-M9-06 offline: Should (bảng 2.1 d05) vs NFR-AVAIL-02 Must. | FR-M9-06, NFR-AVAIL-02 | ✅ Đã chốt 2026-10-17: Must (mọi dòng con), theo NFR-AVAIL-02; RTM đã bỏ ⚠. |

### 3.2 External interface requirements

Nguồn: #05 §1, #05 §1.1, #12 §2, §4, §5. Ưu tiên theo MoSCoW; Status `Active` trừ khi ghi khác.

#### 3.2.1 User interfaces

| ID | Requirement | Priority | Status | Nguồn |
| :-- | :---------- | :------- | :----- | :---- |
| EI-UI-001 | Hệ thống shall cung cấp **giao diện Web desktop** (Frappe Desk tùy biến) cho R01, R02, R09, R10 phục vụ quản trị, danh mục, kho, chi phí, dashboard, báo cáo; chạy trên trình duyệt Chromium hiện hành trên LAN bệnh viện. | Must | Active | #05 §1; #12 §2 |
| EI-UI-002 | Hệ thống shall cung cấp **giao diện trạm quét cảm ứng (kiosk)** full-screen cho T1–T7, trạm đồ vải và trạm thu gom/kho chất thải (M10), với ô quét luôn có focus, stepper theo bước, nút in; tuân thủ NFR-USAB-01 (nút ≥ 48 px, ≤ 3 chạm, dùng được khi đeo găng/màn hình ướt). | Must | Active | #05 §1; #12 §2; NFR-USAB-01 |
| EI-UI-003 | Hệ thống shall cung cấp **PWA cho PDA Android 12+** phục vụ T1 (tiếp nhận), T5 (nạp mẻ), T7 (cấp phát), T8 (sử dụng) với hàng đợi offline (IndexedDB) và đồng bộ idempotent (X-Idempotency-Key). | Must | Active | #12 §2; FR-M9-06 |
| EI-UI-004 | Hệ thống shall cung cấp **Cổng khoa** (trang web đơn giản) cho R08 để xem phiếu cấp phát, thông báo thu hồi và dữ liệu khoa mình. | Should | Active | #12 §5.1 (Website/Portal Page) |
| EI-UI-005 | Khi người dùng quét thẻ tại trạm, hệ thống shall xác thực năng lực trạm (DT-COMP) và chứng chỉ còn hạn (DT-CERT) trước khi mở phiên trạm 8 giờ (DF-7). | Must | Active | #12 §3 DF-7; BRU-HR-001 |
| EI-UI-006 | Hệ thống shall hiển thị toàn bộ giao diện bằng tiếng Việt với thuật ngữ theo QĐ 3671/QĐ-BYT; nhãn in hỗ trợ thêm tiếng Anh. | Must | Active | NFR-USAB-02 |
| EI-UI-007 | Khi một thao tác quét bị chặn (sai chiều, cổng bước chưa Đạt, mã hết hiệu lực, vượt cơ số), giao diện trạm shall hiển thị cảnh báo đỏ toàn màn hình kèm lý do và không ghi nhận giao dịch. | Must | Active | FR-M2-25; BRU-FLOW-002 |
| EI-UI-008 | Hệ thống shall cho phép **ký điện tử** tại cấp phát bằng quét thẻ hoặc chữ ký cảm ứng trên màn hình trạm/PDA (trường Signature). | Must | Active | FR-M2-15; #12 §5.1 |

Chi tiết 37 màn hình gốc (SCR-01..37) và hệ thống thiết kế: #09 UI, #10 PROTO, #17 — đầu vào cho `ux-foundations`/`ui-design`. [v1.11] Thêm 6 màn hình mới chưa có trong #09: SCR-38 Trạm thu gom chất thải; SCR-39 Kho lưu giữ tạm chất thải; SCR-40 Bàn giao chất thải & danh mục đơn vị xử lý; SCR-41 Báo cáo/dashboard chất thải & sự cố; SCR-42 Trung tâm thông báo; SCR-43 Import/Export danh mục & hồ sơ lưu trữ. Tổng 43 SCR.

#### 3.2.2 Hardware interfaces

| ID | Requirement | Priority | Status | Nguồn |
| :-- | :---------- | :------- | :----- | :---- |
| EI-HW-001 | Hệ thống shall nhận chuỗi quét từ **máy quét mã vạch/2D** qua HID keyboard wedge hoặc serial (qua station agent), đọc được GS1 DataMatrix, Code-128 và QR. | Must | Active | #12 §4; NFR-INT-01 |
| EI-HW-002 | Hệ thống shall gửi lệnh in **ZPL hoặc TSPL** tới máy in nhãn nhiệt chuyển 300 dpi qua TCP 9100 (raw socket / CUPS) để in nhãn gói, thẻ Set ID, nhãn QR mẻ, thẻ nhân viên, mã kệ/trạm/cuộn nhãn. | Must | Active | #12 §2, §4 |
| EI-HW-003 | Hệ thống shall quản lý **hai loại nhãn** (`VT-NHAN-HAP` hấp hơi nước 134°C; `VT-NHAN-PLASMA` plasma H2O2): mỗi máy in/cuộn khai báo loại nhãn đang nạp; trạm có thể có 2 máy in hoặc 1 máy in đổi cuộn có xác nhận bằng quét mã cuộn; in sai loại bị chặn. | Must | Active | #12 §4; FR-M2-08; BRU-REP-011 |
| EI-HW-004 | Hệ thống shall nhận số cân từ **cân điện tử** qua RS-232/USB thông qua station agent tại trạm thu gom/cấp phát đồ vải và trạm thu gom/bàn giao chất thải (M10); cho phép nhập tay có xác nhận khi cân không kết nối. | Must | Active | #12 §4; FR-M3-01; FR-M10-02, FR-M10-04 |
| EI-HW-005 | Hệ thống shall nhận dữ liệu **cảm biến môi trường** (nhiệt độ, độ ẩm, áp suất chênh) qua Modbus/HTTP cho từng khu; khi không có cảm biến, cho phép nhập tay 2 lần/ngày. | Could | Active | #12 §4; FR-M9-04 |
| EI-HW-006 | Hệ thống shall nhận **ảnh chụp** (bản in máy, biểu đồ mẻ, ảnh bất thường) từ camera PDA hoặc tải lên từ trạm (trường Attach Image). | Must | Active | FR-M2-10; FR-M2-23 |
| EI-HW-007 | Hệ thống shall in **phiếu** (phiếu cấp phát, phiếu kiểm đếm, sổ tiệt khuẩn điện tử) ra máy in văn phòng qua Print Format (PDF). | Must | Active | #12 §2 Print server |
| EI-HW-008 | Khi máy in đúng loại nhãn không phản hồi, hệ thống shall giữ Cycle ID/Set ID đã sinh, đưa lệnh in vào hàng đợi và cho in lại sau; không tạo mã mới và không in tạm trên loại nhãn khác. | Must | Active | FR-M1-05; FR-M2-08 |

#### 3.2.3 Software interfaces

| ID | Requirement | Priority | Status | Nguồn |
| :-- | :---------- | :------- | :----- | :---- |
| EI-SW-001 | Với máy rửa/máy tiệt khuẩn **kết nối được**, hệ thống shall nhận dữ liệu chu trình (tham số, biểu đồ, cảnh báo, kết quả) qua **station agent** đọc CSV export hoặc API của hãng và đính vào mã lô/mã mẻ với nguồn `Tự động`. Với máy không kết nối được, dữ liệu nhập tay bắt buộc có xác nhận (FR-M2-10). | Must | Active | #12 §4; FR-M2-24 |
| EI-SW-002 | Hệ thống shall gửi thông báo qua **email (SMTP)** và/hoặc **SMS gateway** cho các sự kiện: thu hồi, khóa máy, chứng chỉ/kiểm định sắp hết hạn, tồn kho tối thiểu, đề nghị ghi đè, [v1.11] túi chất thải sắp/quá hạn lưu, giấy phép đơn vị xử lý sắp hết hạn; push (Firebase) là tùy chọn. Cấu hình người nhận theo loại sự kiện và trạng thái gửi/đọc theo FR-M9-10. | Must | Active | #12 §2, §4; FR-M9-10 |
| EI-SW-003 | Hệ thống shall sinh và giải mã **GS1 DataMatrix** (GIAI AI 8004 duy nhất cho Set ID; (01)(11)(17)(21) duy nhất cho Cycle ID — chốt 2026-10-17; QR nội bộ cho mã đối tượng NV-/TB-/KE-/TR-/CN-/CT-) bằng thư viện phía server hoặc mã hóa tại máy in. | Must | Active | #12 §5.4; BRU-ID-001/002 |
| EI-SW-004 | Hệ thống shall cung cấp **REST `/api/resource` và RPC `/api/method/cssd.v1.*`** (40 endpoint theo #11) với xác thực API Key/Secret cho station agent và PWA; mọi RPC ghi nhận trạm là idempotent theo `X-Idempotency-Key`. | Must | Active | #12 §1, §5.1; #11 |
| EI-SW-005 | Hệ thống shall **không tích hợp HIS/EMR** trong phiên bản này nhưng giữ API `cssd.v1` sẵn sàng mở cho giai đoạn sau. | Must | Active | #01 §4.2; #12 §4 |
| EI-SW-006 | Hệ thống shall xuất dữ liệu giá thành, đề nghị mua và báo cáo ra **Excel/CSV** cho ERP bệnh viện (kế toán/mua sắm); API ở giai đoạn sau. | Must | Active | #12 §4 |
| EI-SW-007 | Hệ thống shall nhập dữ liệu danh mục dụng cụ, BOM, cơ số, bảng giá từ **Excel mẫu** qua Data Import, kiểm tra từng dòng, báo lỗi dòng sai và nhập các dòng đúng. | Must | Active | #12 §5.1; UC-01 A1 |
| EI-SW-008 | Hệ thống shall sử dụng **Frappe HR (hrms)** cho Employee, Shift Type/Assignment, Employee Skill Map, Training Event/Result, Employee Checkin phục vụ M4. | Must | Active | #12 §5.3 |
| EI-SW-009 | Hệ thống shall tận dụng module ERPNext **Stock, Buying, Assets, Accounts, Quality Management** theo ánh xạ #12 §5.2 (tiêu hao theo mẻ = Stock Entry Material Issue; NC/CAPA = Non Conformance + Quality Action; test ngày/chỉ thị = Quality Inspection). | Should | Active | #12 §5.2 |

#### 3.2.4 Communications interfaces

| ID | Requirement | Priority | Status | Nguồn |
| :-- | :---------- | :------- | :----- | :---- |
| EI-COM-001 | Mọi kết nối giữa trạm/PDA/web và server shall dùng **HTTPS (TLS nội bộ)** qua Nginx. | Must | Active | #12 §5; #13 §3 |
| EI-COM-002 | PDA shall chỉ kết nối **SSID KSNK**; máy in nhãn nằm trong **VLAN thiết bị**; trạm kiosk khóa hệ điều hành. | Must | Active | #13 §3 |
| EI-COM-003 | API key của station agent shall được **xoay 90 ngày**. | Must | Active | #13 §3 |
| EI-COM-004 | Khi mất kết nối mạng, trạm/PDA shall tiếp tục ghi nhận cục bộ ≥ 4 giờ và đồng bộ theo thứ tự thời gian khi kết nối lại; xung đột đưa R02 xử lý (DF-6). | Should | Active | FR-M9-06; NFR-AVAIL-02; #12 §3 DF-6 |
| EI-COM-005 | Máy in nhãn shall nhận lệnh qua **TCP 9100**; cân qua **RS-232/USB** cục bộ tại PC trạm (station agent); cảm biến qua **Modbus/HTTP**. | Must | Active | #12 §4 |
| EI-COM-006 | Hệ thống shall gửi email qua **SMTP** và SMS qua **SMS gateway** của bệnh viện. | Must | Active | #12 §4 |

### 3.3 Non-functional requirements

#### 3.3.1 NFR import từ BA v1.10 (14 NFR, giữ ID gốc)

Nguồn: #05 §3. Cột *Requirement* giữ nguyên ngưỡng gốc; dòng có `[chuẩn hóa]` là phần viết lại để đo được, kèm nguyên văn gốc để người dùng duyệt. Cách kiểm chứng gốc giữ trong cột *Nguồn*.

| ID | Category (ISO 25010) | Requirement (metric, target, condition) | Priority | Status | Nguồn |
| :-- | :------- | :-------------------------------------- | :------- | :----- | :---- |
| NFR-PERF-01 | Performance efficiency | Thời gian từ khi quét mã đến khi màn hình trạm phản hồi (xác nhận hoặc từ chối) ≤ 1 giây ở P95, đo tại UAT dưới tải NFR-PERF-02 bằng JMeter/Locust. Áp dụng M2, M8. | Must | Active | #05 NFR-PERF-01; kiểm chứng: load test UAT, P95 |
| NFR-PERF-02 | Performance efficiency (capacity) | Hệ thống phục vụ ≥ 40 trạm/thiết bị cầm tay hoạt động đồng thời, ≥ 600 mẻ/tháng, ≥ 3.000 Cycle ID/ngày mà vẫn đạt NFR-PERF-01. `[chuẩn hóa]` gốc ghi "Phân hệ áp dụng: M6" — đề xuất áp dụng toàn hệ thống (M2, M6, M8, M9). | Must | Active | #05 NFR-PERF-02; kiểm chứng: load test UAT |
| NFR-AVAIL-01 | Reliability (availability) | Uptime ≥ 99,5%/tháng (≈ ≤ 3,6 giờ downtime/tháng) tính trên vận hành 24/7; bảo trì có kế hoạch nằm ngoài giờ cao điểm và được báo trước. `[chuẩn hóa]` gốc: "≥ 99,5%/tháng trong giờ vận hành 24/7" — cần xác nhận downtime bảo trì có kế hoạch có tính vào 0,5% hay không (OQ-14). | Must | Active | #05 NFR-AVAIL-01; kiểm chứng: giám sát uptime |
| NFR-AVAIL-02 | Reliability (fault tolerance) | Khi mất mạng, trạm/PDA tiếp tục quét và ghi nhận cục bộ ≥ 4 giờ liên tục; khi kết nối lại, đồng bộ tự động theo thứ tự thời gian, không mất giao dịch, xung đột đưa R02 xử lý. Diễn tập mất mạng tại UAT. | Must | Active | #05 NFR-AVAIL-02; FR-M9-06 (Must từ v1.11, OQ-08 ✅ đã chốt 2026-10-17) |
| NFR-SEC-01 | Security (authentication) | Đăng nhập web bằng tài khoản/mật khẩu (≥ 10 ký tự, đổi 90 ngày) hoặc tại trạm bằng thẻ nhân viên duy nhất; khóa tài khoản sau 5 lần sai; phiên trạm 8 giờ, tự khóa sau 10 phút không thao tác; R01/R02/R09/R10 bật 2FA; PIN phê duyệt 6 số băm bcrypt. `[chuẩn hóa]` gốc chỉ nêu "tài khoản hoặc thẻ; khóa 5 lần; tự khóa 10 phút" — bổ sung chi tiết từ #13 §3. | Must | Active | #05 NFR-SEC-01; #13 §3; kiểm chứng: pentest nội bộ, rà soát audit |
| NFR-SEC-02 | Security (confidentiality) | Mã bệnh nhân lưu mã hóa AES-256 (trường Password); hiển thị ẩn 4 ký tự giữa; chỉ R01, R02 xem đầy đủ với lý do và ghi audit; 100% bản ghi DT-USAGE kiểm tra tại UAT không lộ mã ở dạng rõ trong CSDL/log. `[chuẩn hóa]` gốc: "mã hóa khi lưu, ẩn một phần, chỉ vai trò được phép xem" — bổ sung AES-256 và quy tắc ẩn từ #08, #13. | Must | Active | #05 NFR-SEC-02; #08 §4; #13 §2.2 |
| NFR-SEC-03 | Security (accountability) | Mọi thao tác tạo/sửa/ghi sổ/hủy/đăng nhập/từ chối/ghi đè ghi DT-AUDIT với người – thời điểm – trạm – giá trị trước/sau; bản ghi audit không xóa, không sửa, chỉ vô hiệu; lưu ≥ 10 năm; tra cứu theo đối tượng/người/khoảng ngày. | Must | Active | #05 NFR-SEC-03; #13 §4; FR-M9-05 |
| NFR-USAB-01 | Usability (operability) | Giao diện trạm: mọi nút thao tác ≥ 48 px; dùng được khi đeo găng và màn hình ướt; thao tác chính (tiếp nhận, nạp, dỡ, đóng gói, cấp phát, quét sử dụng) hoàn tất ≤ 3 chạm sau khi quét; kiểm chứng với 5 KTV đeo găng tại UAT, đo số chạm và tỷ lệ lỗi. | Must | Active | #05 NFR-USAB-01 |
| NFR-USAB-02 | Usability / Localization | Toàn bộ giao diện và thông báo bằng tiếng Việt, thuật ngữ theo QĐ 3671/QĐ-BYT; nhãn in hỗ trợ thêm tiếng Anh; 0 chuỗi chưa dịch trên 43 màn hình (SCR-01..43) tại UAT. `[chuẩn hóa]` bổ sung chỉ số "0 chuỗi chưa dịch". | Must | Active | #05 NFR-USAB-02 |
| NFR-COMP-01 | Compliance | Tuân thủ TT 16/2018/TT-BYT và QĐ 3671/QĐ-BYT theo checklist đối chiếu tại UAT; hồ sơ tiệt khuẩn (mẻ, chỉ thị, gói, sử dụng) lưu và tra cứu được ≥ 10 năm; sổ tiệt khuẩn điện tử in được đúng mẫu BYT. | Must | Active | #05 NFR-COMP-01; #02 §5 |
| NFR-COMP-02 | Compliance / Interoperability | Set ID mã hóa GS1 DataMatrix GIAI (AI 8004) duy nhất; Cycle ID mã hóa GS1 DataMatrix (01)(11)(17)(21) duy nhất (chốt 2026-10-17; có thể in thêm dòng chữ người đọc, không dùng Code-128 làm mã máy đọc); hai loại nhãn: nhãn hấp hơi nước 134°C và nhãn plasma H2O2; 100% nhãn mẫu quét được sau chu trình tương ứng (thử tại UAT: 8 mẻ hấp + 2 mẻ plasma theo UAT-01). | Must | Active | #05 NFR-COMP-02; #14 UAT-01; OQ-06 ✅ đã chốt |
| NFR-MAINT-01 | Maintainability (modifiability) | Khu, trạm, chương trình xử lý, mẫu nhãn, định mức, cơ số, ngưỡng cảnh báo cấu hình được bởi R10 qua giao diện, không cần sửa code/deploy; kiểm chứng tại UAT: R10 tự thay đổi ≥ 1 mục mỗi loại không cần DEV. | Must | Active | #05 NFR-MAINT-01 |
| NFR-BACKUP-01 | Reliability (recoverability) | RPO ≤ 15 phút (binlog), RTO ≤ 4 giờ; sao lưu đầy đủ hằng ngày; bản sao ngoài site; bản sao mã hóa; diễn tập khôi phục hằng quý đo RPO/RTO thực tế. `[chuẩn hóa]` bổ sung "ngoài site, mã hóa" từ #13 §3. | Must | Active | #05 NFR-BACKUP-01; #12 §2; #13 §3 |
| NFR-INT-01 | Compatibility (interoperability) | Hỗ trợ máy quét HID/serial, máy in nhãn ZPL/TSPL, cân điện tử RS-232/USB; máy rửa/tiệt khuẩn kết nối được qua CSV/API (tùy máy); không tích hợp HIS. Mỗi loại thiết bị ngoại vi thử nghiệm đạt tại UAT. `[chuẩn hóa]` gốc ghi máy tiệt khuẩn "tùy chọn, giai đoạn 2" trong khi #12 §4 và FR-M2-24 cho phép tự động với máy kết nối được ngay v1.0 — xem OQ-03. | Must | Active | #05 NFR-INT-01; #12 §4 |

#### 3.3.2 NFR bổ sung theo catalog ISO 25010 (21 NFR) [NEW v1.11 — duyệt 2026-10-17]

Đối chiếu 14 NFR gốc với catalog ISO 25010 (`requirement-catalog.md` — Non-functional requirements) cho thấy các nhóm sau **chưa có hoặc chưa đo được**: scalability/capacity người dùng và tăng trưởng dữ liệu, maintenance window, graceful degradation, OWASP/vulnerability, secrets, observability, maintainability (test coverage, tài liệu), portability/container, localization (định dạng, múi giờ), accessibility, compatibility trình duyệt/thiết bị. 21 NFR dưới đây được **chủ đầu tư duyệt ngày 2026-10-17 (Status Active)**; các giá trị số đánh `[đề xuất]` là ngưỡng mặc định đã duyệt, có thể hiệu chỉnh qua quy trình thay đổi (#00 CHG). ID tiếp nối dãy gốc. Tổng NFR v1.11 = 35.

| ID | Category (ISO 25010) | Requirement (metric, target, condition) | Priority | Status | Nguồn / lý do |
| :-- | :------- | :-------------------------------------- | :------- | :----- | :---- |
| NFR-PERF-03 | Performance efficiency | 95% trang Web desktop (danh sách, form, dashboard) tải hoàn tất ≤ 3 giây `[đề xuất]` và báo cáo/sổ tiệt khuẩn điện tử theo tháng sinh PDF ≤ 30 giây `[đề xuất]` tại tải NFR-PERF-02. | Should | Active | Catalog: response-time; gốc chỉ có ngưỡng quét |
| NFR-PERF-04 | Performance efficiency | Tra cứu truy xuất hai chiều (FR-M2-19) và liệt kê toàn bộ gói của một mẻ phục vụ thu hồi trả kết quả ≤ 10 giây `[đề xuất]` với CSDL 10 năm dữ liệu (NFR-SCAL-02); mục tiêu nghiệp vụ "< 5 phút" (O1) bao gồm cả thao tác người dùng. | Must | Active | #01 O1, §9; catalog: throughput |
| NFR-SCAL-01 | Scalability / capacity | Hệ thống hỗ trợ 25–40 người dùng đăng nhập đồng thời (theo #01 §1) và tối đa 40 trạm/PDA (NFR-PERF-02) trên cấu hình server 8 vCPU/16 GB (#12 §5); mở rộng lên 80 người dùng `[đề xuất]` bằng nâng tài nguyên VM, không đổi kiến trúc. | Must | Active | #01 §1; #12 §5; catalog: concurrent users |
| NFR-SCAL-02 | Scalability / capacity | Dung lượng thiết kế: ≥ 3.000 Cycle ID/ngày × 365 × 10 năm ≈ 11 triệu bản ghi DT-PACK và ≥ 50 triệu bản ghi DT-AUDIT `[đề xuất]` không suy giảm NFR-PERF-01; ảnh thực tế lưu ở file storage với chính sách dung lượng ≥ 500 GB `[đề xuất]`. | Should | Active | NFR-PERF-02 × lưu trữ 10 năm (NFR-COMP-01) |
| NFR-AVAIL-03 | Reliability (availability) | Cửa sổ bảo trì có kế hoạch ≤ 4 giờ/tháng `[đề xuất]`, ngoài khung 06:00–20:00 `[đề xuất]`, báo trước R02/R10 ≥ 24 giờ; trong bảo trì, trạm/PDA chạy chế độ offline (NFR-AVAIL-02). | Should | Active | NFR-AVAIL-01 "bảo trì ngoài giờ cao điểm" chưa đo được |
| NFR-AVAIL-04 | Reliability (fault tolerance) | Khi một thiết bị ngoại vi (máy in, cân, agent) lỗi, trạm vẫn ghi nhận giao dịch nghiệp vụ; lệnh in vào hàng đợi, số cân cho nhập tay có đánh dấu nguồn; không thiết bị ngoại vi nào là single point of failure của chuỗi 8 trạm (cấu hình mặc định, A-64). | Must | Active | FR-M1-05, FR-M2-08, FR-M3-01 ngoại lệ; catalog: graceful degradation |
| NFR-SEC-04 | Security | Ứng dụng tùy biến `tracecore` không có lỗ hổng mức High/Critical theo OWASP Top 10 / ASVS Level 2 `[đề xuất]` tại kiểm thử thâm nhập nội bộ trước go-live; lỗ hổng Medium khắc phục trong 30 ngày `[đề xuất]`. | Must | Active | #13 §3 "kiểm thử thâm nhập nội bộ" chưa có ngưỡng; catalog: OWASP |
| NFR-SEC-05 | Security | Bản vá bảo mật Frappe/ERPNext/HRMS và hệ điều hành áp dụng ≤ 30 ngày sau phát hành `[đề xuất]` (Critical ≤ 7 ngày `[đề xuất]`), có thử trên môi trường staging trước. | Should | Active | Catalog: vulnerability/patch policy |
| NFR-SEC-06 | Security | Mọi secret (API Key/Secret station agent, SMTP, SMS gateway, khóa mã hóa trường) lưu ngoài mã nguồn (site_config/vault), không ghi vào log; API key xoay 90 ngày (#13 §3); khóa AES-256 mã bệnh nhân có quy trình quản lý/xoay khóa được R10 phê duyệt. | Must | Active | #13 §3; catalog: secrets management |
| NFR-SEC-07 | Security (authorization) | RBAC theo 10 vai trò × 40 DocType đúng ma trận #13 §2.1; R08 chỉ truy cập dữ liệu khoa mình (User Permission theo Department); 100% ô ma trận kiểm thử tự động tại CI. | Must | Active | #13 §2; catalog: authorization model |
| NFR-SEC-08 | Security (accountability) | Tài khoản nhân viên nghỉ việc vô hiệu trong ngày; rà soát quyền hằng quý có biên bản; đăng nhập bất thường (≥ 5 lần từ chối thẻ/15 phút hoặc đăng nhập ngoài giờ ca) cảnh báo R10 trong ≤ 5 phút `[đề xuất]`. | Should | Active | #13 §3 "Vận hành" chưa có ngưỡng thời gian |
| NFR-OBS-01 | Observability / operability | Server, worker, scheduler, Redis, MariaDB, print server và từng station agent có health check; uptime/latency/queue depth thu thập qua Prometheus/Grafana hoặc Frappe Monitor; cảnh báo tới R10 ≤ 5 phút `[đề xuất]` khi dịch vụ down hoặc hàng đợi offline chưa đồng bộ > 4 giờ. | Should | Active | #12 §5 "Giám sát" chưa có ngưỡng |
| NFR-OBS-02 | Observability / operability | Log ứng dụng có cấu trúc (JSON), lưu ≥ 12 tháng `[đề xuất]`, không chứa mã bệnh nhân dạng rõ, truy vấn theo trạm/người/mã mẻ; log đồng bộ offline ghi batch, số xung đột. | Should | Active | #13 §4 Audit; catalog: logging |
| NFR-MAINT-02 | Maintainability (testability) | Mã Python của app `tracecore` có unit/integration test tự động với độ phủ dòng ≥ 70% `[đề xuất]`, 100% BRU có test tự động; CI chạy toàn bộ test trước mỗi merge. | Should | Active | Catalog: test coverage; 66 TC gốc là thủ công |
| NFR-MAINT-03 | Maintainability (analysability) | Mọi DocType, Workflow, Server Script, RPC có mô tả trong mã và tài liệu kỹ thuật đồng bộ với #08, #11, #16; thay đổi yêu cầu ghi vào #00 CHG và Revision History SRS. | Should | Active | cover.md "mọi thay đổi ghi vào #00" |
| NFR-PORT-01 | Portability | Toàn bộ hệ thống (bench, app, MariaDB, Redis, Nginx) cài đặt lại được từ đầu trên VM Ubuntu 22.04 sạch hoặc Docker (frappe_docker) bằng script/compose trong ≤ 4 giờ `[đề xuất]`, phục vụ RTO (NFR-BACKUP-01) và môi trường staging. | Should | Active | Catalog: containerization; NFR-BACKUP-01 RTO 4 giờ |
| NFR-PORT-02 | Portability (data) | Dữ liệu danh mục, BOM, cơ số, bảng giá nhập được từ Excel mẫu (EI-SW-007); toàn bộ dữ liệu nghiệp vụ xuất được ra CSV/Excel theo DocType để di trú hoặc bàn giao khi kết thúc hợp đồng. | Must | Active | #12 §4, §5.1; catalog: data migration |
| NFR-L10N-01 | Localization | Định dạng ngày `dd/mm/yyyy`, giờ 24h, số thập phân dấu phẩy, tiền tệ VND không lẻ, múi giờ Asia/Ho_Chi_Minh (UTC+7) nhất quán trên web, trạm, PDA, nhãn và báo cáo; dấu thời gian lưu UTC, hiển thị giờ địa phương. | Must | Active | Catalog: locale formats, time zones; NFR-USAB-02 chỉ nêu ngôn ngữ |
| NFR-ACC-01 | Usability (accessibility) | Giao diện Web desktop đạt WCAG 2.1 mức AA `[đề xuất]` cho tương phản, điều hướng bàn phím, nhãn form; giao diện trạm đạt tương phản ≥ 4,5:1, cỡ chữ ≥ 16 px `[đề xuất]`, phân biệt trạng thái Đạt/Không đạt không chỉ bằng màu. | Should | Active | Catalog: accessibility; NFR-USAB-01 chưa đề cập |
| NFR-COMPAT-01 | Compatibility | Web desktop: Chromium/Edge/Firefox 2 phiên bản mới nhất `[đề xuất]`; trạm: Chromium kiosk trên Windows 10+/Ubuntu 22.04; PDA: Android 12+ Chrome PWA; độ phân giải trạm 1366×768 đến 1920×1080, PDA ≥ 5". | Must | Active | #12 §5; catalog: browsers/devices |
| NFR-BACKUP-02 | Reliability (recoverability) | Sao lưu bao gồm CSDL, file đính kèm (ảnh thực tế, bản in máy), site_config và mẫu nhãn; bản sao ngoài site cách ly mạng; khôi phục thử hằng quý xác nhận mở được ≥ 1 mẻ ngẫu nhiên với đủ ảnh. | Must | Active | #13 §3; NFR-BACKUP-01 không nói rõ file đính kèm |

### 3.4 Other requirements

| ID | Requirement | Priority | Status | Nguồn |
| :-- | :---------- | :------- | :----- | :---- |
| OTH-RET-001 | Hệ thống shall lưu trữ và cho tra cứu toàn bộ hồ sơ tiệt khuẩn (DT-LOAD, DT-LOADTEST, DT-PACK, DT-USAGE, DT-RECALL, DT-STEPGATE, DT-DAILYTEST, DT-WASHBATCH) và DT-AUDIT **≥ 10 năm** kể từ ngày ghi sổ; không có cơ chế xóa, chỉ vô hiệu/lưu trữ. | Must | Active | #01 §7; #05 §4; NFR-COMP-01; NFR-SEC-03 |
| OTH-RET-002 | Hệ thống shall lưu lịch sử phiên bản của BOM, bảng định giá, cơ số (người – thời điểm – giá trị cũ/mới) cùng thời hạn với hồ sơ tiệt khuẩn để tái lập giá thành và kiểm đếm tại thời điểm quá khứ. | Must | Active | FR-M1-04; FR-M7-03; FR-M8-01; BRU-CST-002 |
| OTH-PRIV-001 | Hệ thống shall chỉ lưu **mã bệnh nhân** và mã ca mổ do khoa nhập tay (không họ tên, không dữ liệu lâm sàng), mã hóa AES-256, hiển thị ẩn, chỉ R01/R02 xem đầy đủ với lý do và ghi audit (NFR-SEC-02); dữ liệu bệnh nhân không được xuất ra Excel/CSV ở dạng rõ. | Must | Active | #13 §3; #08 §4 |
| OTH-PRIV-002 | Hệ thống shall xử lý dữ liệu nhân sự (CCHN, khám sức khỏe, tiêm chủng) với quyền đọc chỉ R01, R02, R10 theo ma trận #13 §2.1 và phù hợp quy định bảo vệ dữ liệu cá nhân hiện hành của Việt Nam. | Must | Active | #13 §2.1; DT-EMP, DT-CERT |
| OTH-LEG-001 | Sổ tiệt khuẩn điện tử và báo cáo KSNK shall in được theo mẫu BYT và có chữ ký xác nhận của Trưởng khoa KSNK để thay thế sổ giấy; bản in kèm thời điểm xuất và người xuất. | Must | Active | #01 O2, §9; FR-M9-02 |
| OTH-LEG-002 | Mọi chứng từ shall tuân thủ chu trình Nháp → Ghi sổ → Hủy (tạo bản ghi hủy, không xóa) để làm bằng chứng kiểm tra; mọi ngoại lệ/ghi đè theo bảng #04 §3 phải có người phê duyệt, lý do và audit. | Must | Active | #01 §7; #05 §4; #04 §3 |
| OTH-LEG-003 | Hệ thống shall không cho phép tạo mẻ trên thiết bị áp lực quá hạn kiểm định và không cho mở khóa tạm trong trường hợp này. | Must | Active | #02 §5; BRU-EQP-002 |
| OTH-LIC-001 | Toàn bộ nền tảng (Frappe, ERPNext, HRMS và app mở rộng) shall sử dụng giấy phép mã nguồn mở tương thích (GPLv3/MIT/AGPL theo từng app); app `tracecore` tuân thủ điều kiện giấy phép của Frappe/ERPNext. | Should | Active | #12 §5.3; duyệt cùng gói v1.11 ngày 2026-10-17 |

---

## Appendix A — Glossary

| Thuật ngữ | Định nghĩa | Giá trị / định dạng / nguồn |
| --- | --- | --- |
| **AAMI ST79** | Hướng dẫn toàn diện về tiệt khuẩn hơi nước và bảo đảm vô khuẩn của AAMI (Hoa Kỳ). | Căn cứ BRU-REP-006 (cách ly mẻ cấy ghép). |
| **Audit trail (DT-AUDIT)** | Nhật ký bất biến ghi mọi thao tác: user, station, zone, doc, state_before/after, device, ts. | Không xóa, chỉ vô hiệu; lưu ≥ 10 năm. |
| **BI — Biological Indicator (chỉ thị sinh học)** | Chỉ thị bào tử theo ISO 11138, ủ sau mẻ; Đạt = âm tính. | Đọc nhanh 1–3 giờ hoặc 24 giờ. |
| **BOM — Bill of Materials** | Cấu trúc thành phần loại bộ dụng cụ: dụng cụ × số lượng, vị trí khay, ảnh thực tế bộ đã xếp; có phiên bản (v1, v2…). | DT-SETTYPE, DT-SETBOM. |
| **Bowie-Dick** | Test hằng ngày (CI loại 2) kiểm tra loại khí/thấm hơi của máy hấp; điều kiện tạo mẻ đầu ngày. | BRU-EQP-001; DT-DAILYTEST. |
| **BR / BRU** | Business Requirement (BR-M1..M9) / Business Rule (45 quy tắc gốc: BRU-ID, FLOW, REP, PAR, LIN, HR, EQP, INV, CST; [v1.11] + 4 BRU-WST-001..004 cho M10 = 49). | #02, #04; §3.1.10. |
| **BRU-WST-001 — Phân loại không trộn** | Mỗi túi/thùng chất thải chỉ chứa đúng một loại theo nhóm/mã màu TT 20/2021/TT-BYT; một dòng phiếu thu gom = một loại; phát hiện trộn/sai màu → NC Phân loại sai, chỉ thu gom sau khi phân loại lại hoặc R02 xác nhận. | FR-M10-01.2, FR-M10-02.3/.4, FR-M10-03.1. |
| **BRU-WST-002 — Thời gian lưu giữ tối đa** | Tham số theo loại chất thải, nhập tay (mặc định gợi ý ≤ 48 giờ lưu thường; ≤ 7 ngày khi lưu lạnh ≤ 8°C), tính từ thời điểm thu gom; 80% → cảnh báo sắp quá hạn; quá hạn → cảnh báo đỏ + NC + ưu tiên bàn giao; kho lạnh > 8°C → áp lại ngưỡng lưu thường. | FR-M10-01.3, FR-M10-03.2/.3/.4. |
| **BRU-WST-003 — Chỉ bàn giao đơn vị có giấy phép** | Chỉ bàn giao một loại chất thải cho đơn vị xử lý có giấy phép môi trường và hợp đồng còn hiệu lực cho đúng loại đó; hết hiệu lực → tự chuyển Hết hiệu lực và chặn chọn. | FR-M10-04.4, FR-M10-05.3. |
| **BRU-WST-004 — Đối chiếu kg thu gom – bàn giao** | Mỗi phiếu bàn giao đối chiếu tổng kg thu gom của các túi/thùng với kg bàn giao; chênh lệch > ngưỡng (mặc định 5%, R02 nhập tay) → cảnh báo R02, bắt buộc lý do, NC chênh lệch khối lượng. | FR-M10-04, FR-M10-04.1. |
| **CAPA** | Corrective and Preventive Action — hành động khắc phục, phòng ngừa gắn với NC. | DT-INCIDENT; ERPNext Quality Action. |
| **Cách ly (quarantine) mẻ** | Giữ gói của mẻ cấy ghép hoặc chương trình yêu cầu BI cho tới khi BI âm; cấp trước cần R01. | BRU-REP-006; FR-M2-12. |
| **CCHN** | Chứng chỉ hành nghề. | DT-CERT. |
| **CI — Chemical Indicator (chỉ thị hóa học)** | Theo ISO 11140-1: loại 1 (băng), 2 (Bowie-Dick), 4, 5 (tích hợp), 6 (mô phỏng); lô chỉ thị hóa học phải quét trước khi sinh Cycle ID. | BRU-REP-013. |
| **Cổng khoa** | Trang web đơn giản cho R08 xem phiếu cấp phát, thông báo thu hồi, dữ liệu khoa mình (từ v1.11: kg chất thải và NC phân loại sai của khoa). | EI-UI-004; FR-M10-07.3. |
| **Chất thải y tế (rắn) — nhóm & mã màu** | Theo TT 20/2021/TT-BYT: **lây nhiễm** (sắc nhọn, không sắc nhọn, nguy cơ lây nhiễm cao, giải phẫu) — **vàng**; **nguy hại không lây nhiễm** — **đen**; **thông thường** — **xanh**; **tái chế** — **trắng**. M10 chỉ quản lý chất thải rắn. | FR-M10-01; DT-WASTETYPE (đề xuất). |
| **Chứng từ chất thải nguy hại** | Chứng từ theo NĐ 08/2022/NĐ-CP kèm mỗi lần bàn giao chất thải lây nhiễm/nguy hại: số chứng từ, đơn vị vận chuyển, đơn vị xử lý có giấy phép, hợp đồng; bản scan đính phiếu bàn giao. | FR-M10-04.3. |
| **Cổng kiểm soát (step gate)** | Kết quả Đạt/Không đạt của từng bước T1–T5 cho từng bộ trong chu trình; bước trước chưa Đạt → trạm sau từ chối; Không đạt → Xử lý lại bước đó; đủ 5 cổng → Vô khuẩn. | BRU-FLOW-004; FR-M2-25; DT-STEPGATE; ST-SU-REDO. |
| **Cơ số tái xử lý (max_cycles)** | Số chu trình tối đa một dụng cụ/bộ/vật tư tái sử dụng được tái xử lý theo IFU; nhập tay bởi R01/R02, ghi nguồn IFU/Ước tính; cơ số bộ = min cơ số dụng cụ trong BOM nếu không đặt riêng. | Số nguyên; null = Chưa xác định (chỉ cảnh báo). DT-PARLEVEL. |
| **Cơ số tồn khoa** | Số bộ tối thiểu/tối đa khoa được giữ; kiểm tra khi cấp phát; vượt → phê duyệt R02 (cấp cứu tự động ≤ 20%). | min/max/% vượt. BRU-PAR-005. |
| **CSSD** | Central Sterile Services Department — Đơn vị tiệt khuẩn trung tâm. | |
| **Cycle ID (mã vạch một lần)** | Mã tự sinh khi KTV bấm Xác nhận hoàn thành đóng gói; gắn với bộ cho đúng một chu trình; mang Set ID, tên bộ, phiên bản BOM, ngày giờ và người đóng gói, hạn sử dụng, phương pháp, loại gói, lô chỉ thị; bắt buộc có trước khi vào mẻ; hết hiệu lực khi dùng/quá hạn/mẻ không đạt/gói rách/tiếp nhận. | `CY-YYMMDD-NNNN`; offline `CY-YYMMDD-T<trạm>-NNNN`; nhãn GS1 DataMatrix (01)(11)(17)(21). BRU-ID-002..005. |
| **DataMatrix (GS1)** | Mã 2D theo GS1 dùng cho Set ID và Cycle ID; chịu được in nhiệt chuyển và quét sau chu trình. | NFR-COMP-02. |
| **DocType (DT-*)** | Thực thể dữ liệu Frappe; 40 DocType nghiệp vụ. | #08. |
| **Dụng cụ mượn (loaner)** | Dụng cụ/bộ mượn từ hãng, quản lý cùng cơ chế nhưng tách biệt tài sản; Set ID tiền tố `LN-`, có ngày hết hiệu lực khi trả. | FR-M1-07/08; DT-LOANER. |
| **Đơn vị xử lý chất thải** | Tổ chức vận chuyển/xử lý chất thải y tế có giấy phép môi trường và hợp đồng với bệnh viện; actor ngoài ký nhận bàn giao; danh mục có loại được phép, hiệu lực, đơn giá/kg. | FR-M10-05; UC-36. |
| **Đồ vải theo tổng hợp** | Quản lý theo khoa – loại – số chiếc – cân nặng, không theo từng chiếc; quy đổi số ↔ kg, cảnh báo lệch > 15%; phân luồng nhiễm/không nhiễm. | BRU-LIN-001..004; M3. |
| **EARS** | Easy Approach to Requirements Syntax — cú pháp yêu cầu dùng cho §3.1. | |
| **FEFO** | First Expired, First Out — xuất trước gói/lô có hạn gần nhất; chặn lô quá hạn. | BRU-REP-008; BRU-INV-001. |
| **Frappe / ERPNext / HRMS** | Nền tảng ứng dụng mã nguồn mở (Python/MariaDB) và các app ERP, HR; phiên bản mục tiêu v15. | #12 §5. |
| **GIAI** | Global Individual Asset Identifier — định danh tài sản cá thể của GS1, AI 8004 — AI duy nhất cho Set ID (chốt 2026-10-17; không dùng SGTIN (01)+(21)). | Set ID; BRU-ID-001. |
| **GS1 AI (01)(11)(17)(21)** | Application Identifiers: (01) GTIN/mã loại bộ, (11) ngày sản xuất/đóng gói, (17) hạn dùng, (21) số seri (Cycle ID). | Nhãn gói. |
| **Hạn lưu (shelf_life_days)** | Số ngày gói còn vô khuẩn sau đóng gói, theo loại gói, do khoa nhập tay, không có mặc định cứng; chưa nhập thì không chọn được loại gói; R02 có thể gia hạn trong phạm vi IFU. | BRU-REP-009; BRU-ID-003. |
| **HID keyboard wedge** | Chế độ máy quét giả lập bàn phím USB. | EI-HW-001. |
| **HIS / EMR / LIS** | Hệ thống thông tin bệnh viện / bệnh án điện tử / xét nghiệm — **không tích hợp** ở phiên bản này. | |
| **IFU** | Instructions For Use — hướng dẫn nhà sản xuất (cơ số, phương pháp tương thích, hạn lưu). | |
| **Khu bẩn / sạch / vô khuẩn** | Decontamination (áp suất âm; T1, T2) / Preparation & Packing (áp suất dương; T3, T4, T5) / Sterile Storage & Dispatch (áp suất dương, 18–22°C, 35–60% RH; T5b, T6, T7). | DT-ZONE; BRU-FLOW-001. |
| **KPI** | 10 chỉ số đo quy trình TO-BE. | #03 §4; §1.3.3. |
| **KSNK** | Kiểm soát Nhiễm khuẩn. | |
| **KTV** | Kỹ thuật viên. | R03–R06. |
| **Load ID (mã mẻ)** | Mã mẻ tiệt khuẩn tự sinh khi Hoàn thành nạp; chứa toàn bộ gói, thiết bị, chương trình; nơi gắn mọi dữ liệu máy; in nhãn QR mẻ. | `ME-YYMMDD-NN`. DT-LOAD; BRU-REP-015/016. |
| **Lô rửa (Wash Batch)** | Lô máy rửa khử khuẩn; mã tự sinh khi Hoàn thành nạp; kết quả áp cho toàn bộ bộ trong lô. | Tiền tố `LR-`. DT-WASHBATCH. |
| **Loại gói** | Vật liệu bao gói: giấy crepe / túi hàn / hộp lọc — mỗi loại có hạn lưu nhập tay. | DT-SETTYPE. |
| **Loại nhãn** | Vật tư nhãn theo phương pháp: `VT-NHAN-HAP` (hấp 121/134) và `VT-NHAN-PLASMA` (plasma H2O2); máy in/cuộn gán loại; in sai loại bị chặn. | BRU-REP-011; DT-ITEM.label_method. |
| **Mã bệnh nhân** | Mã do khoa nhập tay tại T8, không lấy từ HIS; lưu mã hóa AES-256; hiển thị ẩn 4 ký tự giữa. | NFR-SEC-02; DT-USAGE. |
| **Mã đối tượng (do hệ thống sinh)** | Mọi đối tượng quét mang mã hệ thống sinh và in: nhân viên `NV-` (QR thẻ), thiết bị `TB-`, vị trí kệ `KE-`, trạm `TR-`, cuộn nhãn `CN-`, [v1.11] túi/thùng chất thải `CT-`, bộ dụng cụ = Set ID GS1. | FR-M9-07; FR-M10-01.5; BRU-ID-006. |
| **Máy hai cửa (pass-through)** | Máy rửa / máy tiệt khuẩn có cửa vào khu này và cửa ra khu kế tiếp; là ranh giới vật lý giữa các khu. | BRU-FLOW-001 ngoại lệ. |
| **MoSCoW** | Must / Should / Could / Won't — thang ưu tiên yêu cầu. | |
| **NC — Non-Conformance (không phù hợp)** | Sự cố/không phù hợp được ghi nhận (lô rửa không đạt, mẻ không đạt, đóng gói thiếu…) và theo dõi CAPA. | FR-M2-21/22; DT-INCIDENT. |
| **NFR** | Non-functional requirement — yêu cầu phi chức năng. | §3.3. |
| **Nhập tay có xác nhận** | Với máy không kết nối: người vận hành nhập tham số chu trình theo mẫu chương trình, đính ảnh bản in nếu máy có bản in, bắt buộc tick xác nhận; ghi nguồn `Nhập tay`, người, thời điểm vào mã mẻ. | FR-M2-10; BRU-REP-015. |
| **PDA** | Thiết bị cầm tay Android (12+) có máy quét tích hợp, chạy PWA. | EI-UI-003. |
| **Phân loại Spaulding** | Mức nguy cơ theo tiếp xúc: Thiết yếu (tiệt khuẩn) / Bán thiết yếu (khử khuẩn mức cao) / Không thiết yếu. | DT-INSTR. |
| **Phương pháp tiệt khuẩn** | Hấp 121 / Hấp 134 / Plasma H2O2 / EO; quyết định loại nhãn và chương trình tương thích. | BRU-REP-004. |
| **PIN phê duyệt** | PIN 6 số (băm bcrypt) dùng cho thao tác đặc quyền của R01/R02. | #13 §2.2, §3. |
| **PWA** | Progressive Web App — Service Worker + IndexedDB, chạy offline. | |
| **R01–R10** | 10 vai trò: R01 Trưởng khoa KSNK; R02 Điều dưỡng trưởng / Giám sát CSSD; R03 KTV khu bẩn; R04 KTV khu sạch; R05 KTV tiệt khuẩn; R06 KTV kho vô khuẩn / cấp phát; R07 Nhân viên đồ vải & chất thải (v1.11 mở rộng); R08 Nhân viên khoa sử dụng; R09 Kế toán / Vật tư; R10 Quản trị hệ thống. | §2.3; #13 §1. |
| **RBAC** | Role-Based Access Control — phân quyền theo vai trò × DocType + ràng buộc khu/khoa. | #13 §2. |
| **RPO / RTO** | Recovery Point Objective / Recovery Time Objective. | ≤ 15 phút / ≤ 4 giờ. NFR-BACKUP-01. |
| **RTM** | Requirements Traceability Matrix — ma trận truy vết yêu cầu. | #15. |
| **SCR-NN** | Mã màn hình (43: SCR-01..37 gốc #09; SCR-38..43 mới v1.11 cho M10, thông báo, import/export). | #09; §3.2.1. |
| **Set ID** | Mã định danh vĩnh viễn của bộ dụng cụ vật lý, GS1 DataMatrix GIAI với tiền tố GS1 bệnh viện; không tái cấp kể cả khi thanh lý; không sửa sau khi in thẻ. | DT-SETUNIT; BRU-ID-001. |
| **Sổ tiệt khuẩn điện tử** | Print Format theo mẫu BYT thay sổ giấy; in PDF/Excel; R01 ký xác nhận. | FR-M9-02. |
| **ST-SU-REDO** | Trạng thái "Xử lý lại" của bộ trong WF-01. | #16. |
| **Station agent** | Dịch vụ Python trên PC trạm: cân RS-232/USB, in ZPL/TSPL qua TCP 9100, đọc CSV/API máy kết nối được. | #12 §2, §5.4. |
| **T1–T8** | 8 trạm (cấu hình mặc định, A-64): T1 Tiếp nhận · T2 Rửa – khử khuẩn · T3 Kiểm tra – lắp ráp · T4 Đóng gói · T5 Nạp mẻ tiệt khuẩn · T5b Dỡ mẻ – giải phóng · T6 Kho vô khuẩn · T7 Cấp phát · T8 Sử dụng. | #03 §3.1. |
| **Thu hồi (recall)** | Lệnh tự lập khi mẻ Không đạt / BI dương: liệt kê mọi Cycle ID trong mẻ; gói ở kho → khóa, đã cấp → thu hồi, đã dùng → báo bác sĩ; đóng khi 100% gói xác nhận + CAPA. | FR-M2-20; DT-RECALL; BRU-REP-007. |
| **Tiêu hao tự động theo mẻ** | Khi hoàn tất lô rửa/mẻ/lô giặt, hệ thống trừ tồn vật tư theo định mức chương trình (Stock Entry Material Issue). | BRU-INV-002; FR-M6-03. |
| **TSPL / ZPL** | Ngôn ngữ lệnh máy in nhãn (TSC / Zebra). | EI-HW-002. |
| **TT 16/2018/TT-BYT** | Thông tư quy định về kiểm soát nhiễm khuẩn trong cơ sở KBCB. | |
| **TT 20/2021/TT-BYT** | Thông tư quy định về quản lý chất thải y tế trong phạm vi khuôn viên cơ sở y tế — căn cứ M10 (phân loại, mã màu, bao bì, lưu giữ, bàn giao, báo cáo). | §3.1.10. |
| **NĐ 08/2022/NĐ-CP** | Nghị định quy định chi tiết Luật Bảo vệ môi trường — chứng từ chất thải nguy hại, giấy phép môi trường của đơn vị vận chuyển/xử lý. | FR-M10-04, FR-M10-05. |
| **Thời gian lưu giữ tối đa (chất thải)** | Thời gian tối đa túi/thùng được lưu tại kho chất thải tính từ thu gom; tham số theo loại (BRU-WST-002). | FR-M10-01.3, FR-M10-03. |
| **QĐ 3671/QĐ-BYT** | Quyết định hướng dẫn khử khuẩn, tiệt khuẩn dụng cụ. | |
| **UAT** | User Acceptance Testing — nghiệm thu với thiết bị thật tại 3 khu. | #14. |
| **UC-NN / US-NN** | Use Case (39: UC-01..33 gốc + UC-34..39 v1.11) / User Story (33, tham chiếu gốc). | #06, #07; docs/use-cases.md. |
| **Vật tư tái sử dụng** | Vật tư (không phải dụng cụ phẫu thuật) được tái xử lý nhiều lần, có cơ số riêng. | M1, M8. |
| **WF-NN** | Workflow (9 workflow, 48 trạng thái). | #16. |
| **X-Idempotency-Key** | Header HTTP đảm bảo một giao dịch trạm/PDA đồng bộ lại không bị ghi trùng. | #12 DF-6. |

---

## Appendix B — Open questions / TBD

Gom từ các mục "Vấn đề mở" (#06 trường 25), rủi ro (#01 §8, #02 §6), ghi chú "giai đoạn 2", "tùy chọn", "Chưa xác định" và các mâu thuẫn phát hiện khi đối chiếu d01–d05, d12, d13. Mỗi mục cần người có trách nhiệm chốt trước mốc nêu.

| ID | Vấn đề mở / TBD | Nguồn | Ảnh hưởng | Người chốt | Mốc |
| :-- | :-------------- | :----- | :-------- | :--------- | :--- |
| OQ-01 | **Mẫu nhãn cụ thể** (kích thước, bố cục, vật liệu) cho 2 loại nhãn hấp/plasma chưa xác nhận; cần thử ≥ 3 loại nhãn chịu 134°C và plasma trước UAT (RK-02). | #06 UC M1/M2 "Vấn đề mở"; #01 RK-02; cover.md | FR-M2-08, NFR-COMP-02, EI-HW-003 | R01/R02 + Phòng Vật tư | Trước UAT |
| OQ-02 | **Định mức điện – nước – hóa chất – tiêu hao theo chương trình và đơn giá thực tế** chưa có; dùng mặc định theo loại máy, hiệu chỉnh sau 2 tháng bằng đồng hồ đo. | #06 UC M3–M9 "Vấn đề mở"; RK-04; BRK-04 | FR-M5-02, FR-M7-04, FR-M7-05, O4 | R09 + R02 | Trước go-live; hiệu chỉnh go-live + 2 tháng |
| OQ-03 | **Mâu thuẫn phạm vi tích hợp máy tiệt khuẩn/máy rửa:** #01 §1, §4.2 và NFR-INT-01 ghi "giai đoạn 2 / PLC không kết nối"; #12 §4, FR-M2-24, FR-M2-04/11 cho phép nhận CSV/API qua station agent với máy kết nối được ngay v1.0 ("Tùy máy"). Cần chốt: v1.0 có hiện thực đọc CSV/API cho máy nào (theo danh sách D-04) hay chỉ nhập tay có xác nhận. | #01 §1, §4.2; #05 NFR-INT-01; #12 §4; FR-M2-24 | EI-SW-001, NFR-INT-01, Sprint 2 | R10 + Medcons PM | Trước Sprint 2 |
| OQ-04 | **Danh sách thiết bị kết nối được / có bản in** (`is_connected`, `has_printout`) chưa bàn giao. | cover.md "Yêu cầu bàn giao" | FR-M2-10, FR-M2-24 | R10 + R05 | Trước Sprint 1 |
| OQ-05 | **Tiền tố GS1 của bệnh viện** — #05 §4 ghi "đã chốt" nhưng cover.md vẫn liệt kê trong hạng mục bàn giao trước Sprint 1; cần xác nhận giá trị thực tế và mã loại bộ (01) GTIN hay mã nội bộ trong (01). ✅ Đã chốt 2026-10-17 (phần Set ID): Set ID = GIAI AI 8004 duy nhất; **còn mở:** giá trị tiền tố GS1 thực tế và nội dung (01) của nhãn Cycle ID. **Amendment A-02 (2026-10-20, D6): vẫn mở.** FEAT-018 dùng GTIN test (tiền tố demo `952`, chỉ do devdata/factory gán); `Instrument Set Type.gtin` do R10 nhập (14 chữ số, check digit đúng, duy nhất), nhãn mang GTIN test in thêm dòng `TEST`. R10/BA phải cung cấp GS1 Company Prefix thật và quy tắc cấp GTIN-14 cho từng loại bộ trước UAT và trước khi in nhãn thật. **Amendment A-76 (2026-10-31): đã chốt quy tắc cấp GTIN-14;** bệnh viện vẫn phải cung cấp giá trị prefix thật. | #05 §4; cover.md | FR-M1-05, EI-SW-003 | R10 | Trước UAT và trước khi in nhãn thật (A-02) |
| OQ-06 | **Định dạng mã Cycle ID trên nhãn:** NFR-COMP-02 và #05 §4 cho phép "Code-128 hoặc DataMatrix", trong khi BRU-ID-002 và FR-M2-07 quy định GS1 DataMatrix (01)(11)(17)(21). ✅ Đã chốt 2026-10-17: Cycle ID = GS1 DataMatrix (01)(11)(17)(21) duy nhất; đã sửa NFR-COMP-02, §2.5, EI-SW-003 (có thể in thêm dòng chữ người đọc). | #05 NFR-COMP-02, §4; #04 BRU-ID-002 | FR-M2-07/08, EI-SW-003 | R02 + DEV | Đã chốt |
| OQ-07 | **Cơ số IFU không có cho dụng cụ cũ:** để trống (Chưa xác định, chỉ cảnh báo) hay cơ số mặc định theo nhóm? Danh mục cần bổ sung trước Sprint 1. | BRK-02; FR-M1-01, FR-M8-01; UC-01 A2; UC-31 E3 | FR-M8-01/03, O3 | R01 | Trước Sprint 1 **Trạng thái 21/10/2026 (A-06, I4):** vẫn mở; FEAT-014 không có cơ số mặc định, `Instrument.max_cycles` trống = Chưa xác định. |
| OQ-08 | **Mâu thuẫn ưu tiên offline trạm:** NFR-AVAIL-02 = Must, BR-M9 tiêu chí nghiệm thu yêu cầu offline 4 giờ, nhưng FR-M9-06 = Should và cover.md xếp "offline trạm" vào Sprint 5 (cuối). ✅ Đã chốt 2026-10-17: FR-M9-06 và mọi dòng con = Must theo NFR-AVAIL-02; sprint thực hiện do Medcons PM xếp khi lập kế hoạch (Sprint 5 trong cover.md có thể kéo sớm). | #05 NFR-AVAIL-02, FR-M9-06; #02 §7; cover.md | FR-M9-06, EI-COM-004, kế hoạch | R01 + Medcons PM | Đã chốt (ưu tiên) |
| OQ-09 | **Dải Cycle ID offline cấp trước cho trạm** (`CY-YYMMDD-T<trạm>-NNNN`): kích cỡ dải, cơ chế cấp lại, xử lý trùng khi đồng bộ chưa đặc tả. | FR-M2-07 ngoại lệ; FR-M9-06; #08 §4 | FR-M9-06, FR-M2-07 | DEV + R02 | Thiết kế kỹ thuật (GĐ2) |
| OQ-10 | **Tên app và số DocType trong #12 không nhất quán:** §1 ghi app `cssd` với 38 DocType; §5 ghi app `tracecore` với 40 DocType; RPC vẫn tên `cssd.v1.*`. Cần chốt namespace. | #12 §1 vs §5.1, §5.4 | EI-SW-004, kiến trúc | DEV + Medcons PM | Trước Sprint 1 |
| OQ-11 | **Phiên bản Frappe/ERPNext:** mục tiêu v15; nếu Phòng CNTT chọn v16/v17 phải kiểm tra Raven, Wiki, Builder, Drive đã hỗ trợ nhánh tương ứng. | #12 §5.4 "Phiên bản" | Toàn bộ stack | R10 | Trước Sprint 1 |
| OQ-12 | **Cách đăng nhập R01/R02 không nhất quán:** #13 §1 ghi "Thẻ + PIN", #13 §3 ghi R01/R02/R09/R10 bật 2FA trên web. Cần chốt R01/R02 trên web dùng tài khoản + 2FA, tại trạm dùng thẻ + PIN. | #13 §1 vs §3 | NFR-SEC-01, EI-UI-005 | R10 | Trước Sprint 1 |
| OQ-13 | **Phạm vi áp dụng NFR gốc chưa hợp lý:** NFR-PERF-02 ghi "M6", NFR-INT-01 ghi "M3, M5", NFR-MAINT-01 ghi "M1, M6, M7" — có vẻ là lỗi biên tập; đề xuất áp dụng toàn hệ thống hoặc đúng phân hệ liên quan. | #05 §3 chi tiết NFR | §3.3.1 | Medcons BA | Khi duyệt v1.11 |
| OQ-14 | **Định nghĩa uptime 99,5%:** có loại trừ cửa sổ bảo trì có kế hoạch hay không; ngưỡng thời gian bảo trì tối đa (đề xuất NFR-AVAIL-03). | #05 NFR-AVAIL-01 | NFR-AVAIL-01/03 | R10 | Khi duyệt v1.11 |
| OQ-15 | **Năng lực hạ tầng:** #01 §1 ước tính 25–40 người dùng đồng thời; NFR-PERF-02 ≥ 40 trạm/thiết bị đồng thời; #12 §5 server "≤ 40 trạm". Cần xác nhận số liệu quy mô thực tế của bệnh viện triển khai để chốt NFR-SCAL-01. | #01 §1; #05 NFR-PERF-02; #12 §5 | NFR-SCAL-01 | R10 + R02 | Khi duyệt v1.11 |
| OQ-16 | **Cảm biến môi trường và push notification (Firebase)** là tùy chọn — có mua sắm trong v1.0 không? Nếu không, FR-M9-04 chỉ nhập tay 2 lần/ngày. | #05 §1; #12 §2, §4; FR-M9-04 | EI-HW-005, EI-SW-002 | R10 + R01 | Trước Sprint 4 |
| OQ-17 | **Chuẩn hóa BOM giữa các khoa** chưa đầy đủ/thống nhất; cần workshop 2 tuần đầu; BOM thay đổi theo phẫu thuật viên → cho phép biến thể/phiên bản. | RK-01; BRK-03 | FR-M1-03/04, D-01 | R02 + các khoa | 2 tuần đầu GĐ2 |
| OQ-18 | **Thẻ nhân viên bệnh viện có sẵn:** đăng ký làm mã thẻ nếu duy nhất và quét được — cần khảo sát loại thẻ hiện có (mã vạch/RFID) và tỷ lệ dùng được; nếu không, in thẻ QR `NV-` cho toàn bộ nhân viên khoa lâm sàng (R08). | FR-M9-07 ngoại lệ; BRU-ID-006 | FR-M9-07, EI-UI-005 | R10 | Trước Sprint 1 |
| OQ-19 | **Dữ liệu bệnh nhân ở T8:** ngoài mã bệnh nhân còn "ca mổ, PTV" — cần xác nhận PTV (phẫu thuật viên) lưu dạng mã nhân viên hay tên, và có thuộc phạm vi mã hóa/ẩn theo NFR-SEC-02 không. | #03 §3.2 T8; FR-M2-17 | OTH-PRIV-001 | R01 | Trước Sprint 2 |
| OQ-20 | **Phân bổ chi phí mẻ theo thể tích** (tùy chọn ngoài chia đều theo gói) — có yêu cầu nhập thể tích gói trong danh mục không? | FR-M7-05 TC 2 | FR-M1-03, FR-M7-05 | R09 + R02 | Trước Sprint 5 |
| OQ-21 | **Gửi email phiếu cấp phát cho khoa** là tùy chọn — bật mặc định hay theo khoa? | FR-M2-15 TC 3 | EI-SW-002 | R02 | Trước Sprint 2 |
| OQ-22 | **Mã DataMatrix trên từng dụng cụ đơn lẻ** (FR-M1-02, giai đoạn 2): phương pháp khắc laser hay thẻ, lộ trình triển khai. | #01 §4.2; FR-M1-02 | FR-M1-02 | R01 | Giai đoạn 2 **Trạng thái 21/10/2026 (A-06, I8):** FEAT-014 chỉ sinh mã GIAI theo bản ghi danh mục (bật/tắt); mã theo từng chiếc vật lý và phương pháp khắc vẫn mở. |
| OQ-23 | **Dịch vụ tiệt khuẩn cho bên ngoài** (BO-4 nêu "căn cứ dịch vụ tiệt khuẩn cho bên ngoài") — không có FR/UC tương ứng trong v1.10; ✅ Đã chốt 2026-10-17 (SC-02 phương án a): ngoài phạm vi v1 — chỉ xuất giá thành (FR-M7-06) làm căn cứ; ghi §1.2.2 và Appendix C. | #02 BO-4 | Phạm vi; §1.2.2 | R01 | Đã chốt |
| OQ-24 | **Các NFR/EI mới `[NEW v1.11]`** và các dòng `[chuẩn hóa]` trong §3.2, §3.3.2, §3.4 ✅ Đã chốt 2026-10-17: duyệt 21 NFR mới (§3.3.2), FR-M9-08..16, SC-01 → thêm M10 (FR-M10-01..08); toàn bộ Status Active, đã đưa vào RTM. | SRS v1.11 | §3.2, §3.3, §3.4 | R01 + R10 | Đã chốt |
| OQ-25 | **Thời điểm sinh mã lô/mẻ:** BRU-REP-015 ghi "sinh ngay khi bắt đầu nạp" và WF-04 có trạng thái Nháp, còn BRU-REP-016, FR-M2-03.2, FR-M2-24.1, US-06 và UC-06 ghi chỉ sinh khi Hoàn thành nạp. ✅ Đã chốt 2026-10-22 (người dùng xác nhận): chỉ sinh khi Hoàn thành nạp, không dùng trạng thái Nháp (A-12, Q17). | BA #04 BRU-REP-015/016; #16 WF-04 | FR-M2-03.2, FR-M2-24.1 | R01 | Đã chốt |
| OQ-26 | **NC tự tạo, trừ hóa chất, chi phí lô khi đóng lô rửa** (BRU-REP-002, WF-04, TC-06-01 bước 5) phụ thuộc FEAT-030/042/046. ✅ Đã chốt 2026-10-22 (người dùng xác nhận): FEAT-021 đạt một phần (cờ `nc_pending`, Audit `WashFailed`, hook), phần còn lại làm ở các FEAT đó (A-12, Q22). | BA #04 BRU-REP-002; #14 TC-06-01 | FR-M2-04.4, FR-M2-24 | R01 + R02 | Đã chốt |
| OQ-27 | **Dung tích máy tiệt khuẩn (FR-M2-09.5):** BA DT-EQUIP chỉ có `capacity` Data "Dung tích (STU/kg)", không có số gói tối đa/mẻ. Tạm (A-16, Q4): số nguyên đầu tiên trong `capacity` là số gói tối đa/mẻ, trống thì không giới hạn; nếu khoa khai theo STU/lít cần trường riêng. | BA #08 DT-EQUIP | FR-M2-09.5 | R01 + R10 | Chờ duyệt |
| OQ-28 | **"Quét thẻ người vận hành" khi xác nhận nhập tay (FR-M2-10):** tạm (A-16, Q11) quét lại thẻ của chính nhân viên đang đăng nhập phiên trạm; khác thẻ phiên → `CARD_MISMATCH`, không lưu. FR-M2-09.3 (test ngày, kiểm định) đạt một phần ở FEAT-022 (hook rỗng), đủ ở FEAT-040. | BA #05 FR-M2-10 | FR-M2-10, FR-M2-09.3 | R01 + R02 | Chờ duyệt |

## Appendix C — Quyết định phạm vi [v1.11 — chốt 2026-10-17]

Rà bộ BA v1.10 theo `requirement-catalog.md` của pipeline phát hiện 9 FR khoảng trống (FR-M9-08..16) và 2 khoảng trống phạm vi (SC-01, SC-02). Ngày 2026-10-17 chủ đầu tư đã duyệt: **FR-M9-08..16 chuyển Status Active và đã di chuyển vào §3.1.9** (bảng M9, sau FR-M9-06; RTM đã bổ sung). Hai quyết định phạm vi ghi dưới đây.

### Quyết định phạm vi (chủ đầu tư, 2026-10-17)

| # | Vấn đề | Căn cứ | Phương án đã xét | Quyết định |
| :-- | :-- | :-- | :-- | :-- |
| SC-01 | **Quản lý rác thải y tế** — mô tả Project TraceCore nêu nhưng toàn bộ 17 tài liệu BA v1.10 không có một yêu cầu nào | Project description; BA #01 §3.1 chỉ có 9 phân hệ | (a) Ngoài phạm vi v1; (b) Thêm phân hệ M10 ở v1.11; (c) Giai đoạn 2 | ✅ **(b) Thêm M10 — Quản lý chất thải y tế (WST) ở v1.11**: §3.1.10 FR-M10-01..08, UC-34..37, SCR-38..41, BRU-WST-001..004; toàn bệnh viện, khoa KSNK giám sát; chỉ chất thải rắn (lỏng/khí out-of-scope §1.2.2); căn cứ TT 20/2021/TT-BYT, NĐ 08/2022/NĐ-CP. |
| SC-02 | **Dịch vụ tiệt khuẩn cho bên ngoài** — BO-4 nêu "căn cứ dịch vụ tiệt khuẩn cho bên ngoài" nhưng không có FR/UC (khách hàng ngoài, bảng giá dịch vụ, hóa đơn) | #02 BO-4; OQ-23 | (a) Chỉ xuất giá thành (FR-M7-06) làm căn cứ, không quản lý khách ngoài; (b) Thêm UC/FR cho khách hàng ngoài ở v1.11 | ✅ **(a)**: dịch vụ tiệt khuẩn cho khách hàng ngoài bệnh viện = out-of-scope v1 (§1.2.2); FR-M7-06 xuất giá thành làm căn cứ; OQ-23 đóng. |
