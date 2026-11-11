# FEAT-070 — Vùng vệ sinh và giám sát môi trường (M15) — kế hoạch

> Nhánh `feat/FEAT-070-environmental-hygiene` (bench `~/tracecore-f032`, site test `test_f032`), cắt từ develop 2436b7e.
> Amendment **A-148**. Đầu vào: implementation-plan §3 E-16 dòng FEAT-070; srs §3.1.15 FR-M15-01..07, BRU-ENV-001..003;
> use-cases UC-54; ux-foundations SCR-62 (WEB), SCR-52 (PDA); architecture §5.3.1 M15, §5.3.3; ảnh `SCR-62_MoiTruong.png`.

## Quyết định của người dùng (10/11/2026, chọn cả 4 phương án đề xuất)

| # | Câu hỏi | Chọn |
| --- | --- | --- |
| Q1 | Danh sách mức nguy cơ (BRU-ENV-001) lưu ở đâu | DocType nhỏ mới `Environment Risk Level` (tên mức, số phiếu tối thiểu/tháng, thứ tự, `legal_ref`, tính là nguy cơ cao); nạp 4 mức QĐ 3916 nếu chưa có; vùng Link tới mức, tự điền số phiếu tối thiểu, sửa được |
| Q2 | "Hệ thống" hạ tầng và `next_due` | `Audit Template` thêm `infra_category` (Thông khí / Cấp nước / Nhà vệ sinh / Côn trùng / Phòng cách ly / Khác) và `inspection_interval_days`; một hệ thống = cặp (mã mẫu hạ tầng, vùng); phiếu tự điền `next_due` = ngày phiếu + chu kỳ, người kiểm tra sửa được; không thêm DocType |
| Q3 | Tên ngưỡng và bộ khởi tạo | Tên `NG-<limit_code>-V<n>` (như Audit Template), nạp vài ngưỡng Nháp ví dụ ghi rõ "cần R01 duyệt"; `bench migrate` không ghi đè |
| Q4 | Mẫu Không đạt | Ghi sổ mẫu Không đạt: cờ vùng, ToDo lấy mẫu lại, thông báo R01/R11/bên chịu trách nhiệm, `nc_status` = Đề nghị; R01/R11 bấm "Mở NC Environment" → `Incident CAPA` (thêm loại/nhóm Environment) hoặc bỏ qua có lý do; mẫu lại Link `is_resample_of`, Đạt thì tắt cờ |

## Thiết kế (A-148)

DocType mới, module `Environmental Hygiene` (`tracecore/environmental_hygiene/`):

| DocType | Tên | Ghi chú |
| --- | --- | --- |
| Environment Risk Level (Q1) | `field:risk_name` | `risk_name`, `sort_order`, `min_audits_per_month`, `is_high_risk`, `legal_ref`, `disabled` |
| Environment Zone | `VV-.####` | `department`*, `area_name`*, `risk_level`* (Link), `cleaning_frequency`, `cleaning_chemical` (Item), `responsible_party`* (Department / Outsourced Vendor), `supplier` (bắt buộc khi thuê ngoài), `min_audits_per_month` (trống → lấy từ mức), `awaiting_resample` + `flag_sample` (chỉ dịch vụ ghi), `disabled` |
| Environmental Limit | `NG-<limit_code>-V<n>`, submittable | `limit_code`, `title`, `sample_type`, `method`, `parameter`, `min_value` (tùy chọn), `limit_value` (ngưỡng trên), `unit`, `applies_to_risk_level`, `legal_ref`, `version_no`, `effective_from`, `superseded_by`; bản đã duyệt khóa, sửa = `new_version` |
| Sampling Plan | `KLM-.YYYY.-.###` | `title`, `sample_type`, `limit_code`, `frequency` (Weekly…Annual), `assignee` (Employee), `active`, child **Sampling Plan Zone** (`environment_zone`, `next_due`, `last_sampled_on`, `overdue_notified`) |
| Environmental Sample | `XN-.YYYY.-.#####`, submittable | `environment_zone`, `department`/`risk_level`/`responsible_party`/`supplier` (fetch), `sample_type`, `method`, `limit_code`, `sampled_on`, `sampled_by`, `lab`, `sampling_plan`, `result_value`, `unit`, `environmental_limit` + `limit_applied` (bản chụp), `result`, `is_resample_of`, `attachment`, `nc_status`, `nc_name`, `nc_reason` |

Chạm M12 (chỉ thêm trường, đọc qua Link/`frappe.get_all`, không import chéo): `Audit Session` + `environment_zone`, `next_due`;
`Audit Template` + `infra_category`, `inspection_interval_days`; `compliance_audit/pda.py` trả `zones` và nhận
`environment_zone`, `next_due`; `station_audit.js` chọn vùng khi mẫu loại Vệ sinh môi trường / Cơ sở hạ tầng; seed thêm
mẫu Nháp "Cơ sở hạ tầng — thông khí", "— cấp nước" và "An toàn thực phẩm" (dòng FEAT-061 ghi ATTP ở FEAT-070).
Kiểm phiếu gắn vùng chạy ở M15 qua `doc_events["Audit Session"]["validate"]`.

M2: `Incident CAPA.incident_type` + "Environment Nonconformity", `incident_category` + "Environment"; hook mới
`tracecore_environment_nc` → `reprocessing.incidents.on_environment_nc`.

## Task (TDD: test `FrappeTestCase` trước, thấy đỏ, rồi code)

1. **Docs A-148** — Revision History architecture + srs; §5.3.1 M15 (Risk Level, Sampling Plan Zone, trường mới Audit
   Template/Session, Incident CAPA); §5.3.3 naming NG; ux SCR-62; rtm FR-M15-01..07; dòng FEAT-070.
2. **Risk Level + Zone** (FR-M15-01, .1, .2; BRU-ENV-001; UC-54 E1) — test: thiếu mức/bên chịu trách nhiệm → chặn;
   thuê ngoài thiếu NCC → chặn; số phiếu tối thiểu lấy từ mức; vùng nguy cơ cao 4 phiếu/tháng mới có 1 → vào danh sách
   thiếu (`@bru("BRU-ENV-001")`); R12 chỉ thấy vùng khoa mình.
3. **Environmental Limit** (FR-M15-03; BRU-ENV-002; NFR-MAINT-04) — test: tên `NG-<mã>-V<n>`; bản duyệt khóa;
   `new_version`; `active_limit(code, date)` lấy phiên bản hiệu lực tại ngày; seed Nháp, migrate 2 lần giữ bản đã sửa.
4. **Environmental Sample** (FR-M15-03, .1, FR-M15-04, .1; BRU-ENV-002, BRU-ENV-003; UC-54 E2, E5) — test: so ngưỡng
   hiệu lực tại `sampled_on`, lưu bản chụp; đổi ngưỡng sau không đổi mẫu cũ; Không đạt → cờ vùng, ToDo, thông báo,
   `nc_status` Suggested; mẫu lại Đạt → tắt cờ; mẫu lại Không đạt → cờ giữ, ToDo mới, NC không lặp; `open_nc` tạo
   Incident Environment (idempotent), `dismiss_nc` cần lý do.
5. **Sampling Plan + scheduler** (FR-M15-05, .1) — test: đến kỳ tạo ToDo cho người phụ trách (một lần); mẫu ghi sổ đẩy
   `next_due`, đóng ToDo; mẫu trễ hạn liệt kê; quá hạn 7 ngày nhắc R01 một lần.
6. **Phiếu VSMT/hạ tầng gắn vùng** (FR-M15-02, .1, FR-M15-06, .1) — test: phiếu VSMT/hạ tầng của khoa có vùng phải chọn
   vùng cùng khoa; hạ tầng tự điền `next_due`; tỷ lệ đạt theo mức/khoa/bên chịu trách nhiệm (tách từng NCC); hệ thống
   quá hạn không tính đúng hạn; nhắc trước 7 ngày; PDA context có `zones`, submit lưu vùng.
7. **Chỉ số + báo cáo** (FR-M15-07, .1; QĐ 38) — hook `tracecore_ic_indicators`: bề mặt nguy cơ cao đạt, mẫu đạt,
   thông khí/nước đúng hạn; Script Report "Environmental Hygiene" tháng/quý gộp VSMT, xét nghiệm, hạ tầng, hóa chất bề mặt
   (cùng nguồn `IC Chemical Consumption` với báo cáo M12); Print Format mẫu môi trường.
8. **SCR-62** — Page `tc-ksnk` slug `moi-truong` (nhóm environment; R01, R02, R11, R13 tổng hợp, System Manager); RPC
   `tracecore.v1.environment.overview / open_nc / dismiss_nc`; badge vùng chờ lấy mẫu lại + mẫu chờ quyết định NC.
9. **Quyền, thông báo, mã lỗi** — 5 dòng ma trận (86 → 91), `custom_docperm` sinh lại; EVENTS ENV_SAMPLE_FAILED,
   ENV_SAMPLING_DUE, ENV_SAMPLE_OVERDUE, ENV_INFRA_DUE; mã ENV_* vào `UNMAPPED_BLOCK_CODES`; vi.csv.
10. **Kiểm** — test từng module `--module`, test quyền/nav, diff-cover ≥ 70 %, pre-commit; push nhánh.

## Ngoài phạm vi / follow-up

- UC-54 A3 (mẫu gắn CAPA ổ dịch, FEAT-069), A4 (phiếu hạ tầng cập nhật `Isolation Room.checked_on`): chưa làm.
- Mẫu thực phẩm (A1) dùng `sample_type` Food sẵn có; luồng ATTP ở FEAT-073.
- DEPT view SCR-52: phiếu VSMT chạy trên PDA (như FEAT-062), Cổng khoa chưa có form phiếu.
