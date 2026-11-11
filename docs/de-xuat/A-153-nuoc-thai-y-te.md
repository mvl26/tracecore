# Đề xuất Amendment A-153 — Quản lý nước thải y tế (M15 mở rộng, FEAT-095)

> Trạng thái: **ĐÃ DUYỆT phía người dùng 12/11/2026 (W1–W8 theo đề xuất; chủ đầu tư chưa xác nhận).** Đã ghi vào srs, architecture, use-cases, ux-foundations, implementation-plan, rtm. Chưa code (FEAT-095).
> Ngày: 12/11/2026 · Người lập: Claude Code · Yêu cầu: người dùng trong chat ("bổ sung quản lý nước thải: lịch quan trắc, kết quả quan trắc theo quy định").
> Lý do phải amend: SRS §1.2.2 đang để **"Chất thải y tế lỏng và khí (nước thải, khí thải)" ngoài phạm vi** [v1.11, SC-01]. Thêm DocType ngoài architecture §5.3 → bắt buộc amendment (CLAUDE.md).

---

## 1. Căn cứ pháp lý (đối chiếu trước khi duyệt)

| Văn bản | Nội dung dùng cho thiết kế |
| --- | --- |
| Luật BVMT 2020, Điều 111; NĐ 08/2022/NĐ-CP Điều 97 (sửa bởi NĐ 05/2025/NĐ-CP, NĐ 48/2026/NĐ-CP) | Quan trắc nước thải định kỳ phải đúng thời gian, tần suất, thông số; thông số đã quan trắc tự động liên tục thì không phải quan trắc định kỳ. |
| QCVN 40:2025/BTNMT (TT 06/2025/TT-BTNMT, hiệu lực 01/9/2025) | Thay QCVN 28:2010/BTNMT (nước thải y tế). Chưa xác định phân vùng xả thải → áp dụng cột B. |
| Điều khoản chuyển tiếp TT 06/2025 | Cơ sở đang hoạt động có thể còn áp dụng QCVN 28:2010 theo giấy phép môi trường (GPMT) đến hết lộ trình (nhiều GPMT ghi đến 31/12/2031) → **hệ thống phải chạy song song 2 quy chuẩn**. |
| Giấy phép môi trường của từng bệnh viện | **Nguồn sự thật**: vị trí quan trắc, danh mục thông số, giá trị giới hạn, tần suất (thường 3 hoặc 6 tháng/lần), quan trắc tự động hay không. Mỗi BV khác nhau. |
| TT 02/2022/TT-BTNMT (sửa bởi TT 07/2025/TT-BTNMT) | Kết quả quan trắc đưa vào báo cáo công tác BVMT hằng năm. TraceCore chỉ **xuất số liệu**, không nộp thay. |
| TT 31/2013/TT-BYT (quan trắc môi trường bệnh viện) | Tham khảo; **cần kiểm tra còn hiệu lực** trước khi trích trong FR. |

Nguyên tắc rút ra: **không mã hóa cứng QCVN trong code** — R01 nhập theo GPMT của BV; bộ QCVN 40:2025 cột A/B và QCVN 28:2010 chỉ là fixtures Nháp có phiên bản, chờ chuyên gia BV duyệt (NFR-MAINT-04).

## 2. Quyết định cần duyệt

| ID | Quyết định đề xuất | Phương án khác |
| --- | --- | --- |
| **W1** | Mở một phần SC-01: **nước thải vào M15** (module `Environmental Hygiene`). Khí thải vẫn ngoài phạm vi. | Module riêng M18 → thêm Module Def, tách vai trò; không lợi gì vì M15 đã có mẫu ngưỡng–mẫu–NC. |
| **W2** | Danh mục thông số + giới hạn + tần suất lấy từ **GPMT có phiên bản** (`Wastewater Permit`), không từ `Environmental Limit` (vì 1 đợt quan trắc có 10–15 thông số, ngưỡng gắn với điểm xả và quy chuẩn/cột). | Dùng lại `Environmental Limit` từng thông số → 15 bản ghi/điểm, khó đối chiếu GPMT. |
| **W3** | **Lịch quan trắc tính theo kỳ lịch** (quý / 6 tháng / năm theo tần suất GPMT): kỳ có ≥ 1 đợt ghi sổ đủ thông số = "Đã quan trắc". Không tạo DocType lịch. | Lưu từng lần hẹn như `Sampling Plan Zone` → phải đồng bộ khi đổi GPMT. |
| **W4** | Vượt giới hạn → cờ điểm xả "Vượt chuẩn – chờ quan trắc lại", thông báo, đề nghị NC loại Environment qua hook `tracecore_environment_nc` có sẵn (BRU-ENV-003 mở rộng). | Không mở NC, chỉ cảnh báo. |
| **W5** | Đơn vị quan trắc = `Supplier` (đã có ở SCR-54) + số **VIMCERTS** và hạn; cảnh báo khi hết hạn như giấy phép thuê ngoài. | Ghi tên lab dạng chữ. |
| **W6** | **Nhật ký vận hành HTXLNT hằng ngày** (lưu lượng m³, clo dư/chất khử trùng, sự cố): **Should, giai đoạn 2** — không làm trong FEAT-095. | Làm luôn (thêm 1 DocType + PDA form). |
| **W7** | Người dùng: R01 cấu hình GPMT/điểm; **R11 + người phụ trách HTXLNT** nhập kết quả (cấp vai trò R11 hoặc gán `responsible_user` cho điểm xả, thường thuộc phòng HCQT); R02 xem; R13 xem tổng hợp. | Chỉ R01/R11 nhập. |
| **W8** | Quan trắc tự động liên tục: **chỉ đánh dấu** thông số "tự động" (loại khỏi lịch định kỳ), không kết nối trạm (giữ D3). | Nhập file CSV từ trạm tự động qua `Import Mapping Profile`. |

## 3. Thiết kế (khi W1–W8 theo đề xuất)

### 3.1 DocType mới (module Environmental Hygiene)

| DocType | Naming | Submittable | Trường chính |
| --- | --- | --- | --- |
| `Wastewater Point` | `NT-.##` | Không | `point_name`, `point_type` (Inlet / Outlet / Discharge), `treatment_system` (Data: tên HTXLNT), `design_capacity_m3_day`, `receiving_source`, `coordinates`, `responsible_user` (Link User), `awaiting_remonitor` (chỉ dịch vụ ghi), `disabled` |
| `Wastewater Permit` | `GPMT-<permit_code>-V<n>` (`core.versioning`) | Có — bản đã duyệt khóa, sửa = phiên bản mới | `permit_no`, `issued_on`, `valid_until`, `issuing_authority`, `standard` (QCVN 40:2025 / QCVN 28:2010 / Khác), `standard_column` (A / B / C), `factor_note`, `effective_from`, `superseded_by`, `attachment`, `parameters` (Table) |
| `Wastewater Permit Parameter` (child) | — | — | `wastewater_point`, `parameter`, `unit`, `min_value`, `max_value`, `frequency_months` (3 / 6 / 12), `auto_monitored` (Check), `legal_ref` |
| `Wastewater Monitoring` | `QTNT-.YYYY.-.####` | Có | `wastewater_point`, `wastewater_permit` (bản hiệu lực tại `sampled_on`), `period_label` (vd "Quý 4/2026"), `sampled_on`, `supplier`, `vimcerts_no`, `report_no`, `attachment`, `is_remonitor_of`, `results` (Table), `overall_result` (Pass / Fail), `nc_status`, `nc_name`, `nc_reason` |
| `Wastewater Result` (child) | — | — | `parameter`, `value`, `below_detection` (Check, "KPH"), `unit`, `limit_applied` (bản chụp min–max + quy chuẩn), `result` (Pass / Fail) |

Thêm vào `Supplier` (Custom Field, như SCR-54): `vimcerts_no`, `vimcerts_valid_until`.

### 3.2 Quy tắc nghiệp vụ mới

- **BRU-ENV-004** Giới hạn áp dụng = phiên bản GPMT có hiệu lực tại ngày lấy mẫu; đổi GPMT sau đó không đổi kết quả cũ (cùng tinh thần BRU-ENV-002).
- **BRU-ENV-005** Đợt quan trắc Không đạt nếu ≥ 1 thông số ngoài [min, max]; kết quả "KPH" (dưới giới hạn phát hiện) tính là Đạt với giới hạn trên.
- **BRU-ENV-006** Một kỳ của (điểm xả, thông số không tự động) chỉ "Đã quan trắc" khi có đợt ghi sổ trong kỳ có giá trị cho thông số đó; thiếu thông số → "Thiếu thông số", không phải "Đã quan trắc".

### 3.3 Yêu cầu chức năng (SRS-lite, EARS)

| FR | Câu EARS | AC (tiêu chí nghiệm thu) | Ưu tiên |
| --- | --- | --- | --- |
| FR-M15-08 | Khi R01 khai báo GPMT, hệ thống phải bắt buộc số GPMT, quy chuẩn, cột, ngày hiệu lực và ít nhất 1 thông số có điểm xả, giới hạn, tần suất. | Thiếu tần suất → không lưu được, báo trường thiếu. GPMT còn ≤ 90 ngày hết hạn → badge cam "Còn N ngày". | Must |
| FR-M15-08.1 | Khi GPMT đã duyệt được sửa, hệ thống phải tạo phiên bản mới và giữ nguyên phiên bản cũ. | Sửa V1 → sinh V2, V1 có `superseded_by`. | Must |
| FR-M15-09 | Hệ thống phải hiển thị lịch quan trắc 12 tháng theo điểm xả × kỳ với trạng thái Đã quan trắc / Thiếu thông số / Đến hạn / Quá hạn / Không áp dụng (tự động). | Tần suất 3 tháng, quý 4 chưa có đợt, hôm nay sau 31/12 → "Quá hạn". Trạng thái có chữ, không chỉ màu. | Must |
| FR-M15-09.1 | Khi còn 15 ngày đến cuối kỳ mà chưa có đợt, hệ thống phải nhắc R01, R11 và người phụ trách điểm xả; khi quá hạn phải nhắc R01. | Sự kiện `WW_MONITORING_DUE`, `WW_MONITORING_OVERDUE`, mỗi kỳ nhắc 1 lần. | Must |
| FR-M15-10 | Khi R11 ghi đợt quan trắc, hệ thống phải tự nạp danh sách thông số của điểm xả theo GPMT hiệu lực tại ngày lấy mẫu, so từng giá trị với giới hạn và lưu bản chụp giới hạn. | pH 9,2 với giới hạn 6–9 → Fail; COD "KPH" → Pass. Đổi GPMT sau đó, đợt cũ giữ kết quả. | Must |
| FR-M15-10.1 | Hệ thống phải bắt buộc đính kèm phiếu kết quả của đơn vị quan trắc khi ghi sổ. | Không có file → không Submit được. | Must |
| FR-M15-11 | Nếu đợt quan trắc Không đạt, thì hệ thống phải gắn cờ điểm xả, thông báo R01, R11, người phụ trách, đề nghị mở NC loại Environment và tạo việc quan trắc lại; cờ tắt khi đợt quan trắc lại Đạt. | Cờ "Vượt chuẩn – chờ quan trắc lại" có chữ trên danh sách điểm; R01 bỏ qua NC phải ghi lý do (Audit Log). | Must |
| FR-M15-12 | Khi người dùng xuất báo cáo nước thải theo kỳ hoặc năm, hệ thống phải xuất bảng kết quả từng điểm × thông số × đợt kèm giới hạn và số vượt, dạng PDF/Excel. | Số liệu khớp màn SCR-67; dùng làm phụ lục báo cáo công tác BVMT năm. | Must |
| FR-M15-13 | Hệ thống phải cảnh báo đơn vị quan trắc có VIMCERTS hết hạn và chặn chọn đơn vị đã hết hạn tại ngày lấy mẫu. | VIMCERTS hết hạn 01/10/2026, mẫu ngày 05/10/2026 → báo lỗi inline. | Should |
| FR-M15-13.1 | Hệ thống phải chỉ cho R01 cấu hình GPMT/điểm xả; R11 và người phụ trách điểm xả ghi đợt; R02 xem; R13 xem tổng hợp. | Kiểm tra DocPerm + RPC. | Must |

### 3.4 Giao diện, RPC, sự kiện

- **SCR-67 "Nước thải"** — Page `tc-ksnk` slug `nuoc-thai`, nhóm rail "Môi trường – nghề nghiệp", UC-58 mới. 3 khối: (1) thẻ GPMT hiện hành (số, quy chuẩn/cột, hạn); (2) lưới lịch điểm xả × kỳ 12 tháng; (3) bảng đợt gần nhất từng điểm (thông số vượt tô đỏ + chữ "Vượt"). Actions bar: Ghi đợt quan trắc · Xuất báo cáo · Cập nhật GPMT. Đủ 4 trạng thái loading/empty/error/offline.
- RPC `tracecore.v1.wastewater.overview / schedule / open_nc / dismiss_nc`.
- Badge rail: số kỳ quá hạn + số điểm đang cờ.
- Print Format `Wastewater Monitoring`; Script Report `Wastewater Monitoring Summary`.
- Gộp vào FR-M15-07 (báo cáo môi trường tháng/quý) một dòng tóm tắt nước thải; SCR-66 thêm KPI "Tỷ lệ kỳ quan trắc nước thải đúng hạn" (chỉ R13 xem tổng hợp).

### 3.5 Tài liệu phải cập nhật khi duyệt

`srs.md` (Revision History A-153, §1.2.2 sửa SC-01, §3.1.15 thêm FR-M15-08..13, Appendix A BRU-ENV-004..006, Appendix C) · `architecture.md` §5.3 (5 DocType + custom field Supplier, naming §5.3.3, ma trận quyền DT-WWPOINT, DT-WWPERMIT, DT-WWMON) · `use-cases.md` UC-58 · `ux-foundations.md` SCR-67 (N_SCR 63 → 64) · `implementation-plan.md` FEAT-095 · `rtm.md`.

### 3.6 Ngoài phạm vi

Khí thải; nhật ký vận hành HTXLNT hằng ngày (W6); kết nối trạm quan trắc tự động (W8); nộp báo cáo lên hệ thống của Sở/Bộ; quản lý hóa chất xử lý nước thải (nếu cần, thêm cột ở SCR-54 sau).

## 4. Ước lượng

FEAT-095 ≈ 1 sprint dev (5 DocType, 1 màn Page, 2 RPC đọc + 2 RPC ghi, 1 report, ~25 test `FrappeTestCase` gắn `@bru("BRU-ENV-004..006")`). Làm trên nhánh `feat/FEAT-095-wastewater` trong bench dev (WSL), không làm trong môi trường hiện tại vì không có bench để chạy test.
