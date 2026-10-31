# FEAT-049 Đơn vị xử lý và phiếu bàn giao chất thải — kế hoạch

Đầu vào: implementation-plan §3 FEAT-049; FR-M10-03.5, FR-M10-04, .1-.6, FR-M10-05, .1-.4; UC-36; SCR-40; BRU-WST-003, BRU-WST-004, BRU-CST-002; amendment A-62.

| Task | Nội dung | Đáp ứng |
| --- | --- | --- |
| 1 | `Waste Treatment Vendor` + child loại được phép, hợp đồng; hết hiệu lực, báo 60/30/7 ngày | FR-M10-05, .1-.3; BRU-WST-003 |
| 2 | `Waste Handover` + child dòng, túi; lập phiếu, FIFO, thêm/bỏ túi | FR-M10-04; FR-M10-03.4, .5 |
| 3 | Kg, chênh lệch, lý do, R02 duyệt, NC | FR-M10-04.1; BRU-WST-004 |
| 4 | Chứng từ CTNH, Chờ chứng từ, chữ ký hai bên | FR-M10-04.2, .3; UC-36 A4 |
| 5 | Giá hợp đồng/mặc định chốt lúc ghi sổ; Cost Entry theo khoa; hủy phiếu | FR-M10-04.5, .6; FR-M10-05.4; BRU-CST-002 |
| 6 | RPC, tab Bàn giao trên trạm WST, Print Format | SCR-40; FR-M9-14 |
