# Requirements Traceability Matrix: TraceCore

> Source: docs/srs.md, docs/use-cases.md · Last updated: 2026-10-17 · Version 1.11 (Finalized)
> Import & chuẩn hóa từ #15 RTM v1.10 (Medcons, 20/09/2026). Giữ nguyên ID gốc FR-Mx-NN (thứ tự theo bảng 2.1 của #05) và NFR-*.
> Design, Plan, and Test columns are filled by downstream phases as they produce their artifacts (see Column ownership in rtm-guide: Design ref ← software-architecture / detailed-design / ui-design; Plan ref ← implementation-planning; Test ref ← acceptance-verification). Requirements-engineering owns the other columns.
> Source = "BR-Mx (BRD #02)" cho FR kế thừa baseline; "CHG-0xx" cho FR sinh từ quyết định review v1.3–v1.10 (#00 nhật ký thay đổi); "Catalog gap v1.11" cho FR-M9-08..16 (khoảng trống catalog, duyệt 2026-10-17); "Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT" cho FR-M10-*; NFR gốc = "Catalog ISO 25010 / BA #05", NFR mới = "Catalog ISO 25010 v1.11".

## 1. Functional requirements (90)

| Req ID | Requirement (short) | Priority | Status | Source | Use case(s) | Design ref | Plan ref | Test ref |
| :----- | :------------------ | :------- | :----- | :----- | :---------- | :--------- | :------- | :------- |
| FR-M1-01 | Khai báo dụng cụ đơn lẻ | Must | Active | BR-M1 (BRD #02) | UC-01 | _TBD_ | FEAT-014 | _TBD_ |
| FR-M1-02 | Mã DataMatrix dụng cụ đơn lẻ (giai đoạn 2 sẵn sàng) | Should | Active | BR-M1 (BRD #02) | UC-01 | _TBD_ | FEAT-014 | _TBD_ |
| FR-M1-03 | Định nghĩa loại bộ dụng cụ (BOM) | Must | Active | BR-M1 (BRD #02) | UC-02 | _TBD_ | FEAT-015 | _TBD_ |
| FR-M1-04 | Phiên bản BOM và khoa sở hữu | Must | Active | BR-M1 (BRD #02) | UC-02 | _TBD_ | FEAT-015 | _TBD_ |
| FR-M1-05 | Cấp Set ID vĩnh viễn (GS1) | Must | Active | BR-M1 (BRD #02) | UC-03 | ADR-004; ADR-006 | FEAT-016 | _TBD_ |
| FR-M1-06 | Vòng đời bộ dụng cụ vật lý | Must | Active | BR-M1 (BRD #02) | UC-03 | ADR-003; ADR-005 | FEAT-009; FEAT-016; FEAT-023 | _TBD_ |
| FR-M1-07 | Nhập và trả dụng cụ mượn | Should | Active | BR-M1 (BRD #02) | UC-04 | _TBD_ | FEAT-017 | _TBD_ |
| FR-M1-08 | Chặn cấp phát bộ mượn chưa tái xử lý | Should | Active | BR-M1 (BRD #02) | UC-04 | _TBD_ | FEAT-017 | _TBD_ |
| FR-M1-09 | Ngưỡng bảo dưỡng dụng cụ (tra dầu, bảo trì) | Must | Active | CHG-024 (review v1.10, kế thừa BR-M1) | UC-01 | _TBD_ | FEAT-014; FEAT-018 | _TBD_ |
| FR-M2-01 | Tiếp nhận bằng quét mã bộ + quét thẻ nhân viên giao | Must | Active | BR-M2 (BRD #02) | UC-05 | _TBD_ | FEAT-019 | _TBD_ |
| FR-M2-02 | Kiểm tra chiều luồng tại tiếp nhận | Must | Active | BR-M2 (BRD #02) | UC-05 | ADR-005 | FEAT-019 | _TBD_ |
| FR-M2-23 | Xác nhận thành phần bộ tại tiếp nhận (từng dòng hoặc tất cả) + ghi chú bất thường | Must | Active | CHG-024 (review v1.10, kế thừa BR-M2) | UC-05 | _TBD_ | FEAT-019 | _TBD_ |
| FR-M2-03 | Nạp lô rửa: quét mã máy + quét từng bộ, mã lô sinh tự động khi hoàn thành nạp | Must | Active | BR-M2 (BRD #02) | UC-06 | ADR-005 | FEAT-021 | _TBD_ |
| FR-M2-24 | Mã mẻ gắn toàn bộ bộ dụng cụ và dữ liệu báo cáo của máy | Must | Active | CHG-025 (review v1.10, kế thừa BR-M2) | UC-06 | ADR-007 | FEAT-021; FEAT-024 | _TBD_ |
| FR-M2-25 | Cổng kiểm soát từng bước và xử lý lại | Must | Active | CHG-025 (review v1.10, kế thừa BR-M2) | UC-06 | ADR-005 | FEAT-018; FEAT-019; FEAT-020; FEAT-021; FEAT-023 | _TBD_ |
| FR-M2-04 | Dỡ lô: quét mã máy + mã lô, kết quả áp cho toàn bộ bộ trong lô | Must | Active | BR-M2 (BRD #02) | UC-06 | ADR-007 | FEAT-021 | _TBD_ |
| FR-M2-05 | Kiểm đếm theo BOM có ảnh chụp thực tế | Must | Active | BR-M2 (BRD #02) | UC-07 | ADR-005 | FEAT-020 | _TBD_ |
| FR-M2-06 | Chặn đóng gói khi thiếu chưa xác nhận | Must | Active | BR-M2 (BRD #02) | UC-07 | _TBD_ | FEAT-020 | _TBD_ |
| FR-M2-07 | Xác nhận hoàn thành đóng gói → hệ thống tự sinh mã vạch một lần (Cycle ID) | Must | Active | BR-M2 (BRD #02) | UC-08 | ADR-003; ADR-004; ADR-005 | FEAT-009; FEAT-018 | _TBD_ |
| FR-M2-08 | In nhãn theo phương pháp (2 loại nhãn) | Must | Active | BR-M2 (BRD #02) | UC-08 | ADR-006 | FEAT-002; FEAT-018 | _TBD_ |
| FR-M2-09 | Nạp mẻ tiệt khuẩn: quét mã máy + quét từng gói, mã mẻ sinh tự động khi hoàn thành nạp | Must | Active | BR-M2 (BRD #02) | UC-09 | ADR-005 | FEAT-022 | _TBD_ |
| FR-M2-10 | Nhập tay dữ liệu máy có xác nhận người dùng | Must | Active | BR-M2 (BRD #02) | UC-09 | ADR-007 | FEAT-022 | _TBD_ |
| FR-M2-11 | Dỡ mẻ: quét mã máy + mã mẻ, kết quả mẻ áp cho toàn bộ gói; nhập chỉ thị và giải phóng | Must | Active | BR-M2 (BRD #02) | UC-10 | ADR-007 | FEAT-023 | _TBD_ |
| FR-M2-12 | Cách ly mẻ và xử lý mẻ không đạt | Must | Active | BR-M2 (BRD #02) | UC-10 | ADR-014 | FEAT-023 | _TBD_ |
| FR-M2-13 | Nhập kho vô khuẩn theo vị trí | Must | Active | BR-M2 (BRD #02) | UC-11 | ADR-005 | FEAT-025 | _TBD_ |
| FR-M2-14 | Xử lý gói hết hạn hoặc hư hỏng | Must | Active | BR-M2 (BRD #02) | UC-11 | _TBD_ | FEAT-025 | _TBD_ |
| FR-M2-15 | Cấp phát cho khoa và ký điện tử | Must | Active | BR-M2 (BRD #02) | UC-12 | _TBD_ | FEAT-026 | _TBD_ |
| FR-M2-16 | Kiểm tra cơ số khoa khi cấp phát | Must | Active | BR-M2 (BRD #02) | UC-12 | _TBD_ | FEAT-026 | _TBD_ |
| FR-M2-17 | Quét sử dụng và gắn bệnh nhân | Must | Active | BR-M2 (BRD #02) | UC-13 | ADR-010 | FEAT-027 | _TBD_ |
| FR-M2-18 | Chặn quét mã hết hiệu lực | Must | Active | BR-M2 (BRD #02) | UC-13 | ADR-008 | FEAT-027 | _TBD_ |
| FR-M2-19 | Tra cứu truy xuất hai chiều | Must | Active | BR-M2 (BRD #02) | UC-14 | _TBD_ | FEAT-028 | _TBD_ |
| FR-M2-20 | Lệnh thu hồi | Must | Active | BR-M2 (BRD #02) | UC-14 | ADR-010; ADR-014 | FEAT-029 | _TBD_ |
| FR-M2-21 | Ghi nhận sự cố / NC | Must | Active | BR-M2 (BRD #02) | UC-15 | ADR-014 | FEAT-030 | _TBD_ |
| FR-M2-22 | CAPA và theo dõi đóng | Should | Active | BR-M2 (BRD #02) | UC-15 | _TBD_ | FEAT-030 | _TBD_ |
| FR-M3-01 | Nhập lượt thu gom đồ vải | Must | Active | BR-M3 (BRD #02) | UC-16 | ADR-006 | FEAT-033 | _TBD_ |
| FR-M3-02 | Danh mục loại đồ vải và khối lượng chuẩn | Must | Active | BR-M3 (BRD #02) | UC-16 | _TBD_ | FEAT-033 | _TBD_ |
| FR-M3-03 | Tạo lô giặt | Must | Active | BR-M3 (BRD #02) | UC-17 | _TBD_ | FEAT-034 | _TBD_ |
| FR-M3-04 | Tiêu hao và chi phí lô giặt | Should | Active | BR-M3 (BRD #02) | UC-17 | _TBD_ | FEAT-034 | _TBD_ |
| FR-M3-05 | Cấp phát đồ vải theo khoa | Must | Active | BR-M3 (BRD #02) | UC-18 | _TBD_ | FEAT-035 | _TBD_ |
| FR-M3-06 | Đối chiếu thu – trả và định mức | Must | Active | BR-M3 (BRD #02) | UC-18 | _TBD_ | FEAT-035 | _TBD_ |
| FR-M4-01 | Hồ sơ nhân sự | Must | Active | BR-M4 (BRD #02) | UC-19 | ADR-002; ADR-009 | FEAT-003; FEAT-036 | [FEAT-003 Employee subset](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| FR-M4-02 | Chứng chỉ và cảnh báo hết hạn | Must | Active | BR-M4 (BRD #02) | UC-19 | ADR-014 | FEAT-036 | _TBD_ |
| FR-M4-03 | Ma trận năng lực theo trạm | Must | Active | BR-M4 (BRD #02) | UC-20 | ADR-008 | FEAT-003; FEAT-037 | [FEAT-003 competency subset](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| FR-M4-04 | Phân ca và sản lượng theo người | Should | Active | BR-M4 (BRD #02) | UC-20 | ADR-009 | FEAT-037 | _TBD_ |
| FR-M5-01 | Hồ sơ thiết bị theo khu | Must | Active | BR-M5 (BRD #02) | UC-21 | ADR-009 | FEAT-038 | _TBD_ |
| FR-M5-02 | Danh mục chương trình xử lý theo máy | Must | Active | BR-M5 (BRD #02) | UC-21 | _TBD_ | FEAT-038 | _TBD_ |
| FR-M5-03 | Lịch bảo trì, kiểm định, hiệu chuẩn | Must | Active | BR-M5 (BRD #02) | UC-22 | ADR-014 | FEAT-039 | _TBD_ |
| FR-M5-04 | Sự cố và sửa chữa thiết bị | Must | Active | BR-M5 (BRD #02) | UC-22 | _TBD_ | FEAT-039 | _TBD_ |
| FR-M5-05 | Test hằng ngày theo máy | Must | Active | BR-M5 (BRD #02) | UC-23 | _TBD_ | FEAT-040 | _TBD_ |
| FR-M5-06 | Khóa máy tự động | Must | Active | BR-M5 (BRD #02) | UC-23 | _TBD_ | FEAT-040 | _TBD_ |
| FR-M6-01 | Nhập kho theo lô/hạn | Must | Active | BR-M6 (BRD #02) | UC-24 | ADR-009 | FEAT-041 | _TBD_ |
| FR-M6-02 | Danh mục vật tư tiêu hao tái xử lý | Must | Active | BR-M6 (BRD #02) | UC-24 | ADR-009 | FEAT-041 | _TBD_ |
| FR-M6-03 | Tiêu hao tự động theo mẻ/lô | Must | Active | BR-M6 (BRD #02) | UC-25 | ADR-009 | FEAT-042 | _TBD_ |
| FR-M6-04 | Xuất kho thủ công và FEFO | Must | Active | BR-M6 (BRD #02) | UC-25 | ADR-009 | FEAT-042 | _TBD_ |
| FR-M6-05 | Kiểm kê định kỳ | Should | Active | BR-M6 (BRD #02) | UC-26 | ADR-009 | FEAT-043 | _TBD_ |
| FR-M6-06 | Cảnh báo tồn tối thiểu và sắp hết hạn | Must | Active | BR-M6 (BRD #02) | UC-26 | ADR-009; ADR-014 | FEAT-043 | _TBD_ |
| FR-M7-01 | Nhập chi phí theo khoản mục | Must | Active | BR-M7 (BRD #02) | UC-27 | _TBD_ | FEAT-044 | _TBD_ |
| FR-M7-02 | Gắn chi phí với đối tượng phân bổ | Must | Active | BR-M7 (BRD #02) | UC-27 | _TBD_ | FEAT-044 | _TBD_ |
| FR-M7-03 | Bảng định giá vật tư có phiên bản | Must | Active | BR-M7 (BRD #02) | UC-28 | _TBD_ | FEAT-045 | _TBD_ |
| FR-M7-04 | Định mức tiêu hao theo chương trình | Must | Active | BR-M7 (BRD #02) | UC-28 | _TBD_ | FEAT-045 | _TBD_ |
| FR-M7-05 | Tính chi phí mẻ và phân bổ theo gói | Must | Active | BR-M7 (BRD #02) | UC-29 | _TBD_ | FEAT-046 | _TBD_ |
| FR-M7-06 | Giá thành tái xử lý bộ dụng cụ | Must | Active | BR-M7 (BRD #02) | UC-29 | _TBD_ | FEAT-046 | _TBD_ |
| FR-M8-01 | Cấu hình cơ số tái xử lý tối đa (nhập tay) | Must | Active | BR-M8 (BRD #02) | UC-30 | _TBD_ | FEAT-031 | _TBD_ |
| FR-M8-02 | Cấu hình cơ số tồn khoa | Must | Active | BR-M8 (BRD #02) | UC-30 | _TBD_ | FEAT-026; FEAT-031 | _TBD_ |
| FR-M8-03 | Cảnh báo sớm và chặn sinh Cycle ID | Must | Active | BR-M8 (BRD #02) | UC-31 | ADR-014 | FEAT-018; FEAT-023; FEAT-032 | _TBD_ |
| FR-M8-04 | Ghi đè có phê duyệt và audit | Must | Active | BR-M8 (BRD #02) | UC-31 | ADR-008 | FEAT-032 | _TBD_ |
| FR-M9-01 | Dashboard vận hành | Must | Active | BR-M9 (BRD #02) | UC-32 | _TBD_ | FEAT-006 | _TBD_ |
| FR-M9-02 | Sổ tiệt khuẩn điện tử và báo cáo BYT | Must | Active | BR-M9 (BRD #02) | UC-32 | _TBD_ | FEAT-007 | _TBD_ |
| FR-M9-03 | Khai báo khu vực một chiều và trạm | Must | Active | BR-M9 (BRD #02) | UC-33 | ADR-001 | FEAT-002 | _TBD_ |
| FR-M9-04 | Kiểm soát môi trường khu | Should | Active | BR-M9 (BRD #02) | UC-33 | _TBD_ | FEAT-008 | _TBD_ |
| FR-M9-05 | Người dùng, phân quyền, audit trail | Must | Active | BR-M9 (BRD #02) | UC-33 | ADR-008; ADR-010 | FEAT-003 | [FEAT-003 acceptance evidence](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| FR-M9-07 | Hệ thống sinh mã định danh cho mọi đối tượng quét | Must | Active | CHG-032 (review v1.10, kế thừa BR-M9) | UC-33 | ADR-004 | FEAT-001; FEAT-005 | _TBD_ |
| FR-M9-06 | Chế độ offline tại trạm (Must từ v1.11 theo NFR-AVAIL-02, chốt 2026-10-17) | Must | Active | BR-M9 (BRD #02) | UC-33 | ADR-003 | FEAT-009 | _TBD_ |
| FR-M9-08 | Đăng xuất / kết thúc phiên trạm, một thẻ – một phiên | Must | Active | Catalog gap v1.11 | UC-33 | ADR-008 | FEAT-003 | [FEAT-003 session evidence](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| FR-M9-09 | Đổi / đặt lại mật khẩu, PIN; vô hiệu tài khoản nghỉ việc | Must | Active | Catalog gap v1.11 | UC-33 | ADR-010 | FEAT-003 | [FEAT-003 account evidence](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| FR-M9-10 | Trung tâm thông báo: kênh, người nhận theo loại sự kiện, trạng thái gửi/đọc | Must | Active | Catalog gap v1.11 | UC-38 | ADR-014 | FEAT-010 | _TBD_ |
| FR-M9-11 | Import danh mục ban đầu theo lô từ Excel mẫu, kiểm tra từng dòng, import ảnh hàng loạt | Must | Active | Catalog gap v1.11 | UC-39 | _TBD_ | FEAT-011 | _TBD_ |
| FR-M9-12 | Xuất hồ sơ tiệt khuẩn theo kỳ (PDF + Excel/CSV) phục vụ lưu trữ ≥ 10 năm | Must | Active | Catalog gap v1.11 | UC-39 | _TBD_ | FEAT-012 | _TBD_ |
| FR-M9-13 | Tìm kiếm, lọc, sắp xếp, phân trang trên mọi danh sách; ô quét là phím tắt | Must | Active | Catalog gap v1.11 | UC-32 | ADR-001 | FEAT-006 | _TBD_ |
| FR-M9-14 | Trạng thái màn hình trạm/PDA: rỗng / đang tải / lỗi kèm hành động kế tiếp | Must | Active | Catalog gap v1.11 | — / mọi UC trạm (UC-05..13, UC-16..18, UC-34..36) | ADR-002 | FEAT-001; Foundations | _TBD_ |
| FR-M9-15 | Trợ giúp theo trạm và gửi phản hồi/báo lỗi kèm ảnh màn hình | Could | Active | Catalog gap v1.11 | — / mọi UC trạm (UC-05..13, UC-16..18, UC-34..36) | ADR-002 | FEAT-013 | _TBD_ |
| FR-M9-16 | Xóa mềm danh mục đã có giao dịch; chỉ R10 xóa cứng bản ghi chưa giao dịch | Must | Active | Catalog gap v1.11 | UC-33 | ADR-001; ADR-008 | FEAT-004 | _TBD_ |
| FR-M10-01 | Danh mục loại chất thải & mã màu TT 20/2021, bao bì, khối lượng chuẩn, đơn giá/kg, thời gian lưu tối đa, QR túi/thùng | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-34 | ADR-004; ADR-013 | FEAT-047 | _TBD_ |
| FR-M10-02 | Thu gom chất thải tại khoa: quét thẻ người giao, loại, số túi, cân; phiếu khoa – loại – số – kg; chặn trộn loại | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-34 | ADR-006; ADR-013 | FEAT-047 | _TBD_ |
| FR-M10-03 | Lưu giữ tạm kho chất thải: vị trí theo loại, nhiệt độ kho lạnh, cảnh báo hạn lưu, FIFO | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-35 | ADR-013; ADR-014 | FEAT-048 | _TBD_ |
| FR-M10-04 | Bàn giao đơn vị xử lý: phiếu loại – số – kg, đối chiếu kg, ký điện tử, chứng từ CTNH, chi phí = kg × đơn giá | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-36 | ADR-006; ADR-013 | FEAT-049 | _TBD_ |
| FR-M10-05 | Danh mục đơn vị xử lý & hợp đồng, giấy phép theo loại; chặn bàn giao đơn vị không giấy phép | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-36 | ADR-013; ADR-014 | FEAT-049 | _TBD_ |
| FR-M10-06 | Sự cố chất thải (tràn đổ, phơi nhiễm sắc nhọn, phân loại sai) → NC/CAPA dùng chung FR-M2-21/22 | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-37 | ADR-013 | FEAT-050 | _TBD_ |
| FR-M10-07 | Báo cáo & dashboard chất thải: kg khoa/loại/kỳ, chênh lệch thu – giao, chi phí/kg, tuân thủ hạn lưu, mẫu TT 20/2021 | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-37 | ADR-010; ADR-013 | FEAT-050 | _TBD_ |
| FR-M10-08 | Định mức túi/thùng theo khoa (liên kết M6), kg/giường, cảnh báo phát sinh bất thường ±30% | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-37 | ADR-009; ADR-013 | FEAT-050 | _TBD_ |

FR-M9-08..16 và FR-M10-01..08 là ID mới v1.11 (chủ đầu tư duyệt 2026-10-17, srs.md Appendix C / §3.1.10); FR-M9-14/15 là yêu cầu xuyên suốt mọi màn hình trạm/PDA nên không có UC sở hữu riêng (ghi "—" kèm danh sách UC trạm tham chiếu).

## 2. Non-functional requirements (35)

NFR là yêu cầu hệ thống, không có use case sở hữu riêng; cột Use case(s) ghi các UC khai báo "NFR liên quan" trong #06 (trường 22) để tham khảo, phân hệ áp dụng theo #05 §3. 21 NFR mới (NFR-PERF-03..NFR-BACKUP-02, srs.md §3.3.2) được chủ đầu tư duyệt 2026-10-17, Use case = "—" (áp dụng toàn hệ thống).

| Req ID | Requirement (short) | Priority | Status | Source | Use case(s) | Design ref | Plan ref | Test ref |
| :----- | :------------------ | :------- | :----- | :----- | :---------- | :--------- | :------- | :------- |
| NFR-PERF-01 | Hiệu năng — Phản hồi quét: Thời gian từ quét đến phản hồi màn hình ≤ 1 giây với 95% giao dịch. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M2, M8; tham chiếu UC-05, UC-06, UC-07, UC-08, UC-09, UC-10, UC-11, UC-12, UC-13, UC-14, UC-15, UC-30, UC-31) | ADR-005; ADR-012 | FEAT-018; FEAT-019; FEAT-022; FEAT-027; Foundations | _TBD_ |
| NFR-PERF-02 | Hiệu năng — Tải đồng thời: ≥ 40 trạm/thiết bị cầm tay hoạt động đồng thời, ≥ 600 mẻ/tháng, ≥ 3.000 Cycle ID/ngày. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M6; tham chiếu UC-24, UC-25, UC-26) | ADR-012 | Foundations | _TBD_ |
| NFR-AVAIL-01 | Sẵn sàng — Uptime: ≥ 99,5%/tháng trong giờ vận hành 24/7; bảo trì có kế hoạch ngoài giờ cao điểm. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M9; tham chiếu UC-32, UC-33) | ADR-001; ADR-011 | Foundations | _TBD_ |
| NFR-AVAIL-02 | Sẵn sàng — Offline tại trạm: Trạm tiếp tục quét ≥ 4 giờ khi mất mạng; đồng bộ tự động khi kết nối lại (FR-M9-06 = Must từ v1.11). | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M2; tham chiếu UC-05, UC-06, UC-07, UC-08, UC-09, UC-10, UC-11, UC-12, UC-13, UC-14, UC-15) | ADR-003; ADR-012 | FEAT-009 | _TBD_ |
| NFR-SEC-01 | Bảo mật — Xác thực: Đăng nhập bằng tài khoản hoặc quét thẻ nhân viên; khóa sau 5 lần sai; phiên trạm tự khóa sau 10 phút. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M4, M9; tham chiếu UC-19, UC-20, UC-32, UC-33) | ADR-010 | FEAT-003; Foundations | [FEAT-003 authentication evidence](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| NFR-SEC-02 | Bảo mật — Dữ liệu bệnh nhân: Mã bệnh nhân mã hóa khi lưu, ẩn một phần khi hiển thị; chỉ vai trò được phép xem. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng Toàn hệ thống; tham chiếu UC-13) | ADR-010 | FEAT-027 | _TBD_ |
| NFR-SEC-03 | Bảo mật — Audit trail bất biến: Mọi thao tác ghi người – thời điểm – trạm – giá trị trước/sau; không xóa, chỉ vô hiệu. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M2, M8, M9; tham chiếu UC-05, UC-06, UC-07, UC-08, UC-09, UC-10, UC-11, UC-12, UC-14, UC-15, UC-30, UC-31, UC-32, UC-33) | ADR-005; ADR-008 | FEAT-004; Foundations | [FEAT-003 auth audit subset](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| NFR-USAB-01 | Khả dụng — Giao diện trạm: Nút ≥ 48px, thao tác được khi đeo găng, màn hình ướt; tối đa 3 chạm cho thao tác chính. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M2, M3; tham chiếu UC-05, UC-06, UC-07, UC-08, UC-09, UC-10, UC-11, UC-12, UC-14, UC-15, UC-16, UC-17, UC-18) | ADR-002; ADR-013 | FEAT-018; FEAT-019; FEAT-027; Foundations | _TBD_ |
| NFR-USAB-02 | Khả dụng — Ngôn ngữ: Tiếng Việt là chính, thuật ngữ theo QĐ 3671/QĐ-BYT; hỗ trợ tiếng Anh cho nhãn. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng Toàn hệ thống) | ADR-002 | Foundations | _TBD_ |
| NFR-COMP-01 | Tuân thủ — Quy định KSNK: TT 16/2018/TT-BYT, QĐ 3671/QĐ-BYT; lưu hồ sơ tiệt khuẩn ≥ 10 năm; sổ tiệt khuẩn điện tử in được. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M2, M4, M5; tham chiếu UC-05, UC-06, UC-07, UC-08, UC-09, UC-10, UC-11, UC-12, UC-14, UC-15, UC-19, UC-20, UC-21, UC-22, UC-23) | ADR-005; ADR-007; ADR-008; ADR-013 | FEAT-007; FEAT-012; Foundations | _TBD_ |
| NFR-COMP-02 | Tuân thủ — Nhãn và mã vạch: GS1 DataMatrix GIAI (AI 8004) cho Set ID; Cycle ID GS1 DataMatrix (01)(11)(17)(21) duy nhất (chốt 2026-10-17); hai loại nhãn: nhãn chịu hấp hơi nước 134°C và nhãn tương thích plasma H2O2, quét được sau chu trình. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M1; tham chiếu UC-01, UC-02, UC-03, UC-04) | ADR-004; ADR-006 | FEAT-016; FEAT-018 | _TBD_ |
| NFR-MAINT-01 | Bảo trì — Cấu hình không code: Khu, trạm, chương trình, mẫu nhãn, định mức, cơ số cấu hình bằng giao diện, không cần lập trình. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M1, M6, M7; tham chiếu UC-01, UC-02, UC-03, UC-04, UC-24, UC-25, UC-26, UC-27, UC-28, UC-29) | ADR-001; ADR-002; ADR-009 | FEAT-002; FEAT-031; FEAT-038 | _TBD_ |
| NFR-BACKUP-01 | Sao lưu — RPO/RTO: RPO ≤ 15 phút, RTO ≤ 4 giờ; sao lưu hằng ngày, kiểm tra khôi phục hằng quý. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M7, M9; tham chiếu UC-27, UC-28, UC-29, UC-32, UC-33) | ADR-011 | Foundations | _TBD_ |
| NFR-INT-01 | Tích hợp — Thiết bị ngoại vi: Máy quét HID/serial, máy in nhãn ZPL/TSPL, cân điện tử RS-232/USB, máy tiệt khuẩn (tùy chọn, giai đoạn 2). Không tích hợp HIS. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M3, M5; tham chiếu UC-16, UC-17, UC-18, UC-21, UC-22, UC-23) | ADR-006; ADR-007 | FEAT-018; FEAT-024; FEAT-033 | _TBD_ |
| NFR-PERF-03 | Hiệu năng — Web desktop: 95% trang tải ≤ 3 giây; báo cáo/sổ tiệt khuẩn tháng sinh PDF ≤ 30 giây. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-001 | FEAT-006; FEAT-007; Foundations | _TBD_ |
| NFR-PERF-04 | Hiệu năng — Truy xuất hai chiều / liệt kê gói của mẻ ≤ 10 giây với CSDL 10 năm. | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-008 | FEAT-028; FEAT-029 | _TBD_ |
| NFR-SCAL-01 | Mở rộng — 25–40 người dùng đồng thời, 40 trạm/PDA trên 8 vCPU/16 GB; lên 80 người dùng bằng nâng VM. | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-001; ADR-011 | Foundations | _TBD_ |
| NFR-SCAL-02 | Mở rộng — Dung lượng 10 năm: ≈ 11 triệu DT-PACK, ≥ 50 triệu DT-AUDIT; file storage ≥ 500 GB. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-008; ADR-011 | Foundations | _TBD_ |
| NFR-AVAIL-03 | Sẵn sàng — Cửa sổ bảo trì ≤ 4 giờ/tháng ngoài 06:00–20:00, báo trước ≥ 24 giờ. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-003; ADR-011 | Foundations | _TBD_ |
| NFR-AVAIL-04 | Sẵn sàng — Thiết bị ngoại vi lỗi không chặn giao dịch; không single point of failure trong chuỗi 8 trạm. | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-003; ADR-006; ADR-014 | FEAT-018; FEAT-033; Foundations | _TBD_ |
| NFR-SEC-04 | Bảo mật — Không lỗ hổng High/Critical theo OWASP Top 10 / ASVS L2 trước go-live; Medium ≤ 30 ngày. | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-012 | Foundations | _TBD_ |
| NFR-SEC-05 | Bảo mật — Bản vá ≤ 30 ngày (Critical ≤ 7 ngày), thử trên staging. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-011 | Foundations | _TBD_ |
| NFR-SEC-06 | Bảo mật — Secret ngoài mã nguồn, không ghi log; API key xoay 90 ngày; quy trình khóa AES-256. | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-010 | Foundations | _TBD_ |
| NFR-SEC-07 | Bảo mật — RBAC 10 vai trò × DocType theo #13; R08 chỉ dữ liệu khoa mình; 100% ô ma trận test tại CI. | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-010; ADR-012; ADR-013 | FEAT-003; Foundations | [FEAT-003 matrix subset; future R08 limits](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| NFR-SEC-08 | Bảo mật — Vô hiệu tài khoản nghỉ việc trong ngày; rà soát quyền hằng quý; cảnh báo đăng nhập bất thường ≤ 5 phút. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-010 | FEAT-003; FEAT-036 | [FEAT-003 disable subset; review/alert pending](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| NFR-OBS-01 | Giám sát — Health check mọi dịch vụ và station agent; cảnh báo R10 ≤ 5 phút khi down hoặc hàng đợi offline > 4 giờ. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-011; ADR-014 | Foundations | _TBD_ |
| NFR-OBS-02 | Giám sát — Log JSON có cấu trúc, lưu ≥ 12 tháng, không chứa mã bệnh nhân dạng rõ. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-008 | Foundations | _TBD_ |
| NFR-MAINT-02 | Bảo trì — Test tự động độ phủ ≥ 70%, 100% BRU có test; CI trước mỗi merge. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-012 | Foundations | _TBD_ |
| NFR-MAINT-03 | Bảo trì — Tài liệu kỹ thuật đồng bộ #08/#11/#16; thay đổi ghi #00 CHG và Revision History. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-001; ADR-009; ADR-012 | Foundations | _TBD_ |
| NFR-PORT-01 | Di động — Cài lại từ đầu trên Ubuntu 22.04 sạch hoặc Docker ≤ 4 giờ. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-001; ADR-011 | Foundations | _TBD_ |
| NFR-PORT-02 | Di động — Nhập từ Excel mẫu; xuất toàn bộ dữ liệu nghiệp vụ ra CSV/Excel theo DocType. | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-009 | FEAT-011; FEAT-012 | _TBD_ |
| NFR-L10N-01 | Bản địa hóa — dd/mm/yyyy, 24h, dấu phẩy thập phân, VND, Asia/Ho_Chi_Minh; lưu UTC. | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-002; ADR-003 | Foundations | _TBD_ |
| NFR-ACC-01 | Tiếp cận — Web WCAG 2.1 AA; trạm tương phản ≥ 4,5:1, chữ ≥ 16 px, trạng thái không chỉ bằng màu. | Should | Active | Catalog ISO 25010 v1.11 | — | ADR-002 | FEAT-018; Foundations | _TBD_ |
| NFR-COMPAT-01 | Tương thích — Chromium/Edge/Firefox 2 bản mới nhất; kiosk Windows 10+/Ubuntu 22.04; Android 12+; 1366×768–1920×1080. | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-002; ADR-011 | Foundations | _TBD_ |
| NFR-BACKUP-02 | Sao lưu — Gồm CSDL, file đính kèm, site_config, mẫu nhãn; bản ngoài site cách ly; khôi phục thử hằng quý. | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-011 | Foundations | _TBD_ |

## 3. Tham chiếu gốc giữ lại

Bảng dưới là **tham chiếu từ bộ BA v1.10** (#15 RTM, #05 SRS, #06 UC), giữ lại để các bước sau (architecture, ux-foundations, implementation-planning, detailed-design, acceptance-verification) đối chiếu và tái sử dụng ID. Đây **không** phải cột Design/Plan/Test do downstream sở hữu: downstream vẫn phải điền cột của mình trong mục 1–2 theo quy tắc append; BRU/SCR/API/TC/US/WF dưới đây có thể được trích dẫn lại nhưng không thay thế nghĩa vụ đó.

| FR | BRU (quy tắc nghiệp vụ) | SCR (màn hình #08) | API (#09, cấp UC) | TC (#14) | US (#07) | WF (#11) |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| FR-M1-01 | — | SCR-01 | API-M1-01, API-M1-06 | TC-01-01, TC-01-02 | US-01 | — |
| FR-M1-02 | — | SCR-01 | API-M1-01, API-M1-06 | TC-01-01, TC-01-02 | US-01 | — |
| FR-M1-03 | — | SCR-02 | API-M1-02 | TC-02-01, TC-02-02 | US-02 | — |
| FR-M1-04 | — | SCR-02 | API-M1-02 | TC-02-01, TC-02-02 | US-02 | — |
| FR-M1-05 | BRU-ID-001, BRU-ID-006 | SCR-03 | API-M1-03, API-M1-04 | TC-03-01, TC-03-02 | US-03 | WF-01 |
| FR-M1-06 | BRU-ID-001, BRU-ID-006 | SCR-03 | API-M1-03, API-M1-04 | TC-03-01, TC-03-02 | US-03 | WF-01 |
| FR-M1-07 | — | SCR-04 | API-M1-05 | TC-04-01, TC-04-02 | US-04 | WF-01 |
| FR-M1-08 | — | SCR-04 | API-M1-05 | TC-04-01, TC-04-02 | US-04 | WF-01 |
| FR-M1-09 | BRU-REP-014 | SCR-01 | API-M1-01, API-M1-06 | TC-01-01, TC-01-02 | US-01 | — |
| FR-M2-01 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-001, BRU-REP-012 | SCR-05, SCR-34 | API-M2-01, API-M1-06 | TC-05-01, TC-05-02 | US-05 | WF-01, WF-02 |
| FR-M2-02 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-001, BRU-REP-012 | SCR-05, SCR-34 | API-M2-01, API-M1-06 | TC-05-01, TC-05-02 | US-05 | WF-01, WF-02 |
| FR-M2-23 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-001, BRU-REP-012 | SCR-05, SCR-34 | API-M2-01, API-M1-06 | TC-05-01, TC-05-02 | US-05 | WF-01, WF-02 |
| FR-M2-03 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-002, BRU-FLOW-004, BRU-REP-015, BRU-REP-016 | SCR-06 | API-M2-02, API-M2-03, API-M2-17 | TC-06-01, TC-06-02 | US-06 | WF-04, WF-01 |
| FR-M2-24 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-002, BRU-FLOW-004, BRU-REP-015, BRU-REP-016 | SCR-06 | API-M2-02, API-M2-03, API-M2-17 | TC-06-01, TC-06-02 | US-06 | WF-04, WF-01 |
| FR-M2-25 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-002, BRU-FLOW-004, BRU-REP-015, BRU-REP-016 | SCR-06 | API-M2-02, API-M2-03, API-M2-17 | TC-06-01, TC-06-02 | US-06 | WF-04, WF-01 |
| FR-M2-04 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-002, BRU-FLOW-004, BRU-REP-015, BRU-REP-016 | SCR-06 | API-M2-02, API-M2-03, API-M2-17 | TC-06-01, TC-06-02 | US-06 | WF-04, WF-01 |
| FR-M2-05 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-003, BRU-FLOW-004 | SCR-07 | API-M2-04 | TC-07-01, TC-07-02 | US-07 | WF-01 |
| FR-M2-06 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-003, BRU-FLOW-004 | SCR-07 | API-M2-04 | TC-07-01, TC-07-02 | US-07 | WF-01 |
| FR-M2-07 | BRU-ID-002, BRU-ID-004, BRU-FLOW-002, BRU-FLOW-003, BRU-REP-009, BRU-FLOW-004, BRU-REP-013, BRU-REP-014, BRU-REP-011 | SCR-08 | API-M2-05, API-M2-06, API-M1-06 | TC-08-01, TC-08-02 | US-08 | WF-02 |
| FR-M2-08 | BRU-ID-002, BRU-ID-004, BRU-ID-005, BRU-FLOW-002, BRU-FLOW-003, BRU-REP-009, BRU-FLOW-004, BRU-REP-013, BRU-REP-014, BRU-REP-011 | SCR-08 | API-M2-05, API-M2-06, API-M1-06 | TC-08-01, TC-08-02 | US-08 | WF-02 |
| FR-M2-09 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-004, BRU-FLOW-004, BRU-REP-015, BRU-REP-016 | SCR-09, SCR-35 | API-M2-07, API-M2-08, API-M2-17 | TC-09-01, TC-09-02 | US-09 | WF-03, WF-02 |
| FR-M2-10 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-004, BRU-FLOW-004, BRU-REP-015, BRU-REP-016 | SCR-09, SCR-35 | API-M2-07, API-M2-08, API-M2-17 | TC-09-01, TC-09-02 | US-09 | WF-03, WF-02 |
| FR-M2-11 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-005, BRU-REP-006, BRU-FLOW-004, BRU-REP-015, BRU-REP-016 | SCR-10 | API-M2-09, API-M2-10 | TC-10-01, TC-10-02 | US-10 | WF-03, WF-02 |
| FR-M2-12 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-005, BRU-REP-006, BRU-FLOW-004, BRU-REP-015, BRU-REP-016 | SCR-10 | API-M2-09, API-M2-10 | TC-10-01, TC-10-02 | US-10 | WF-03, WF-02 |
| FR-M2-13 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-008, BRU-FLOW-004 | SCR-11 | API-M2-11, API-M2-17 | TC-11-01, TC-11-02 | US-11 | WF-02 |
| FR-M2-14 | BRU-FLOW-002, BRU-FLOW-003, BRU-REP-008, BRU-FLOW-004 | SCR-11 | API-M2-11, API-M2-17 | TC-11-01, TC-11-02 | US-11 | WF-02 |
| FR-M2-15 | BRU-FLOW-002, BRU-FLOW-003, BRU-PAR-005 | SCR-12, SCR-36 | API-M2-12 | TC-12-01, TC-12-02 | US-12 | WF-02, WF-01 |
| FR-M2-16 | BRU-FLOW-002, BRU-FLOW-003, BRU-PAR-005 | SCR-12, SCR-36 | API-M2-12 | TC-12-01, TC-12-02 | US-12 | WF-02, WF-01 |
| FR-M2-17 | BRU-ID-003, BRU-FLOW-002, BRU-FLOW-003, BRU-REP-010 | SCR-13, SCR-37 | API-M2-13 | TC-13-01, TC-13-02 | US-13 | WF-02, WF-01 |
| FR-M2-18 | BRU-ID-003, BRU-FLOW-002, BRU-FLOW-003, BRU-REP-010 | SCR-13, SCR-37 | API-M2-13 | TC-13-01, TC-13-02 | US-13 | WF-02, WF-01 |
| FR-M2-19 | BRU-REP-007 | SCR-14 | API-M2-14, API-M2-15 | TC-14-01, TC-14-02 | US-14 | WF-05 |
| FR-M2-20 | BRU-REP-007 | SCR-14 | API-M2-14, API-M2-15 | TC-14-01, TC-14-02 | US-14 | WF-05 |
| FR-M2-21 | — | SCR-15 | API-M2-16 | TC-15-01, TC-15-02 | US-15 | WF-06 |
| FR-M2-22 | — | SCR-15 | API-M2-16 | TC-15-01, TC-15-02 | US-15 | WF-06 |
| FR-M3-01 | BRU-LIN-001 | SCR-16 | API-M3-01 | TC-16-01, TC-16-02 | US-16 | — |
| FR-M3-02 | BRU-LIN-001, BRU-LIN-002 | SCR-16 | API-M3-01 | TC-16-01, TC-16-02 | US-16 | — |
| FR-M3-03 | BRU-LIN-001, BRU-LIN-003 | SCR-17 | API-M3-02 | TC-17-01, TC-17-02 | US-17 | WF-04 |
| FR-M3-04 | BRU-LIN-001, BRU-LIN-003 | SCR-17 | API-M3-02 | TC-17-01, TC-17-02 | US-17 | WF-04 |
| FR-M3-05 | BRU-LIN-001, BRU-LIN-004 | SCR-18 | API-M3-03, API-M3-04 | TC-18-01, TC-18-02 | US-18 | — |
| FR-M3-06 | BRU-LIN-001, BRU-LIN-004 | SCR-18 | API-M3-03, API-M3-04 | TC-18-01, TC-18-02 | US-18 | — |
| FR-M4-01 | BRU-ID-006 | SCR-19 | API-M4-01 | TC-19-01, TC-19-02 | US-19 | — |
| FR-M4-02 | BRU-ID-006, BRU-HR-002 | SCR-19 | API-M4-01 | TC-19-01, TC-19-02 | US-19 | — |
| FR-M4-03 | BRU-HR-001 | SCR-20 | API-M4-02 | TC-20-01, TC-20-02 | US-20 | — |
| FR-M4-04 | BRU-HR-001 | SCR-20 | API-M4-02 | TC-20-01, TC-20-02 | US-20 | — |
| FR-M5-01 | BRU-ID-006, BRU-EQP-003 | SCR-21 | API-M5-01 | TC-21-01, TC-21-02 | US-21 | — |
| FR-M5-02 | BRU-ID-006, BRU-EQP-003 | SCR-21 | API-M5-01 | TC-21-01, TC-21-02 | US-21 | — |
| FR-M5-03 | BRU-EQP-002 | SCR-22 | API-M5-03 | TC-22-01, TC-22-02 | US-22 | WF-07 |
| FR-M5-04 | BRU-EQP-002 | SCR-22 | API-M5-03 | TC-22-01, TC-22-02 | US-22 | WF-07 |
| FR-M5-05 | BRU-EQP-001 | SCR-23 | API-M5-02 | TC-23-01, TC-23-02 | US-23 | WF-07 |
| FR-M5-06 | BRU-EQP-001, BRU-EQP-002 | SCR-23 | API-M5-02 | TC-23-01, TC-23-02 | US-23 | WF-07 |
| FR-M6-01 | — | SCR-24 | API-M6-01 | TC-24-01, TC-24-02 | US-24 | WF-09 |
| FR-M6-02 | — | SCR-24 | API-M6-01 | TC-24-01, TC-24-02 | US-24 | WF-09 |
| FR-M6-03 | BRU-INV-001, BRU-INV-002 | SCR-25 | API-M6-01 | TC-25-01, TC-25-02 | US-25 | WF-09 |
| FR-M6-04 | BRU-INV-001, BRU-INV-002 | SCR-25 | API-M6-01 | TC-25-01, TC-25-02 | US-25 | WF-09 |
| FR-M6-05 | — | SCR-26 | API-M6-02 | TC-26-01, TC-26-02 | US-26 | WF-09 |
| FR-M6-06 | — | SCR-26 | API-M6-02 | TC-26-01, TC-26-02 | US-26 | WF-09 |
| FR-M7-01 | — | SCR-27 | API-M7-01 | TC-27-01, TC-27-02 | US-27 | — |
| FR-M7-02 | — | SCR-27 | API-M7-01 | TC-27-01, TC-27-02 | US-27 | — |
| FR-M7-03 | BRU-CST-002 | SCR-28 | API-M7-01 | TC-28-01, TC-28-02 | US-28 | — |
| FR-M7-04 | BRU-CST-002 | SCR-28 | API-M7-01 | TC-28-01, TC-28-02 | US-28 | — |
| FR-M7-05 | BRU-CST-001, BRU-CST-003 | SCR-29 | API-M7-02 | TC-29-01, TC-29-02 | US-29 | — |
| FR-M7-06 | BRU-CST-001, BRU-CST-003 | SCR-29 | API-M7-02 | TC-29-01, TC-29-02 | US-29 | — |
| FR-M8-01 | — | SCR-30 | API-M8-01 | TC-30-01, TC-30-02 | US-30 | — |
| FR-M8-02 | — | SCR-30 | API-M8-01 | TC-30-01, TC-30-02 | US-30 | — |
| FR-M8-03 | BRU-PAR-001, BRU-PAR-002, BRU-PAR-003, BRU-PAR-004 | SCR-31 | API-M8-02 | TC-31-01, TC-31-02 | US-31 | WF-08, WF-01 |
| FR-M8-04 | BRU-PAR-001, BRU-PAR-002, BRU-PAR-003, BRU-PAR-004 | SCR-31 | API-M8-02 | TC-31-01, TC-31-02 | US-31 | WF-08, WF-01 |
| FR-M9-01 | — | SCR-32 | API-M9-01 | TC-32-01, TC-32-02 | US-32 | — |
| FR-M9-02 | — | SCR-32 | API-M9-01 | TC-32-01, TC-32-02 | US-32 | — |
| FR-M9-03 | BRU-ID-006, BRU-FLOW-001 | SCR-33 | API-M9-02 | TC-33-01, TC-33-02 | US-33 | — |
| FR-M9-04 | BRU-ID-006, BRU-FLOW-001 | SCR-33 | API-M9-02 | TC-33-01, TC-33-02 | US-33 | — |
| FR-M9-05 | BRU-ID-006, BRU-FLOW-001 | SCR-33 | API-M9-02 | TC-33-01, TC-33-02 | US-33 | — |
| FR-M9-07 | BRU-ID-006, BRU-FLOW-001 | SCR-33 | API-M9-02 | TC-33-01, TC-33-02 | US-33 | — |
| FR-M9-06 | BRU-ID-006, BRU-FLOW-001 | SCR-33 | API-M9-02 | TC-33-01, TC-33-02 | US-33 | — |
| FR-M9-08, FR-M9-09, FR-M9-16 | BRU-ID-006 | SCR-33 | — (v1.11, chưa có trong #11) | — | — | — |
| FR-M9-10 | — | SCR-42 (mới) | — (v1.11) | — | — | — |
| FR-M9-11, FR-M9-12 | — | SCR-43 (mới) | — (v1.11) | — | — | — |
| FR-M9-13 | — | SCR-32 và mọi danh sách | — (v1.11) | — | — | — |
| FR-M9-14, FR-M9-15 | — | mọi SCR trạm/PDA | — (v1.11) | — | — | — |
| FR-M10-01, FR-M10-02 | BRU-WST-001, BRU-WST-002, BRU-ID-006 | SCR-38 (mới) | — (v1.11) | — | — | — |
| FR-M10-03 | BRU-WST-001, BRU-WST-002 | SCR-39 (mới) | — (v1.11) | — | — | — |
| FR-M10-04, FR-M10-05 | BRU-WST-003, BRU-WST-004, BRU-CST-002 | SCR-40 (mới) | — (v1.11) | — | — | WF-06 (NC) |
| FR-M10-06, FR-M10-07, FR-M10-08 | BRU-WST-001, BRU-WST-002 | SCR-41 (mới), SCR-32 | — (v1.11) | — | — | WF-06 (NC) |

Kiểm thử NFR: 14 NFR gốc tham chiếu "#14 mục 3.1 (TC phi chức năng, UAT)" theo #15 §2.3; 21 NFR mới v1.11 chưa có TC — acceptance-verification bổ sung. Dòng FR mới v1.11 (FR-M9-08..16, FR-M10-*) chưa có API/TC/US trong bộ BA v1.10; các bước detailed-design và acceptance-verification điền.

## 4. Kiểm đếm và điểm bất nhất

| Chỉ tiêu | Kết quả |
| :-- | :-- |
| Dòng FR trong RTM | 90 (73 gốc + 9 FR-M9-08..16 + 8 FR-M10-01..08) |
| Dòng NFR trong RTM | 35 (14 gốc + 21 mới v1.11) |
| UC trong docs/use-cases.md | 39 (UC-01..33 gốc + UC-34..39 mới) |
| SCR | 43 (SCR-01..37 gốc + SCR-38..43 mới) |
| FR không có UC | 0 — FR-M9-14/15 là yêu cầu xuyên suốt, ghi "—" kèm danh sách UC trạm |
| UC không có FR | 0 — rỗng |
| FR xuất hiện ở UC nhưng không có trong srs.md §3.1 | 0 — rỗng |
| FR có >1 UC | 0 (mỗi FR thuộc đúng một UC sở hữu, như #15) |
| Bộ Số Chuẩn BA v1.10 → v1.11 | N_MOD 9→10, N_FR 73→90, N_NFR 14→35, N_UC 33→39, N_SCR 37→43 |

**Điểm bất nhất phát hiện khi import (d05 / d06 / d15):**

- FR-M9-06: ưu tiên bảng 2.1 = Should, mục chi tiết 2.2 = Must — ✅ đã chốt Must ngày 2026-10-17 theo NFR-AVAIL-02 (OQ-08).
- Thứ tự ID trong #05 §2.1 và #15 không theo số (FR-M2-23 đứng sau FR-M2-02; FR-M2-24/25 giữa FR-M2-03 và FR-M2-04; FR-M9-07 trước FR-M9-06) — RTM giữ nguyên thứ tự này theo yêu cầu import; không ảnh hưởng ID.
- #05 bảng 2.1 không có cột Nguồn BR; nguồn BR lấy từ mục chi tiết 2.2 (trường "Nguồn BR"), khớp 100% với tiền tố phân hệ (FR-Mx → BR-Mx).
- #06 trường 25 "Vấn đề mở" dùng chung một câu cho cả nhóm UC (UC-01..15 một câu, UC-16..33 một câu), không phải vấn đề mở riêng từng UC — đã chép nguyên vào docs/use-cases.md, cần rà lại khi finalize.
- Nhãn ngoại lệ UC-08 trong #06 có thứ tự E1, E4, E5, E2, E3 (do bổ sung ở v1.3/v1.10) — giữ nguyên nhãn để TC-08-xx tham chiếu được.
- #15 §2.2 ghi BRU-FLOW-004 áp dụng "UC-06..UC-11" nhưng #06 trường 13 chỉ liệt kê BRU-FLOW-004 tại UC-06, 07, 08, 09, 10, 11 (khớp); BRU-ID-005 và BRU-LIN-002, BRU-HR-002 chỉ gắn FR, không gắn UC trong #15 §2.2 — RTM mục 3 lấy theo #15 §2.1 (cấp FR) nên vẫn đủ.
