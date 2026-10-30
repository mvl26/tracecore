# FEAT-048 Kho lưu giữ tạm chất thải — kế hoạch

Đầu vào: implementation-plan §3 FEAT-048; FR-M10-03, .1-.4; UC-35; SCR-39; BRU-WST-001, BRU-WST-002; amendment A-61.
FR-M10-03.5 (đề xuất FIFO) dùng ở phiếu bàn giao, làm cùng FEAT-049.

| Task | Nội dung | Đáp ứng |
| --- | --- | --- |
| 1 | DocType `Waste Storage Location` (`KE-`, kho lạnh, khu) + child `Waste Storage Location Type` (loại được phép, vị trí mặc định) | FR-M10-03, .1; BRU-ID-006 |
| 2 | `Waste Container`: trạng thái Stored, vị trí, giờ nhập kho, cờ lưu lạnh, mốc đã cảnh báo | FR-M10-03; BRU-WST-002 |
| 3 | `waste.storage.store`, `store_collection`: quét túi + vị trí, sai loại thì chặn kèm vị trí đúng, nhập cả phiếu, chuyển vị trí tính lại hạn | FR-M10-03, .1; UC-35 A1, A2, E1, E4; BRU-WST-001 |
| 4 | `run_checks` 15 phút: 80 % cảnh báo, quá hạn cảnh báo đỏ + NC | FR-M10-03.3, .4; BRU-WST-002 |
| 5 | Nhiệt độ kho lạnh qua `Environment Log`; > 8 °C quá 2 giờ thì áp lại hạn lưu thường | FR-M10-03.2; UC-35 E2; BRU-WST-002 |
| 6 | Ngưỡng cấu hình ở `TraceCore Settings`; R02 sửa qua nút trên báo cáo | UC-35 Open issues; người dùng chốt 30/10/2026 |
| 7 | RPC `tracecore.v1.waste.stock/store/record_temperature`, màn trạm tab Kho (SCR-39) đủ 4 trạng thái | FR-M9-14; SCR-39 |
| 8 | Script Report `Waste Storage Stock` cho R02 trên Desk | UC-35 A3 |

Kiểm tra: `waste.tests.test_storage`, `v1.tests.test_waste_api`, `waste.tests.test_waste_station_assets`, `reprocessing.tests.test_incidents`, coverage changed-code ≥ 70 %, `pre-commit`.
