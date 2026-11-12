# FEAT-095 — Nước thải y tế (Amendment A-153) — kế hoạch hiện thực

> Đầu vào: `docs/implementation-plan.md` FEAT-095 + AC-095-01..14; `docs/srs.md` FR-M15-08..13, BRU-ENV-004..006,
> Appendix C (W1–W8); `docs/use-cases.md` UC-58; `docs/ux-foundations.md` SCR-67; `docs/architecture.md` Revision
> History A-153 và §5.3 M15. Bản mẫu giao diện: file HTML người dùng gửi kèm ticket (12/11/2026).
> Nhánh `feat/FEAT-095-wastewater`, bench `~/tracecore-f043`, site `test_f043`. TDD: test `IsolatedTestCase` viết
> trước, chạy thấy đỏ, rồi mới code. Mỗi BRU có test gắn `@bru`.

## Quyết định đã chốt (12/11/2026)

W1–W8 theo đề xuất A-153; FEAT-095 thay FEAT-075; người phụ trách HTXLNT được cấp R11 (responsible_user chỉ nhận
nhắc); TT 31/2013 chỉ tham khảo; thêm `permit_code`; QCVN 40:2025 chưa có văn bản → mẫu chỉ có danh mục thông số.

## Thiết kế ngắn

- Package `tracecore/environmental_hygiene/`: `wastewater.py` (GPMT, phiên bản, đánh giá, đợt, cờ, NC),
  `wastewater_schedule.py` (kỳ, lịch, nhắc), `wastewater_report.py` (số liệu báo cáo + tóm tắt), `data/wastewater_standards.json`.
- Kỳ: tần suất f ∈ {3, 6, 12} tháng, kỳ = khối f tháng tính từ 01/01. Kỳ của điểm = tần suất nhỏ nhất trong các dòng
  không tự động. Ô lịch (điểm, kỳ P): thông số "phải có trong P" = thông số có kỳ riêng kết thúc cùng P; mỗi thông số
  đạt khi có đợt ghi sổ trong kỳ riêng của nó có giá trị/KPH. Trạng thái: na (mọi dòng tự động) · future · fail (có đợt
  Không đạt trong P) · done · over (hết kỳ, không có đợt) · miss (hết kỳ/đang kỳ, có đợt nhưng thiếu) · due (đang kỳ,
  chưa có đợt).
- Đánh giá dòng: KPH → Fail nếu có min, ngược lại Pass; value 0 = chưa nhập; detect_only → value > 0 Fail; ngoài
  [min, max] Fail. Đợt: điểm Inlet → Reference; ≥ 1 Fail → Fail; thiếu thông số → Incomplete; còn lại Pass.

## Tasks

| # | Task | Test (viết trước) | FR / BRU / AC |
| :- | :- | :- | :- |
| 1 | DocType `Wastewater Point`, `Wastewater Permit` + child `Wastewater Permit Parameter`; versioning `GPMT-<code>-V<n>`, khóa sau duyệt, `new_version`, `superseded_by`; validate bắt buộc/tần suất/min ≤ max/trùng dòng | `test_wastewater_permit.py` | FR-M15-08, 08.1; BRU-ENV-004; AC-095-01, 03 |
| 2 | Mẫu quy chuẩn `data/wastewater_standards.json` + `template(standard, column)` | `test_wastewater_permit.py` | FR-M15-08.2; AC-095-04 |
| 3 | DocType `Wastewater Monitoring` + child `Wastewater Result`; chọn GPMT hiệu lực, nạp thông số, đánh giá, bản chụp, kỳ, VIMCERTS, phiếu kết quả | `test_wastewater_monitoring.py` | FR-M15-10, 10.1, 13; BRU-ENV-004, 005; AC-095-07, 08, 09, 13 |
| 4 | Không đạt → cờ điểm, ToDo quan trắc lại, thông báo, `nc_status`; quan trắc lại; `open_nc`/`dismiss_nc` (R01) qua hook `tracecore_environment_nc` (ctx `source_doctype`) | `test_wastewater_monitoring.py` | FR-M15-11; BRU-ENV-003; AC-095-10, 11 |
| 5 | Lịch kỳ + `run_daily` nhắc đến hạn/quá hạn (`wastewater_due_days`) | `test_wastewater_schedule.py` | FR-M15-09, 09.1; BRU-ENV-006; AC-095-05, 06 |
| 6 | Báo cáo: Script Report `Wastewater Monitoring Summary`, Print Format, dòng tóm tắt FR-M15-07, chỉ số `ww_period_on_time`, badge | `test_wastewater_report.py` | FR-M15-12, 12.1; AC-095-12 |
| 7 | RPC `tracecore.v1.wastewater.*` (overview, schedule, parameters, template GET; new_permit_version, open_nc, dismiss_nc POST @idempotent) | `tests/test_wastewater_api.py` | FR-M15-13.1; AC-095-02, 14 |
| 8 | Màn SCR-67 `scr_67_nuoc_thai.js` (slug `nuoc-thai`), client script form Monitoring/Permit | `tests/test_ksnk_scr67.py` (JS qua node) | FR-M15-09, AC-095-02, 05 |
| 9 | Nối file dùng chung: hooks (doc_events Audit Log, scheduler, badges, indicators), notification EVENTS, error_codes UNMAPPED, name_columns, permission_matrix.csv + custom_docperm, Custom Field Supplier, IC Program Settings, vi.csv | test_permissions, test_permissions_v112, test_error_codes, test_notification, test_name_columns | FR-M15-13.1 |
| 10 | migrate site đang chạy (không patch), test từng module, diff-cover ≥ 70 %, pre-commit, bench build, As-Built | — | DoD |

## Không làm

Khí thải; nhật ký vận hành HTXLNT (W6); kết nối trạm tự động (W8); nộp báo cáo Sở/Bộ; merge develop, push, deploy
(chờ người dùng).
