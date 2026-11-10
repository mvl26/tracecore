# Requirements Traceability Matrix: TraceCore

> Source: docs/srs.md, docs/use-cases.md · Last updated: 2026-11-03 · Version 1.12 (Amendment A-113)
> Import & chuẩn hóa từ #15 RTM v1.10 (Medcons, 20/09/2026). Giữ nguyên ID gốc FR-Mx-NN (thứ tự theo bảng 2.1 của #05) và NFR-*.
> Design, Plan, and Test columns are filled by downstream phases as they produce their artifacts (see Column ownership in rtm-guide: Design ref ← software-architecture / detailed-design / ui-design; Plan ref ← implementation-planning; Test ref ← acceptance-verification). Requirements-engineering owns the other columns.
> Source = "BR-Mx (BRD #02)" cho FR kế thừa baseline; "CHG-0xx" cho FR sinh từ quyết định review v1.3–v1.10 (#00 nhật ký thay đổi); "Catalog gap v1.11" cho FR-M9-08..16 (khoảng trống catalog, duyệt 2026-10-17); "Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT" cho FR-M10-*; NFR gốc = "Catalog ISO 25010 / BA #05", NFR mới = "Catalog ISO 25010 v1.11".

## 1. Functional requirements (175 dòng: 94 trước A-113 + 81 FR v1.12)

| Req ID | Requirement (short) | Priority | Status | Source | Use case(s) | Design ref | Plan ref | Test ref |
| :----- | :------------------ | :------- | :----- | :----- | :---------- | :--------- | :------- | :------- |
| FR-M1-01 | Khai báo dụng cụ đơn lẻ | Must | Active | BR-M1 (BRD #02) | UC-01 | _TBD_ | FEAT-014 | _TBD_ |
| FR-M1-02 | Mã DataMatrix dụng cụ đơn lẻ (giai đoạn 2 sẵn sàng) | Should | Active | BR-M1 (BRD #02) | UC-01 | _TBD_ | FEAT-014 (FR-M1-02, .1, .3); FEAT-020 (FR-M1-02.2, .4) | [FEAT-020 evidence](superpowers/reviews/FEAT-020-acceptance-evidence.md) (FR-M1-02.2, .4) |
| FR-M1-03 | Định nghĩa loại bộ dụng cụ (BOM) | Must | Active | BR-M1 (BRD #02) | UC-02 | _TBD_ | FEAT-015 | `tracecore/instrument/tests/test_set_type.py`, `test_shelf_life.py`, `test_set_type_photos.py`, `test_count_sheet.py`; `tracecore/instrument/doctype/instrument_set_type/test_instrument_set_type.py` (dự kiến, FEAT-015) |
| FR-M1-04 | Phiên bản BOM và khoa sở hữu | Must | Active | BR-M1 (BRD #02) | UC-02 | _TBD_ | FEAT-015 | `tracecore/instrument/tests/test_bom_versions.py`, `test_bom_compare.py`, `test_bom_pinning.py`; `tracecore/instrument/doctype/set_bom_item/test_set_bom_item.py` (dự kiến, FEAT-015) |
| FR-M1-05 | Cấp Set ID vĩnh viễn (GS1) | Must | Active | BR-M1 (BRD #02) | UC-03 | ADR-004; ADR-006 | FEAT-016 | `tracecore/core/tests/test_code_registry.py`, `tracecore/core/tests/test_gs1.py`, `tracecore/instrument/tests/test_set_units.py`, `test_set_tags.py`, `test_set_tag_printing.py`; `tracecore/tracecore/doctype/label_template/test_set_templates.py`; `tracecore/v1/tests/test_set_unit_api.py` (dự kiến, FEAT-016) |
| FR-M1-06 | Vòng đời bộ dụng cụ vật lý | Must | Active | BR-M1 (BRD #02) | UC-03 | ADR-003; ADR-005 | FEAT-009; FEAT-016; FEAT-023 | `tracecore/instrument/tests/test_set_units.py`, `test_set_unit_history.py`; `tracecore/core/tests/test_step_gate.py` (thứ tự theo client_ts, FR-M1-06.4); `tracecore/v1/tests/test_set_unit_api.py` (dự kiến, FEAT-016) |
| FR-M1-07 | Nhập và trả dụng cụ mượn | Should | Active | BR-M1 (BRD #02) | UC-04 | _TBD_ | FEAT-017 | _TBD_ |
| FR-M1-08 | Chặn cấp phát bộ mượn chưa tái xử lý | Should | Active | BR-M1 (BRD #02) | UC-04 | _TBD_ | FEAT-017 | _TBD_ |
| FR-M1-09 | Ngưỡng bảo dưỡng dụng cụ (tra dầu, bảo trì) | Must | Active | CHG-024 (review v1.10, kế thừa BR-M1) | UC-01 | _TBD_ | FEAT-014; FEAT-018 | _TBD_ |
| FR-M2-01 | Tiếp nhận bằng quét mã bộ + quét thẻ nhân viên giao | Must | Active | BR-M2 (BRD #02) | UC-05 | _TBD_ | FEAT-019 | `tracecore/reprocessing/tests/test_receiving_open.py`, `test_receiving_scan.py`, `test_receiving_confirm.py`, `test_receiving_submit.py`, `tracecore/v1/tests/test_receive_api.py`, `tests_e2e/test_station_t1.py` |
| FR-M2-02 | Kiểm tra chiều luồng tại tiếp nhận | Must | Active | BR-M2 (BRD #02) | UC-05 | ADR-005 | FEAT-019 | `tracecore/reprocessing/tests/test_receiving_open.py`, `test_receiving_scan.py`, `test_receiving_confirm.py`, `test_receiving_submit.py`, `tracecore/v1/tests/test_receive_api.py`, `tests_e2e/test_station_t1.py` |
| FR-M2-23 | Xác nhận thành phần bộ tại tiếp nhận (từng dòng hoặc tất cả) + ghi chú bất thường | Must | Active | CHG-024 (review v1.10, kế thừa BR-M2) | UC-05 | _TBD_ | FEAT-019 | `tracecore/reprocessing/tests/test_receiving_open.py`, `test_receiving_scan.py`, `test_receiving_confirm.py`, `test_receiving_submit.py`, `tracecore/v1/tests/test_receive_api.py`, `tests_e2e/test_station_t1.py` |
| FR-M2-03 | Nạp lô rửa: quét mã máy + quét từng bộ, mã lô sinh tự động khi hoàn thành nạp | Must | Active | BR-M2 (BRD #02) | UC-06 | ADR-005 | FEAT-021 | _TBD_ |
| FR-M2-24 | Mã mẻ gắn toàn bộ bộ dụng cụ và dữ liệu báo cáo của máy | Must | Active | CHG-025 (review v1.10, kế thừa BR-M2) | UC-06 | ADR-007 | FEAT-021; FEAT-024 | _TBD_ |
| FR-M2-25 | Cổng kiểm soát từng bước và xử lý lại | Must | Active | CHG-025 (review v1.10, kế thừa BR-M2) | UC-06 | ADR-005 | FEAT-018; FEAT-019; FEAT-020; FEAT-021; FEAT-023 | [FEAT-020 evidence](superpowers/reviews/FEAT-020-acceptance-evidence.md) (cổng T3) |
| FR-M2-04 | Dỡ lô: quét mã máy + mã lô, kết quả áp cho toàn bộ bộ trong lô | Must | Active | BR-M2 (BRD #02) | UC-06 | ADR-007 | FEAT-021 | _TBD_ |
| FR-M2-05 | Kiểm đếm theo BOM có ảnh chụp thực tế | Must | Active | BR-M2 (BRD #02) | UC-07 | ADR-005 | FEAT-020 | [FEAT-020 evidence](superpowers/reviews/FEAT-020-acceptance-evidence.md) |
| FR-M2-06 | Chặn đóng gói khi thiếu chưa xác nhận | Must | Active | BR-M2 (BRD #02) | UC-07 | ADR-005 | FEAT-020 | [FEAT-020 evidence](superpowers/reviews/FEAT-020-acceptance-evidence.md) |
| FR-M2-07 | Xác nhận hoàn thành đóng gói → hệ thống tự sinh mã vạch một lần (Cycle ID) | Must | Active | BR-M2 (BRD #02) | UC-08 | ADR-003; ADR-004; ADR-005 | FEAT-009; FEAT-018 | `tracecore/reprocessing/tests/test_packing.py`, `test_packing_offline.py`; `tracecore/v1/tests/test_pack_api.py`; `tests_e2e/test_station_t4.py`, `test_station_offline.py` |
| FR-M2-08 | In nhãn theo phương pháp (2 loại nhãn) | Must | Active | BR-M2 (BRD #02) | UC-08 | ADR-006 | FEAT-002; FEAT-018 | _TBD_ |
| FR-M2-09 | Nạp mẻ tiệt khuẩn: quét mã máy + quét từng gói, mã mẻ sinh tự động khi hoàn thành nạp | Must | Active | BR-M2 (BRD #02) | UC-09 | ADR-005 | FEAT-022 | _TBD_ |
| FR-M2-10 | Nhập tay dữ liệu máy có xác nhận người dùng | Must | Active | BR-M2 (BRD #02) | UC-09 | ADR-007 | FEAT-022, FEAT-076 | _TBD_ |
| FR-M2-11 | Dỡ mẻ: quét mã máy + mã mẻ, kết quả mẻ áp cho toàn bộ gói; nhập chỉ thị và giải phóng | Must | Active | BR-M2 (BRD #02) | UC-10 | ADR-007 | FEAT-023 | _TBD_ |
| FR-M2-12 | Cách ly mẻ và xử lý mẻ không đạt | Must | Active | BR-M2 (BRD #02) | UC-10 | ADR-014 | FEAT-023 | _TBD_ |
| FR-M2-13 | Nhập kho vô khuẩn theo vị trí | Must | Active | BR-M2 (BRD #02) | UC-11 | ADR-005 | FEAT-025 | [FEAT-025 evidence](superpowers/reviews/FEAT-025-acceptance-evidence.md) |
| FR-M2-14 | Xử lý gói hết hạn hoặc hư hỏng | Must | Active | BR-M2 (BRD #02) | UC-11 | _TBD_ | FEAT-025 | [FEAT-025 evidence](superpowers/reviews/FEAT-025-acceptance-evidence.md) |
| FR-M2-15 | Cấp phát cho khoa và ký điện tử | Must | Active | BR-M2 (BRD #02) | UC-12 | ADR-001, ADR-005 | FEAT-026 | [FEAT-026 evidence](superpowers/reviews/FEAT-026-acceptance-evidence.md) |
| FR-M2-16 | Kiểm tra cơ số khoa khi cấp phát | Must | Active | BR-M2 (BRD #02) | UC-12 | ADR-001 | FEAT-026 | [FEAT-026 evidence](superpowers/reviews/FEAT-026-acceptance-evidence.md) |
| FR-M2-17 | Quét sử dụng và gắn bệnh nhân | Must | Active | BR-M2 (BRD #02) | UC-13 | ADR-010 | FEAT-027 | _TBD_ |
| FR-M2-18 | Chặn quét mã hết hiệu lực | Must | Active | BR-M2 (BRD #02) | UC-13 | ADR-008 | FEAT-027 | _TBD_ |
| FR-M2-19 | Tra cứu truy xuất hai chiều | Must | Active | BR-M2 (BRD #02) | UC-14 | _TBD_ | FEAT-028 | _TBD_ |
| FR-M2-20 | Lệnh thu hồi | Must | Active | BR-M2 (BRD #02) | UC-14 | ADR-010; ADR-014 | FEAT-029 | _TBD_ |
| FR-M2-21 | Ghi nhận sự cố / NC | Must | Active | BR-M2 (BRD #02) | UC-15 | ADR-014 | FEAT-030 | _TBD_ |
| FR-M2-22 | CAPA và theo dõi đóng | Should | Active | BR-M2 (BRD #02) | UC-15 | _TBD_ | FEAT-030 | _TBD_ |
| FR-M3-01 | Nhập lượt thu gom đồ vải | Must | Active | BR-M3 (BRD #02) | UC-16 | ADR-006 | FEAT-033 | _TBD_ |
| FR-M3-02 | Danh mục loại đồ vải và khối lượng chuẩn | Must | Active | BR-M3 (BRD #02) | UC-16 | _TBD_ | FEAT-033 | _TBD_ |
| FR-M3-03 | Tạo lô giặt | Must | Active | BR-M3 (BRD #02) | UC-17 | A-50 | FEAT-034 | `linen/tests/test_laundry.py`, `v1/tests/test_laundry_api.py` |
| FR-M3-04 | Tiêu hao và chi phí lô giặt | Should | Active | BR-M3 (BRD #02) | UC-17 | A-50 | FEAT-034 | `inventory/tests/test_consume_laundry.py`, `costing/tests/test_from_laundry.py`, `linen/tests/test_laundry_cost_report.py` |
| FR-M3-05 | Cấp phát đồ vải theo khoa | Must | Active | BR-M3 (BRD #02) | UC-18 | A-51 | FEAT-035 | `linen/tests/test_linen_issue.py`, `v1/tests/test_linen_issue_api.py` |
| FR-M3-06 | Đối chiếu thu – trả và định mức | Must | Active | BR-M3 (BRD #02) | UC-18 | A-51 | FEAT-035 | `linen/tests/test_reconcile.py` |
| FR-M3-07 | Danh mục thiết bị giặt là | Must | Active | #1847 | UC-17 | A-104 | #1847 | `linen/tests/test_laundry_equipment.py` |
| FR-M3-08 | Định mức theo mẻ của chương trình giặt, sấy | Must | Active | #1847 | UC-17 | A-104 | #1847 | `linen/tests/test_laundry_equipment.py` |
| FR-M3-09 | Lô giặt: định mức và thực tế | Must | Active | #1847 | UC-17 | A-104 | #1847 | `linen/tests/test_laundry_norm.py`, `v1/tests/test_laundry_api.py` |
| FR-M3-10 | Góc máy và báo cáo định mức | Should | Active | #1847 | UC-17 | A-104 | #1847 | `linen/tests/test_machine_usage.py` |
| FR-M4-01 | Hồ sơ nhân sự | Must | Active | BR-M4 (BRD #02) | UC-19 | ADR-002; ADR-009 | FEAT-003; FEAT-036 | [FEAT-003 Employee subset](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| FR-M4-02 | Chứng chỉ và cảnh báo hết hạn | Must | Active | BR-M4 (BRD #02) | UC-19 | ADR-014 | FEAT-036 | `hr/tests/test_certificates.py`, `v1/tests/test_staff_api.py` |
| FR-M4-03 | Ma trận năng lực theo trạm | Must | Active | BR-M4 (BRD #02) | UC-20 | ADR-008 | FEAT-003; FEAT-037 | [FEAT-003 competency subset](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| FR-M4-04 | Phân ca và sản lượng theo người | Should | Active | BR-M4 (BRD #02) | UC-20 | ADR-009 | FEAT-037 | `hr/tests/test_competency.py`, `hr/tests/test_shifts.py`, `v1/tests/test_competency_api.py` |
| FR-M5-01 | Hồ sơ thiết bị theo khu | Must | Active | BR-M5 (BRD #02) | UC-21 | ADR-009 | FEAT-038 | _TBD_ |
| FR-M5-02 | Danh mục chương trình xử lý theo máy | Must | Active | BR-M5 (BRD #02) | UC-21 | _TBD_ | FEAT-038 | _TBD_ |
| FR-M5-03 | Lịch bảo trì, kiểm định, hiệu chuẩn | Must | Active | BR-M5 (BRD #02) | UC-22 | ADR-014 | FEAT-039 | _TBD_ |
| FR-M5-04 | Sự cố và sửa chữa thiết bị | Must | Active | BR-M5 (BRD #02) | UC-22 | _TBD_ | FEAT-039 | _TBD_ |
| FR-M5-05 | Test hằng ngày theo máy | Must | Active | BR-M5 (BRD #02) | UC-23 | _TBD_ | FEAT-040 | _TBD_ |
| FR-M5-06 | Khóa máy tự động | Must | Active | BR-M5 (BRD #02) | UC-23 | _TBD_ | FEAT-040 | _TBD_ |
| FR-M6-01 | Nhập kho theo lô/hạn | Must | Active | BR-M6 (BRD #02) | UC-24 | ADR-009; A-07 | FEAT-041 | _TBD_ |
| FR-M6-02 | Danh mục vật tư tiêu hao tái xử lý | Must | Active | BR-M6 (BRD #02) | UC-24 | ADR-009; A-07 | FEAT-041 | _TBD_ |
| FR-M6-03 | Tiêu hao tự động theo mẻ/lô | Must | Active | BR-M6 (BRD #02) | UC-25 | ADR-009 | FEAT-042 | `inventory/tests/test_consume.py`, `inventory/tests/test_manual_issue.py`, `v1/tests/test_stock_api.py` |
| FR-M6-04 | Xuất kho thủ công và FEFO | Must | Active | BR-M6 (BRD #02) | UC-25 | ADR-009 | FEAT-042 | `inventory/tests/test_consume.py`, `inventory/tests/test_manual_issue.py`, `v1/tests/test_stock_api.py` |
| FR-M6-05 | Kiểm kê định kỳ | Should | Active | BR-M6 (BRD #02) | UC-26 | ADR-009; A-52 | FEAT-043 | `inventory/tests/test_count.py`, `inventory/tests/test_count_print.py` |
| FR-M6-06 | Cảnh báo tồn tối thiểu và sắp hết hạn | Must | Active | BR-M6 (BRD #02) | UC-26 | ADR-009; ADR-014; A-52 | FEAT-043 | `inventory/tests/test_alerts.py`, `inventory/tests/test_stock_alerts_report.py`, `v1/tests/test_purchase_request_api.py` |
| FR-M7-01 | Nhập chi phí theo khoản mục | Must | Active | BR-M7 (BRD #02) | UC-27 | _TBD_ | FEAT-044 | _TBD_ |
| FR-M7-02 | Gắn chi phí với đối tượng phân bổ | Must | Active | BR-M7 (BRD #02) | UC-27 | _TBD_ | FEAT-044 | _TBD_ |
| FR-M7-03 | Bảng định giá vật tư có phiên bản | Must | Active | BR-M7 (BRD #02) | UC-28 | A-48 | FEAT-045 | `tracecore/costing/tests/test_cost_rate_version.py`, `test_rates.py`, `test_rate_at_rpc.py`, `test_cost_rate_version_desk_assets.py` |
| FR-M7-04 | Định mức tiêu hao theo chương trình | Must | Active | BR-M7 (BRD #02) | UC-28 | A-48 | FEAT-045 | `tracecore/costing/tests/test_rates.py` (định mức loại gói, cảnh báo 0 và chương trình thiếu định mức); `tracecore/equipment/tests/test_norms.py` (định mức theo chương trình, FEAT-038) |
| FR-M7-05 | Tính chi phí mẻ và phân bổ theo gói | Must | Active | BR-M7 (BRD #02) | UC-29 | ADR-009; A-53 | FEAT-046 | `tracecore/costing/tests/test_sheet.py`, `test_sheet_hooks.py`, `test_cost_sheet_doctype.py` |
| FR-M7-06 | Giá thành tái xử lý bộ dụng cụ | Must | Active | BR-M7 (BRD #02) | UC-29 | ADR-009; A-53 | FEAT-046 | `tracecore/costing/tests/test_sheet.py` (TestPackCost), `test_recalculate_rpc.py`; `tracecore/costing/report/set_cost_report/test_set_cost_report.py` |
| FR-M8-01 | Cấu hình cơ số tái xử lý tối đa (nhập tay) | Must | Active | BR-M8 (BRD #02) | UC-30 | _TBD_ | FEAT-031 | `tracecore/par/tests/test_config.py`, `tracecore/par/tests/test_par_desk_assets.py`; e2e `tests_e2e/test_desk_par.py` (FEAT-031) |
| FR-M8-02 | Cấu hình cơ số tồn khoa | Must | Active | BR-M8 (BRD #02) | UC-30 | _TBD_ | FEAT-026; FEAT-031 | `tracecore/par/tests/test_config.py` (FR-M8-02, .1, .3; FEAT-031); `tracecore/par/tests/test_stock.py` (áp cơ số khoa khi cấp phát, FEAT-026); FR-M8-02.2 (báo cáo tồn khoa so cơ số) chưa có: tồn khoa đã có từ `Issue Note` (A-11 G3, A-17 C4), báo cáo làm ở FEAT riêng |
| FR-M8-03 | Cảnh báo sớm và chặn sinh Cycle ID | Must | Active | BR-M8 (BRD #02) | UC-31 | ADR-014 | FEAT-018; FEAT-023; FEAT-032 | `tracecore/par/tests/test_check.py`, `tracecore/core/tests/test_step_gate.py`, `tracecore/v1/tests/test_par_api.py` (FR-M8-03.1–.3; FEAT-032); bộ đếm tăng khi giải phóng → FEAT-023 (A-18 G2) |
| FR-M8-04 | Ghi đè có phê duyệt và audit | Must | Active | BR-M8 (BRD #02) | UC-31 | ADR-008 | FEAT-032 | `tracecore/par/tests/test_override.py`, `tracecore/par/doctype/par_override/test_par_override.py`, `tracecore/v1/tests/test_par_api.py`, `tracecore/par/report/par_override_report/test_par_override_report.py`, `tracecore/par/tests/test_par_override_desk_assets.py` (FEAT-032) |
| FR-M9-01 | Dashboard vận hành | Must | Active | BR-M9 (BRD #02) | UC-32 | ADR-002; A-54 | FEAT-006 | `admin_reports/tests/test_dashboard.py`, `v1/tests/test_dashboard_api.py`, `tests/test_tc_dashboard.py` |
| FR-M9-02 | Sổ tiệt khuẩn điện tử và báo cáo BYT | Must | Active | BR-M9 (BRD #02) | UC-32 | A-57 | FEAT-007 | `admin_reports/tests/test_sterilization_log.py` |
| FR-M9-03 | Khai báo khu vực một chiều và trạm | Must | Active | BR-M9 (BRD #02) | UC-33 | ADR-001 | FEAT-002, FEAT-051 | `core/tests/test_zones.py`, `test_zone_station.py` |
| FR-M9-04 | Kiểm soát môi trường khu | Should | Active | BR-M9 (BRD #02) | UC-33 | A-55 | FEAT-008 | `admin_reports/tests/test_environment.py`, `admin_reports/tests/test_environment_report.py`, `v1/tests/test_env_api.py` |
| FR-M9-05 | Người dùng, phân quyền, audit trail | Must | Active | BR-M9 (BRD #02) | UC-33 | ADR-008; ADR-010 | FEAT-003 | [FEAT-003 acceptance evidence](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| FR-M9-07 | Hệ thống sinh mã định danh cho mọi đối tượng quét | Must | Active | CHG-032 (review v1.10, kế thừa BR-M9) | UC-33 | ADR-004 | FEAT-001; FEAT-005 | _TBD_ |
| FR-M9-06 | Chế độ offline tại trạm (Must từ v1.11 theo NFR-AVAIL-02, chốt 2026-10-17) | Must | Active | BR-M9 (BRD #02) | UC-33 | ADR-003 | FEAT-009 | `tracecore/core/tests/test_code_range.py`, `test_sync.py`; `tracecore/v1/tests/test_sync_api.py`; `tests_e2e/test_station_offline.py`, `test_station_t1.py` |
| FR-M9-08 | Đăng xuất / kết thúc phiên trạm, một thẻ – một phiên | Must | Active | Catalog gap v1.11 | UC-33 | ADR-008 | FEAT-003 | [FEAT-003 session evidence](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| FR-M9-09 | Đổi / đặt lại mật khẩu, PIN; vô hiệu tài khoản nghỉ việc | Must | Active | Catalog gap v1.11 | UC-33 | ADR-010 | FEAT-003 | [FEAT-003 account evidence](superpowers/reviews/FEAT-003-acceptance-evidence.md) |
| FR-M9-10 | Trung tâm thông báo: kênh, người nhận theo loại sự kiện, trạng thái gửi/đọc | Must | Active | Catalog gap v1.11 | UC-38 | ADR-014 | FEAT-010 | `core/tests/test_notification.py`, `v1/tests/test_notification_api.py` |
| FR-M9-11 | Import danh mục ban đầu theo lô từ Excel mẫu, kiểm tra từng dòng, import ảnh hàng loạt | Must | Active | Catalog gap v1.11 | UC-39 | ADR-002; A-41 | FEAT-011 | `tracecore/core/tests/test_importer.py`; `tracecore/{admin_reports,instrument,equipment,inventory,par}/tests/test_imports.py`; `tracecore/instrument/tests/test_photo_import.py`; `tracecore/v1/tests/test_imports_api.py`; `tests_e2e/test_desk_import.py` |
| FR-M9-12 | Xuất hồ sơ tiệt khuẩn theo kỳ (PDF + Excel/CSV) phục vụ lưu trữ ≥ 10 năm | Must | Active | Catalog gap v1.11 | UC-39 | A-58 | FEAT-012 | `admin_reports/tests/test_archive.py` |
| FR-M9-13 | Tìm kiếm, lọc, sắp xếp, phân trang trên mọi danh sách; ô quét là phím tắt | Must | Active | Catalog gap v1.11 | UC-32 | ADR-001; A-54 | FEAT-006 | `tests/test_list_scan.py`, `v1/tests/test_dashboard_api.py` |
| FR-M9-14 | Trạng thái màn hình trạm/PDA: rỗng / đang tải / lỗi kèm hành động kế tiếp | Must | Active | Catalog gap v1.11 | — / mọi UC trạm (UC-05..13, UC-16..18, UC-34..36) | ADR-002 | FEAT-001; Foundations | _TBD_ |
| FR-M9-15 | Trợ giúp theo trạm và gửi phản hồi/báo lỗi kèm ảnh màn hình | Could | Active | Catalog gap v1.11 | — / mọi UC trạm (UC-05..13, UC-16..18, UC-34..36) | ADR-002, A-56 | FEAT-013 | `tests/test_station_help.py`, `tests/test_station_help_assets.py`, `v1/tests/test_help_api.py`, `v1/tests/test_feedback_api.py` |
| FR-M9-16 | Xóa mềm danh mục đã có giao dịch; chỉ R10 xóa cứng bản ghi chưa giao dịch | Must | Active | Catalog gap v1.11 | UC-33 | ADR-001; ADR-008 | FEAT-004 | _TBD_ |
| FR-M10-01 | Danh mục loại chất thải & mã màu TT 20/2021, bao bì, khối lượng chuẩn, đơn giá/kg, thời gian lưu tối đa, QR túi/thùng | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-34 | ADR-004; ADR-013 | FEAT-047 | `waste/tests/test_waste_type.py`, `waste/tests/test_collection.py`, `waste/tests/test_waste_station_assets.py`, `v1/tests/test_waste_api.py` |
| FR-M10-02 | Thu gom chất thải tại khoa: quét thẻ người giao, loại, số túi, cân; phiếu khoa – loại – số – kg; chặn trộn loại | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-34 | ADR-006; ADR-013 | FEAT-047 | `waste/tests/test_waste_type.py`, `waste/tests/test_collection.py`, `waste/tests/test_waste_station_assets.py`, `v1/tests/test_waste_api.py` |
| FR-M10-03 | Lưu giữ tạm kho chất thải: vị trí theo loại, nhiệt độ kho lạnh, cảnh báo hạn lưu, FIFO | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-35 | ADR-013; ADR-014 | FEAT-048 | `waste/tests/test_storage.py`, `v1/tests/test_waste_store_api.py` |
| FR-M10-04 | Bàn giao đơn vị xử lý: phiếu loại – số – kg, đối chiếu kg, ký điện tử, chứng từ CTNH, chi phí = kg × đơn giá | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-36 | ADR-006; ADR-013 | FEAT-049 | `waste/tests/test_handover.py`, `v1/tests/test_waste_handover_api.py` |
| FR-M10-05 | Danh mục đơn vị xử lý & hợp đồng, giấy phép theo loại; chặn bàn giao đơn vị không giấy phép | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-36 | ADR-013; ADR-014 | FEAT-049 | `waste/tests/test_handover.py`, `v1/tests/test_waste_handover_api.py` |
| FR-M10-06 | Sự cố chất thải (tràn đổ, phơi nhiễm sắc nhọn, phân loại sai) → NC/CAPA dùng chung FR-M2-21/22 | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-37 | ADR-013 | FEAT-050 | `waste/tests/test_analysis.py` |
| FR-M10-07 | Báo cáo & dashboard chất thải: kg khoa/loại/kỳ, chênh lệch thu – giao, chi phí/kg, tuân thủ hạn lưu, mẫu TT 20/2021 | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-37 | ADR-010; ADR-013 | FEAT-050 | `waste/tests/test_analysis.py`, `v1/tests/test_dashboard_api.py` |
| FR-M10-08 | Định mức túi/thùng theo khoa (liên kết M6), kg/giường, cảnh báo phát sinh bất thường ±30% | Must | Active | Quyết định chủ đầu tư 2026-10-17 (SC-01); TT 20/2021/TT-BYT | UC-37 | ADR-009; ADR-013 | FEAT-050 | `waste/tests/test_analysis.py` |


**[NEW v1.12 — Amendment A-113, 2026-11-03] 81 FR của M11–M17 và M9 mở rộng** (BA v1.12 §4–§11; người dùng duyệt D1–D11 ngày 03/11/2026, chủ đầu tư chưa xác nhận). Design ref: `ADR-015` cho FR dùng engine phiếu giám sát, `ADR-010` cho FR có mã người bệnh; các FR còn lại `_TBD_` tới detailed-design. Plan ref: FEAT-056..074 (implementation-plan §3 E-12..E-19); FR thuộc hai FEAT ghi cả hai.

| Req ID | Requirement (short) | Priority | Status | Source | Use case(s) | Design ref | Plan ref | Test ref |
| :----- | :------------------ | :------- | :----- | :----- | :---------- | :--------- | :------- | :------- |
| FR-M11-01 | Cơ cấu KSNK bắt buộc theo giường, tuyến | Must | Active | BA v1.12 (A-113) | UC-40 | SCR-47; A-132; A-138 | FEAT-057, FEAT-094 | `infection_program/tests/test_structure.py`, `infection_program/tests/test_qualification.py`, `infection_program/doctype/ic_structure_profile/test_ic_structure_profile.py`, `v1/tests/test_ksnk_structure_api.py`, `tests/test_ksnk_scr47.py` |
| FR-M11-02 | Ghi sổ Hội đồng: 1 Chủ tịch, 1 Thư ký | Must | Active | BA v1.12 (A-113) | UC-40 | SCR-47; A-138 | FEAT-057, FEAT-094 | `infection_program/doctype/ic_committee/test_ic_committee.py` |
| FR-M11-03 | Mạng lưới: mỗi khoa ≥ 1 BS + 1 ĐD | Must | Active | BA v1.12 (A-113) | UC-40 | SCR-47; A-132; A-138 | FEAT-057, FEAT-094 | `infection_program/doctype/ic_network_member/test_ic_network_member.py`, `infection_program/tests/test_structure.py` |
| FR-M11-04 | Kế hoạch năm: R13 duyệt, một kế hoạch/năm | Must | Active | BA v1.12 (A-113) | UC-41 | SCR-48; A-133 | FEAT-058 | `infection_program/doctype/ic_annual_plan/test_ic_annual_plan.py`, `v1/tests/test_ksnk_plan_api.py`, `tests/test_ksnk_scr48.py` |
| FR-M11-05 | Nhắc hoạt động kế hoạch tới hạn/quá hạn | Should | Active | BA v1.12 (A-113) | UC-41 | SCR-48; A-133 | FEAT-058 | `infection_program/tests/test_reminders.py` |
| FR-M11-06 | Báo cáo tổng kết KSNK năm | Must | Active | BA v1.12 (A-113) | UC-41 | SCR-48; A-133 | FEAT-058 | `infection_program/doctype/ic_annual_plan/test_ic_annual_plan.py`, `infection_program/tests/test_plan_print.py` |
| FR-M11-07 | Nhắc văn bản nội bộ hết hạn rà soát | Must | Active | BA v1.12 (A-113) | UC-41 | SCR-48; A-133 | FEAT-058 | `infection_program/doctype/ic_procedure_document/test_ic_procedure_document.py`, `infection_program/tests/test_reminders.py` |
| FR-M11-08 | Biên bản họp Hội đồng → việc theo dõi | Should | Active | BA v1.12 (A-113) | UC-41 | SCR-48; A-133 | FEAT-058 | `infection_program/doctype/ic_committee_meeting/test_ic_committee_meeting.py`, `infection_program/tests/test_reminders.py` |
| FR-M11-09 | Tỷ lệ NVYT đào tạo KSNK cơ bản theo khoa | Must | Active | BA v1.12 (A-113) | UC-42 | SCR-49; A-135 | FEAT-059 | `infection_program/tests/test_training.py`, `infection_program/report/ic_training_by_department/test_ic_training_by_department.py`, `v1/tests/test_ksnk_training_api.py`, `tests/test_ksnk_scr49.py` |
| FR-M11-10 | Tỷ lệ chuyên trách/Hội đồng/mạng lưới đã đào tạo | Must | Active | BA v1.12 (A-113) | UC-42 | SCR-49; A-135 | FEAT-059 | `infection_program/tests/test_training.py` (TestTrainingCore), `infection_program/tests/test_training_permissions.py` |
| FR-M11-11 | Sinh viên thực tập phải đào tạo KSNK trước | Should | Active | BA v1.12 (A-113) | UC-42 | SCR-49; A-135 | FEAT-059 | `infection_program/doctype/trainee_induction/test_trainee_induction.py` |
| FR-M11-12 | Dự án cải tiến chất lượng, nghiên cứu KSNK | Should | Active | BA v1.12 (A-113) | UC-42 | SCR-49; A-149 | FEAT-072 | `infection_program/doctype/ic_improvement_project/test_ic_improvement_project.py`, `v1/tests/test_ksnk_improvement_api.py` |
| FR-M11-13 | Tự đánh giá chất lượng KSNK hằng năm | Should | Active | BA v1.12 (A-113) | UC-42 | SCR-49; ADR-015; A-149 | FEAT-072 | `infection_program/tests/test_quality_review.py` |
| FR-M12-01 | Mẫu phiếu duyệt → khóa phiên bản | Must | Active | BA v1.12 (A-113) | UC-43 | ADR-015 | FEAT-060 | _TBD_ |
| FR-M12-02 | Bộ mẫu phiếu khởi tạo ở trạng thái Nháp | Must | Active | BA v1.12 (A-113) | UC-43 | ADR-015 | FEAT-061 | `compliance_audit/tests/test_seed.py` |
| FR-M12-03 | Lịch giám sát giao việc, độ bao phủ | Must | Active | BA v1.12 (A-113) | UC-43 | ADR-015 | FEAT-060 | _TBD_ |
| FR-M12-04 | Ghi phiếu PDA ≤ 3 chạm, offline | Must | Active | BA v1.12 (A-113) | UC-44 | ADR-015 | FEAT-060 | _TBD_ |
| FR-M12-05 | Tỷ lệ tuân thủ vệ sinh tay theo cơ hội | Must | Active | BA v1.12 (A-113) | UC-44 | ADR-015 | FEAT-061 | `compliance_audit/tests/test_hand_hygiene.py`, `compliance_audit/tests/test_hand_hygiene_aggregate.py`, `compliance_audit/tests/test_hygiene_report.py` |
| FR-M12-06 | Điểm % theo trọng số, mục N/A loại trừ | Must | Active | BA v1.12 (A-113) | UC-44 | ADR-015 | FEAT-060 | _TBD_ |
| FR-M12-07 | Gói dự phòng chấm tất-cả-hoặc-không | Must | Active | BA v1.12 (A-113) | UC-44 | ADR-015; A-141 | FEAT-062 | `hai_surveillance/tests`, `compliance_audit/tests/test_bundle.py` |
| FR-M12-08 | Phản hồi kết quả phiếu cho khoa | Must | Active | BA v1.12 (A-113) | UC-45 | ADR-015 | FEAT-060 | _TBD_ |
| FR-M12-09 | Mục trọng yếu không đạt → đề nghị NC | Must | Active | BA v1.12 (A-113) | UC-45 | ADR-015 | FEAT-060 | _TBD_ |
| FR-M12-10 | Chặn người giám sát tự quan sát mình | Must | Active | BA v1.12 (A-113) | UC-44 | ADR-015 | FEAT-060 | _TBD_ |
| FR-M12-11 | Nhãn "Chưa đủ mẫu" khi dưới min_sample | Should | Active | BA v1.12 (A-113) | UC-44 | ADR-015 | FEAT-060 | _TBD_ |
| FR-M12-12 | Hóa chất KSNK theo khoa–tháng, 3 nguồn | Must | Active | BA v1.12 (A-113) | UC-46 | ADR-015; SCR-54; A-142 | FEAT-066 | `compliance_audit/tests/test_chemicals.py`, `compliance_audit/tests/test_chemical_import.py`, `v1/tests/test_ic_chemical_api.py`, `tests/test_ksnk_scr54.py` |
| FR-M12-13 | Nhắc giấy phép đơn vị thuê ngoài 60/30/7 ngày | Must | Active | BA v1.12 (A-113) | UC-46 | ADR-015; SCR-54; A-142 | FEAT-066 | `compliance_audit/tests/test_vendors.py` |
| FR-M12-14 | Báo cáo tuân thủ theo kỳ PDF/Excel | Must | Active | BA v1.12 (A-113) | UC-45 | ADR-015 | FEAT-060 | _TBD_ |
| FR-M13-01 | Định nghĩa ca có phiên bản theo ngày khởi phát | Must | Active | BA v1.12 (A-113) | UC-48 | A-144 | FEAT-063 | `hai_surveillance/tests`, `v1/tests/test_hai_case_api.py` |
| FR-M13-02 | Mẫu số ngày: một bản ghi/(ngày, khoa) | Must | Active | BA v1.12 (A-113) | UC-47 | ADR-014; A-141 | FEAT-062 | `hai_surveillance/tests`, `compliance_audit/tests/test_bundle.py` |
| FR-M13-03 | Nhắc 10:00 khi thiếu mẫu số hôm trước | Must | Active | BA v1.12 (A-113) | UC-47 | ADR-014; A-141 | FEAT-062 | `hai_surveillance/tests`, `compliance_audit/tests/test_bundle.py` |
| FR-M13-04 | Đợt thiết bị, mã BN mã hóa, ngày thiết bị | Must | Active | BA v1.12 (A-113) | UC-47 | ADR-010; A-141 | FEAT-062 | `hai_surveillance/tests`, `compliance_audit/tests/test_bundle.py` |
| FR-M13-05 | Ca NKBV Nghi ngờ → Xác định/Loại trừ | Must | Active | BA v1.12 (A-113) | UC-48 | ADR-010; A-144 | FEAT-063 | `hai_surveillance/tests`, `v1/tests/test_hai_case_api.py` |
| FR-M13-06 | Kiểm tra ngưỡng giờ/ngày thiết bị khi xác định ca | Must | Active | BA v1.12 (A-113) | UC-48 | A-144 | FEAT-063 | `hai_surveillance/tests`, `v1/tests/test_hai_case_api.py` |
| FR-M13-07 | Đăng ký phẫu thuật, NNIS, cửa sổ theo dõi | Must | Active | BA v1.12 (A-113) | UC-49 | SCR-57; A-147 | FEAT-064 | `hai_surveillance/tests/test_ssi.py`, `hai_surveillance/tests/test_ssi_import.py`, `v1/tests/test_ssi_api.py`, `tests/test_ksnk_scr57.py` |
| FR-M13-08 | Lịch theo dõi NKVM sau ra viện | Must | Active | BA v1.12 (A-113) | UC-49 | SCR-57 (WEB + PDA); A-147 | FEAT-064 | `hai_surveillance/tests/test_ssi.py`, `v1/tests/test_ssi_pda.py`, `v1/tests/test_ssi_api.py` |
| FR-M13-09 | Kháng sinh dự phòng: tỷ lệ có, đúng thời điểm | Must | Active | BA v1.12 (A-113) | UC-49 | SCR-57, SCR-58; A-147 | FEAT-064 | `hai_surveillance/tests/test_ssi.py`, `hai_surveillance/tests/test_ssi_export.py` |
| FR-M13-10 | Tỷ suất NKBV/1.000 ngày theo khoa và kỳ | Must | Active | BA v1.12 (A-113) | UC-48 | A-144 | FEAT-063 | `hai_surveillance/tests`, `v1/tests/test_hai_case_api.py` |
| FR-M13-11 | Khóa kỳ tháng, mở khóa có lý do | Must | Active | BA v1.12 (A-113) | UC-48 | A-144 | FEAT-063 | `hai_surveillance/tests`, `v1/tests/test_hai_case_api.py` |
| FR-M13-12 | Xuất báo cáo NKVM/NK hồi sức theo ánh xạ cột | Must | Active | BA v1.12 (A-113) | UC-49 | SCR-58; A-147 | FEAT-064 | `core/tests/test_exporter.py`, `hai_surveillance/tests/test_ssi_export.py`, `v1/tests/test_ssi_api.py`, `tests/test_ksnk_scr57.py` |
| FR-M13-13 | Cảnh báo cụm ca vượt ngưỡng | Should | Active | BA v1.12 (A-113) | UC-50 | SCR-58; A-150 | FEAT-069 | `microbiology/tests/test_clusters.py` |
| FR-M13-14 | Điều tra cắt ngang tỷ lệ hiện mắc | Could | Active | BA v1.12 (A-113) | UC-50 | SCR-58; ADR-010; ADR-015; A-149 | FEAT-072 | `compliance_audit/tests/test_prevalence.py`, `hai_surveillance/tests/test_prevalence.py`, `v1/tests/test_hai_prevalence_api.py` |
| FR-M13-15 | Che mã BN trên danh sách, báo cáo, export M13 | Must | Active | BA v1.12 (A-113) | UC-48 | ADR-010; A-144 | FEAT-063 | `hai_surveillance/tests`, `v1/tests/test_hai_case_api.py` |
| FR-M14-01 | Import vi sinh theo hồ sơ ánh xạ, bỏ trùng | Must | Active | BA v1.12 (A-113) | UC-51 | SCR-59; ADR-009; A-136 | FEAT-067 | `microbiology/tests/test_imports.py`, `core/tests/test_importer_wide.py`, `tests/test_ksnk_scr59.py` |
| FR-M14-02 | Nhập tay kết quả vi sinh có xác nhận | Must | Active | BA v1.12 (A-113) | UC-51 | SCR-59; A-136 | FEAT-067 | `v1/tests/test_micro_api.py` |
| FR-M14-03 | Gắn nhãn đa kháng theo MDRO Rule, chủng đầu | Must | Active | BA v1.12 (A-113) | UC-51 | SCR-59; ADR-015; A-136 | FEAT-067 | `microbiology/doctype/mdro_rule/test_mdro_rule.py`, `microbiology/doctype/microbiology_isolate/test_microbiology_isolate.py`, `microbiology/tests/test_seed.py` |
| FR-M14-04 | Thông báo chủng đa kháng mới ≤ 15 phút | Must | Active | BA v1.12 (A-113) | UC-51 | SCR-59; ADR-014; A-136 | FEAT-067 | `microbiology/doctype/microbiology_isolate/test_microbiology_isolate.py`, `v1/tests/test_micro_api.py` |
| FR-M14-05 | Cảnh báo người bệnh từng đa kháng tái xuất hiện | Should | Active | BA v1.12 (A-113) | UC-51 | ADR-010; A-136 | FEAT-067 | `microbiology/doctype/microbiology_isolate/test_microbiology_isolate.py`, `v1/tests/test_micro_api.py` |
| FR-M14-06 | Lệnh cách ly: loại phòng ngừa, lý do, danh sách | Must | Active | BA v1.12 (A-113) | UC-52 | SCR-60; ADR-010; A-146 | FEAT-068 | `microbiology/tests/test_isolation.py`, `v1/tests/test_isolation_api.py`, `tests/test_ksnk_scr60.py` |
| FR-M14-07 | Tỷ lệ khoa có phòng cách ly đạt điều kiện | Must | Active | BA v1.12 (A-113) | UC-52 | SCR-60; A-146 | FEAT-068 | `microbiology/tests/test_isolation.py`, `microbiology/tests/test_isolation_patch.py` |
| FR-M14-08 | Báo cáo kháng thuốc quý S/I/R | Must | Active | BA v1.12 (A-113) | UC-51 | SCR-59; A-136 | FEAT-067 | `microbiology/tests/test_resistance.py` |
| FR-M14-09 | Điều tra ổ dịch, đường cong dịch | Must | Active | BA v1.12 (A-113) | UC-53 | SCR-61; A-150 | FEAT-069 | `microbiology/tests/test_outbreaks.py` |
| FR-M14-10 | Khai báo bệnh truyền nhiễm theo hạn nhóm bệnh | Must | Active | BA v1.12 (A-113) | UC-53 | SCR-61; A-150 | FEAT-069 | `microbiology/tests/test_notifiable.py` |
| FR-M15-01 | Vùng vệ sinh: mức nguy cơ, bên chịu trách nhiệm | Must | Active | BA v1.12 (A-113) | UC-54 | _TBD_ | FEAT-070 | tracecore/environmental_hygiene/tests (A-148) |
| FR-M15-02 | Tổng hợp tỷ lệ đạt VSMT theo mức nguy cơ, khoa | Must | Active | BA v1.12 (A-113) | UC-54 | ADR-015 | FEAT-070 | tracecore/environmental_hygiene/tests (A-148) |
| FR-M15-03 | Kết quả xét nghiệm môi trường so ngưỡng | Must | Active | BA v1.12 (A-113) | UC-54 | _TBD_ | FEAT-070 | tracecore/environmental_hygiene/tests (A-148) |
| FR-M15-04 | Mẫu Không đạt → thông báo, đề nghị NC | Must | Active | BA v1.12 (A-113) | UC-54 | _TBD_ | FEAT-070 | tracecore/environmental_hygiene/tests (A-148) |
| FR-M15-05 | Kế hoạch lấy mẫu giao việc, mẫu trễ hạn | Should | Active | BA v1.12 (A-113) | UC-54 | _TBD_ | FEAT-070 | tracecore/environmental_hygiene/tests (A-148) |
| FR-M15-06 | Phiếu kiểm tra hạ tầng, hạn kế tiếp, nhắc 7 ngày | Must | Active | BA v1.12 (A-113) | UC-54 | _TBD_ | FEAT-070 | tracecore/environmental_hygiene/tests (A-148) |
| FR-M15-07 | Báo cáo môi trường tháng/quý | Must | Active | BA v1.12 (A-113) | UC-54 | _TBD_ | FEAT-070 | tracecore/environmental_hygiene/tests (A-148) |
| FR-M16-01 | Báo phơi nhiễm ban đầu ≤ 3 bước, thông báo ngay | Must | Active | BA v1.12 (A-113) | UC-55 | SCR-63; A-137 | FEAT-071 | `occupational_safety/tests/test_exposure.py`, `v1/tests/test_exposure_api.py`, `occupational_safety/tests/test_ui.py` |
| FR-M16-02 | Sự cố sắc nhọn M10 → Occupational Exposure | Must | Active | BA v1.12 (A-113) | UC-55 | A-137 | FEAT-071 | `occupational_safety/tests/test_hook.py` |
| FR-M16-03 | Thời gian phơi nhiễm → báo cáo → dự phòng, cờ | Must | Active | BA v1.12 (A-113) | UC-55 | SCR-64; A-137 | FEAT-071 | `occupational_safety/tests/test_exposure.py` |
| FR-M16-04 | Sơ cứu, dự phòng → lịch theo dõi theo mẫu | Must | Active | BA v1.12 (A-113) | UC-55 | SCR-64; A-137 | FEAT-071 | `occupational_safety/tests/test_config.py`, `occupational_safety/tests/test_exposure.py`, `occupational_safety/tests/test_jobs.py` |
| FR-M16-05 | Quyền xem hồ sơ phơi nhiễm: R01, R11, chính NV | Must | Active | BA v1.12 (A-113) | UC-55 | ADR-010; A-137 | FEAT-071 | `occupational_safety/tests/test_privacy.py`, `v1/tests/test_exposure_api.py` |
| FR-M16-06 | Không lưu kết quả XN/chẩn đoán nhân viên | Must | Active | BA v1.12 (A-113) | UC-55 | A-137 | FEAT-071 | `occupational_safety/tests/test_exposure.py` |
| FR-M16-07 | Tiêm chủng: next_due, nhắc, tỷ lệ bao phủ | Must | Active | BA v1.12 (A-113) | UC-55 | SCR-64; A-137 | FEAT-071 | `occupational_safety/tests/test_immunization.py` |
| FR-M16-08 | Cảnh báo tồn thuốc dự phòng sau phơi nhiễm | Should | Active | BA v1.12 (A-113) | UC-55 | SCR-64; A-137 | FEAT-071 | `occupational_safety/tests/test_jobs.py` |
| FR-M16-09 | Báo cáo phơi nhiễm theo kỳ | Must | Active | BA v1.12 (A-113) | UC-55 | SCR-64; A-137 | FEAT-071 | `occupational_safety/tests/test_report.py` |
| FR-M17-01 | Giám sát bếp ăn bằng mẫu phiếu ATTP | Should | Active | BA v1.12 (A-113) | UC-56 | SCR-52; ADR-015; A-151 | FEAT-073 | `tests/test_ksnk_scr65.py` (TestFoodAuditsAndSamples) |
| FR-M17-02 | Nhắc hạn khám sức khỏe người chế biến | Should | Active | BA v1.12 (A-113) | UC-56 | SCR-65; A-151 | FEAT-073 | `food_safety/tests/test_handlers.py` |
| FR-M17-03 | Mẫu thực phẩm xử lý như mẫu môi trường | Should | Active | BA v1.12 (A-113) | UC-56 | SCR-65; A-151 | FEAT-073 | `tests/test_ksnk_scr65.py` (test_food_sample_is_handled_like_environmental_sample) |
| FR-M17-04 | Sự cố nghi ngộ độc thực phẩm → báo, NC, khai báo | Should | Active | BA v1.12 (A-113) | UC-56 | SCR-65; A-151 | FEAT-073 | `food_safety/tests/test_events.py`, `tests/test_ksnk_scr65.py` |
| FR-M17-05 | Buổi truyền thông KSNK, tổng hợp quý | Could | Active | BA v1.12 (A-113) | UC-56 | SCR-65; A-151 | FEAT-073 | `food_safety/tests/test_education.py` |
| FR-M17-06 | Tài liệu truyền thông người bệnh có QR | Could | Active | BA v1.12 (A-113) | UC-56 | SCR-65; A-151 | FEAT-073 | `infection_program/tests/test_communication_materials.py`, `tests/test_ksnk_scr65.py` |
| FR-M9-24 | Bảng chỉ số KSNK toàn viện theo kế hoạch năm | Must | Active | BA v1.12 (A-113) | UC-57 | _TBD_ | FEAT-065 | _TBD_ |
| FR-M9-25 | Báo cáo Hội đồng 1 trang hằng tháng (PDF) | Must | Active | BA v1.12 (A-113) | UC-57 | _TBD_ | FEAT-065 | _TBD_ |
| FR-M9-26 | Cổng khoa: chỉ số khoa cạnh trung bình toàn viện | Must | Active | BA v1.12 (A-113) | UC-57 | _TBD_ | FEAT-065 | _TBD_ |
| FR-M9-27 | Khóa kỳ → tính, lưu IC Indicator Value | Must | Active | BA v1.12 (A-113) | UC-57 | _TBD_ | FEAT-056 | _TBD_ |
| FR-M9-28 | Nhập file qua hồ sơ ánh xạ cột, báo lỗi dòng | Must | Active | BA v1.12 (A-113) | UC-57 | _TBD_ | FEAT-056 | _TBD_ |
| FR-M9-29 | Tự đánh giá năm QĐ 38 điền sẵn | Should | Active | BA v1.12 (A-113) | UC-57 | _TBD_ | FEAT-065 | _TBD_ |
| FR-M9-30 | Gói xuất hồ sơ KSNK cho đoàn kiểm tra | Could | Active | BA v1.12 (A-113) | UC-57 | SCR-66; A-152 | FEAT-074 | `admin_reports/tests/test_ic_dossier.py`, `tests/test_core_dossier.py`, `*/tests/test_dossier.py`, `tests/test_ksnk_scr66_dossier.py` |

FR-M9-08..16 và FR-M10-01..08 là ID mới v1.11 (chủ đầu tư duyệt 2026-10-17, srs.md Appendix C / §3.1.10); FR-M9-14/15 là yêu cầu xuyên suốt mọi màn hình trạm/PDA nên không có UC sở hữu riêng (ghi "—" kèm danh sách UC trạm tham chiếu).

## 2. Non-functional requirements (42)

NFR là yêu cầu hệ thống, không có use case sở hữu riêng; cột Use case(s) ghi các UC khai báo "NFR liên quan" trong #06 (trường 22) để tham khảo, phân hệ áp dụng theo #05 §3. 21 NFR mới (NFR-PERF-03..NFR-BACKUP-02, srs.md §3.3.2) được chủ đầu tư duyệt 2026-10-17, Use case = "—" (áp dụng toàn hệ thống).

| Req ID | Requirement (short) | Priority | Status | Source | Use case(s) | Design ref | Plan ref | Test ref |
| :----- | :------------------ | :------- | :----- | :----- | :---------- | :--------- | :------- | :------- |
| NFR-PERF-01 | Hiệu năng — Phản hồi quét: Thời gian từ quét đến phản hồi màn hình ≤ 1 giây với 95% giao dịch. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M2, M8; tham chiếu UC-05, UC-06, UC-07, UC-08, UC-09, UC-10, UC-11, UC-12, UC-13, UC-14, UC-15, UC-30, UC-31) | ADR-005; ADR-012 | FEAT-018; FEAT-019; FEAT-022; FEAT-027; Foundations | _TBD_ |
| NFR-PERF-02 | Hiệu năng — Tải đồng thời: ≥ 40 trạm/thiết bị cầm tay hoạt động đồng thời, ≥ 600 mẻ/tháng, ≥ 3.000 Cycle ID/ngày. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M6; tham chiếu UC-24, UC-25, UC-26) | ADR-012 | Foundations | _TBD_ |
| NFR-AVAIL-01 | Sẵn sàng — Uptime: ≥ 99,5%/tháng trong giờ vận hành 24/7; bảo trì có kế hoạch ngoài giờ cao điểm. | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M9; tham chiếu UC-32, UC-33) | ADR-001; ADR-011 | Foundations | _TBD_ |
| NFR-AVAIL-02 | Sẵn sàng — Offline tại trạm: Trạm tiếp tục quét ≥ 4 giờ khi mất mạng; đồng bộ tự động khi kết nối lại (FR-M9-06 = Must từ v1.11). | Must | Active | Catalog ISO 25010 / BA #05 | — (áp dụng M2; tham chiếu UC-05, UC-06, UC-07, UC-08, UC-09, UC-10, UC-11, UC-12, UC-13, UC-14, UC-15) | ADR-003; ADR-012 | FEAT-009 | `tracecore/reprocessing/tests/test_packing_offline.py`, `test_receiving_offline.py`; `tracecore/v1/tests/test_usage_offline.py`; `tests_e2e/test_station_offline.py` |
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
| NFR-AVAIL-04 | Sẵn sàng — Thiết bị ngoại vi lỗi không chặn giao dịch; không single point of failure trong chuỗi 8 trạm (cấu hình mặc định, A-64). | Must | Active | Catalog ISO 25010 v1.11 | — | ADR-003; ADR-006; ADR-014 | FEAT-018; FEAT-033; Foundations | _TBD_ |
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

**[NEW v1.12 — A-113] 7 NFR bổ sung** (BA v1.12 §12.1); NFR hiện có áp dụng nguyên cho M11–M17.

| Req ID | Requirement (short) | Priority | Status | Source | Use case(s) | Design ref | Plan ref | Test ref |
| :----- | :------------------ | :------- | :----- | :----- | :---------- | :--------- | :------- | :------- |
| NFR-PRIV-01 | Security — Dữ liệu sức khỏe BN/NV là dữ liệu nhạy cảm (NĐ 356/2025): tối thiểu hóa (không họ tên BN, không kết quả XN NV), mã BN mã hóa (ADR-010), che trên danh sách/export, xem đầy đủ có lý do + Audit Log. Kiểm: test tự động mọi report/export M13, M14, M16 không chứa mã BN rõ; JSON DocType không có trường họ tên BN. | Must | Active | BA v1.12 (A-113) | UC-48, UC-51, UC-55 | ADR-010; ADR-008 | FEAT-056 (F-22); đo lại FEAT-063, FEAT-067, FEAT-071 | _TBD_ |
| NFR-PRIV-02 | Security — Thời hạn lưu dữ liệu ca bệnh, phơi nhiễm cấu hình được; hết hạn xóa định danh, giữ số liệu tổng hợp. Kiểm: job định kỳ có test; thời hạn do bệnh viện quyết (OQ-V12-07). | Must | Active | BA v1.12 (A-113) | UC-48, UC-55 | ADR-010 | FEAT-063, FEAT-071 | _TBD_ |
| NFR-SEC-09 | Security — Ma trận quyền mở rộng cho R11–R13 và mọi DocType mới được kiểm thử tự động từ CSV như NFR-SEC-07; R12, R08 giới hạn theo Department. Kiểm: CI chạy test ma trận. | Must | Active | BA v1.12 (A-113) | — | ADR-010 | FEAT-056 (F-22) | _TBD_ |
| NFR-USAB-03 | Usability — Phiếu giám sát trên PDA: mỗi cơ hội vệ sinh tay ≤ 3 chạm, nút ≥ 48 px, chữ ≥ 16 px, dùng được một tay. Kiểm: E2E PDA 412×915 (khi người dùng cho chạy). | Must | Active | BA v1.12 (A-113) | UC-44 | ADR-002; ADR-015 | FEAT-061 | `tests/test_hygiene_screen.py` (không E2E) |
| NFR-AVAIL-05 | Reliability — Phiếu giám sát, mẫu số, báo phơi nhiễm hoạt động offline ≥ 4 giờ và đồng bộ idempotent (ADR-003, NFR-AVAIL-02). Kiểm: test mất mạng như FR-M12-04. | Must | Active | BA v1.12 (A-113) | UC-44, UC-47, UC-55 | ADR-003 | FEAT-061, FEAT-062, FEAT-071 | _TBD_ |
| NFR-MAINT-04 | Maintainability — Tiêu chí chuyên môn (mẫu phiếu, định nghĩa ca, quy tắc đa kháng, ngưỡng môi trường, bước theo dõi phơi nhiễm) là dữ liệu cấu hình có phiên bản; nâng cấp app không ghi đè bản bệnh viện đã sửa. Kiểm: test migrate hai lần giữ bản đã sửa. | Must | Active | BA v1.12 (A-113) | UC-43, UC-48, UC-51, UC-54, UC-55 | ADR-015 | FEAT-060, FEAT-063, FEAT-067, FEAT-070, FEAT-071 | _TBD_ |
| NFR-PERF-05 | Performance efficiency — Bảng chỉ số KSNK mở ≤ 3 giây với 24 tháng dữ liệu của bệnh viện 1.000 giường (đọc IC Indicator Value, không tính lại khi mở). Kiểm: test hiệu năng với dữ liệu sinh giả. | Must | Active | BA v1.12 (A-113) | UC-57 | ADR-015 | FEAT-065 | _TBD_ |

## 3. Tham chiếu gốc giữ lại

Bảng dưới là **tham chiếu từ bộ BA v1.10** (#15 RTM, #05 SRS, #06 UC), giữ lại để các bước sau (architecture, ux-foundations, implementation-planning, detailed-design, acceptance-verification) đối chiếu và tái sử dụng ID. Đây **không** phải cột Design/Plan/Test do downstream sở hữu: downstream vẫn phải điền cột của mình trong mục 1–2 theo quy tắc append; BRU/SCR/API/TC/US/WF dưới đây có thể được trích dẫn lại nhưng không thay thế nghĩa vụ đó.

| FR | BRU (quy tắc nghiệp vụ) | SCR (màn hình #08) | API (#09, cấp UC) | TC (#14) | US (#07) | WF (#11) |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| FR-M1-01 | — | SCR-01 | API-M1-01, API-M1-06 | TC-01-01, TC-01-02 | US-01 | — |
| FR-M1-02 | — | SCR-01 | API-M1-01, API-M1-06 | TC-01-01, TC-01-02 | US-01 | — |
| FR-M1-03 | BRU-REP-009 | SCR-02 | API-M1-02 | TC-02-01, TC-02-02 | US-02 | — |
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
| FR-M3-07 | BRU-EQP-002 | SCR-21 | — | — | — | — |
| FR-M3-08 | BRU-LIN-005 | SCR-21 | — | — | — | — |
| FR-M3-09 | BRU-LIN-006, BRU-LIN-007 | SCR-17 | API-M3-02 | — | — | WF-04 |
| FR-M3-10 | — | SCR-21 | — | — | — | — |
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
| FR-M9-17, FR-M9-18 | — | Desk TraceCore Settings, danh mục mã lỗi | — (A-71) | FEAT-052 | — | — |
| FR-M9-19 | — | mọi SCR trạm/PDA, màn đăng nhập trạm | — (A-71) | FEAT-052 | — | — |
| FR-M9-20, FR-M9-21 | — | Desk Nhật ký lỗi, báo cáo | — (A-71) | FEAT-052 | — | — |
| FR-M5-07 | — | SCR-06 | — (A-71) | FEAT-052 | — | — |
| FR-M5-02.6, FR-M5-02.7, FR-M5-02.8 | BRU-INV-003 | Desk Process Program, báo cáo Program Consumable Gaps | — (A-111) | FEAT-054 | — | `tracecore/core/tests/test_run_consumables.py` |
| FR-M2-03.9, FR-M2-09.9, FR-M5-05.5 | BRU-INV-003 | SCR-06, SCR-09, SCR-23 | — (A-111) | FEAT-054 | — | `tracecore/reprocessing/tests/test_run_consumables_station.py` |
| FR-M6-03, FR-M6-03.5 | BRU-INV-002, BRU-INV-003 | SCR-25 | — (A-111) | FEAT-054 | — | `tracecore/inventory/tests/test_consume_actual.py` |
| FR-M6-02.4 | — | SCR-24 (Desk Item) | — (A-112) | FEAT-055 | — | `tracecore/inventory/tests/test_consumable_reports.py` |
| FR-M6-03.6, FR-M6-03.7, FR-M6-03.10 | BRU-INV-001, BRU-INV-004 | SCR-06, SCR-09, SCR-10, SCR-23 | — (A-112) | FEAT-055 | — | `tracecore/core/tests/test_lots.py`, `tracecore/reprocessing/tests/test_indicator_lots.py` |
| FR-M6-03, FR-M6-03.5, FR-M6-03.8 | BRU-INV-004 | SCR-25 | — (A-112) | FEAT-055 | — | `tracecore/inventory/tests/test_consume_lots.py` |
| FR-M2-03.10, FR-M2-09.10, FR-M6-03.9 | BRU-REP-018 | SCR-06, SCR-09 (Desk Wash Batch, Sterilization Load) | — (A-112) | FEAT-055 | — | `tracecore/reprocessing/tests/test_run_cancel.py` |
| FR-M6-07, FR-M6-08 | — | SCR-25, SCR-26 (báo cáo Consumable Usage, Consumable Lot Trace) | — (A-112) | FEAT-055 | — | `tracecore/inventory/tests/test_consumable_reports.py` |
| FR-M1-03.7, FR-M1-03.8 | BRU-REP-017, BRU-REP-004 | SCR-02 (Desk Loại bộ) | — (A-110) | FEAT-053 | — | `tracecore/core/tests/test_program_match.py` |
| FR-M5-02.5 | — | Desk Process Program | — (A-110) | FEAT-053 | — | `tracecore/core/tests/test_program_match.py` (`TestProgramSetTypes`) |
| FR-M2-03.7, FR-M2-03.8 | BRU-REP-017 | SCR-06 | — (A-110) | FEAT-053 | — | `tracecore/reprocessing/tests/test_set_program_station.py`, `tracecore/tests/test_station_program_match_assets.py` |
| FR-M2-09.7, FR-M2-09.8 | BRU-REP-017 | SCR-09 | — (A-110) | FEAT-053 | — | `tracecore/reprocessing/tests/test_set_program_station.py`, `tracecore/tests/test_station_program_match_assets.py` |
| FR-M2-08, FR-M2-08.1, FR-M2-08.2, FR-M2-08.8 | BRU-REP-011 (thu hẹp), BRU-ID-005 | SCR-06, SCR-08, SCR-09, Desk TraceCore Settings, Printer | — (A-114) | FEAT-075 | — | — |
| FR-M1-05.4, FR-M10-01.5, EI-HW-002, EI-HW-003, EI-HW-007, EI-HW-008 | BRU-ID-006 | SCR-02, SCR-38, Desk in thẻ bộ, nhãn QR đối tượng | — (A-114) | FEAT-075 | — | — |
| FR-M10-01, FR-M10-02 | BRU-WST-001, BRU-WST-002, BRU-ID-006 | SCR-38 (mới) | — (v1.11) | — | — | — |
| FR-M10-03 | BRU-WST-001, BRU-WST-002 | SCR-39 (mới) | — (v1.11) | — | — | — |
| FR-M10-04, FR-M10-05 | BRU-WST-003, BRU-WST-004, BRU-CST-002 | SCR-40 (mới) | — (v1.11) | — | — | WF-06 (NC) |
| FR-M10-06, FR-M10-07, FR-M10-08 | BRU-WST-001, BRU-WST-002 | SCR-41 (mới), SCR-32 | — (v1.11) | — | — | WF-06 (NC) |

Kiểm thử NFR: 14 NFR gốc tham chiếu "#14 mục 3.1 (TC phi chức năng, UAT)" theo #15 §2.3; 21 NFR mới v1.11 chưa có TC — acceptance-verification bổ sung. Dòng FR mới v1.11 (FR-M9-08..16, FR-M10-*) chưa có API/TC/US trong bộ BA v1.10; các bước detailed-design và acceptance-verification điền.

## 4. Kiểm đếm và điểm bất nhất

| Chỉ tiêu | Kết quả |
| :-- | :-- |
| Dòng FR trong RTM | 175 (94 dòng trước A-113 — 73 gốc + 9 FR-M9-08..16 + 8 FR-M10-01..08 + 4 dòng amendment — + [A-113] 81 FR-M11..M17 & FR-M9-24..30) |
| Dòng NFR trong RTM | 42 (14 gốc + 21 mới v1.11 + [A-113] 7 mới v1.12) |
| UC trong docs/use-cases.md | 57 (UC-01..33 gốc + UC-34..39 mới + [A-113] UC-40..57) |
| SCR | 63 đã duyệt (SCR-01..37 gốc + SCR-38..43 mới + [A-113] SCR-47..66; SCR-44..46 đề xuất chưa duyệt) |
| FR không có UC | 0 — FR-M9-14/15 là yêu cầu xuyên suốt, ghi "—" kèm danh sách UC trạm |
| UC không có FR | 0 — rỗng |
| FR xuất hiện ở UC nhưng không có trong srs.md §3.1 | 0 — rỗng |
| FR có >1 UC | 0 (mỗi FR thuộc đúng một UC sở hữu, như #15; giữ nguyên cho 81 FR v1.12) |
| Bộ Số Chuẩn BA v1.10 → v1.11 | N_MOD 9→10, N_FR 73→90, N_NFR 14→35, N_UC 33→39, N_SCR 37→43 |
| Bộ Số Chuẩn v1.11 → v1.12 (A-113) | N_MOD 10→17, N_FR 90→171, N_NFR 35→42, N_UC 39→57, N_SCR 43→63, N_BRU 49→83, ADR 14→15, FEAT 55→74, vai trò 10→13 |

**Điểm bất nhất phát hiện khi import (d05 / d06 / d15):**

- FR-M9-06: ưu tiên bảng 2.1 = Should, mục chi tiết 2.2 = Must — ✅ đã chốt Must ngày 2026-10-17 theo NFR-AVAIL-02 (OQ-08).
- Thứ tự ID trong #05 §2.1 và #15 không theo số (FR-M2-23 đứng sau FR-M2-02; FR-M2-24/25 giữa FR-M2-03 và FR-M2-04; FR-M9-07 trước FR-M9-06) — RTM giữ nguyên thứ tự này theo yêu cầu import; không ảnh hưởng ID.
- #05 bảng 2.1 không có cột Nguồn BR; nguồn BR lấy từ mục chi tiết 2.2 (trường "Nguồn BR"), khớp 100% với tiền tố phân hệ (FR-Mx → BR-Mx).
- #06 trường 25 "Vấn đề mở" dùng chung một câu cho cả nhóm UC (UC-01..15 một câu, UC-16..33 một câu), không phải vấn đề mở riêng từng UC — đã chép nguyên vào docs/use-cases.md, cần rà lại khi finalize.
- Nhãn ngoại lệ UC-08 trong #06 có thứ tự E1, E4, E5, E2, E3 (do bổ sung ở v1.3/v1.10) — giữ nguyên nhãn để TC-08-xx tham chiếu được.
- #15 §2.2 ghi BRU-FLOW-004 áp dụng "UC-06..UC-11" nhưng #06 trường 13 chỉ liệt kê BRU-FLOW-004 tại UC-06, 07, 08, 09, 10, 11 (khớp); BRU-ID-005 và BRU-LIN-002, BRU-HR-002 chỉ gắn FR, không gắn UC trong #15 §2.2 — RTM mục 3 lấy theo #15 §2.1 (cấp FR) nên vẫn đủ.
