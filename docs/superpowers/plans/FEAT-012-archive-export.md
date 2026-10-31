# FEAT-012 Xuất hồ sơ tiệt khuẩn lưu trữ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** R01/R10 xuất gói hồ sơ tiệt khuẩn (mẻ, chỉ thị, dữ liệu máy, cấp phát, sử dụng, audit) theo kỳ, theo một mẻ hoặc một lệnh thu hồi thành một file ZIP (PDF + CSV + manifest), có SHA-256 và dấu thời gian, chạy nền, lưu được ≥ 10 năm độc lập với hệ thống.

**Architecture:** DocType `Archive Export` (M9, module `Admin Reports`, mã `XH-.YYYY.-.#####`, không ghi sổ: chỉ dịch vụ đổi trạng thái, không sửa tham số sau khi tạo, không xóa). Tạo phiếu (Desk hoặc RPC `tracecore.v1.archive.export`) → `after_insert` xếp job RQ `long` → `admin_reports.archive.build` gom bản ghi liên quan, sinh CSV + PDF (dùng lại `sterilization_log.render_pdf` của FEAT-007), `manifest.json` (SHA-256 từng file), nén ZIP, lưu File riêng tư đính vào phiếu, ghi SHA-256 của ZIP lên phiếu, báo người xuất. `verify` tính lại SHA-256 của file đã lưu để đối chiếu.

**Tech Stack:** Frappe v15, `IsolatedTestCase`, RQ, `zipfile`, `hashlib`, `csv`.

**Spec:** `docs/implementation-plan.md` FEAT-012; `docs/srs.md` FR-M9-12, OTH-RET-001, NFR-COMP-01, NFR-SEC-02, NFR-PORT-02; `docs/use-cases.md` UC-39 bước 6, A3, E3, E4; `docs/architecture.md` §5.3 (Archive Export), Retention; Amendment **A-58**.

## Quyết định (Amendment A-58; người dùng chốt Q1–Q4 ngày 30/10/2026, chủ đầu tư chưa xác nhận)
| # | Quyết định |
| :- | :- |
| Q1 | Một file ZIP: `sterilization_log.pdf` (+ `ksnk_summary.pdf` khi xuất theo kỳ), CSV UTF-8 có BOM (mở thẳng bằng Excel): `loads.csv`, `indicators.csv`, `machine_data.csv`, `load_packs.csv`, `issues.csv`, `usage.csv`, `audit.csv` theo phạm vi chọn, và `manifest.json` (SHA-256, số byte, số dòng từng file). SHA-256 của ZIP lưu trên phiếu. |
| Q2 | Mã bệnh nhân trong `usage.csv` mặc định là mã đã che. Chỉ TC R01 tick "Xuất mã bệnh nhân đầy đủ" kèm lý do mới xuất mã rõ; ghi Audit Log `View Patient Code` kèm lý do (UC-39 E3, NFR-SEC-02). |
| Q3 | Dấu thời gian = giờ máy chủ (ISO 8601 có offset) + người xuất + SHA-256, ghi trong manifest và trên phiếu (không sửa được). Không dùng TSA RFC 3161. |
| Q4 | Phạm vi: theo kỳ (mẻ bắt đầu trong kỳ, trừ Đang chạy), theo một mẻ, hoặc theo một lệnh thu hồi (mẻ của lệnh + mẻ của các gói trong lệnh) (UC-39 A3). |
| D1 | Bản ghi liên quan: mẻ → gói trong mẻ → phiếu cấp phát đã ghi sổ có gói đó → bản ghi sử dụng của gói; audit = Audit Log của các bản ghi trên (và lệnh thu hồi). |
| D2 | Quyền: TC R01, TC R10 tạo và đọc; vai trò khác không thấy. Kỳ chưa khóa (FEAT-007 `report_locked_until`) → cờ `provisional`, PDF có dấu TẠM. |
| D3 | Lỗi khi sinh gói → trạng thái Failed + thông báo; tạo phiếu mới để xuất lại. |

## Tasks
- [x] **T1 DocType + quyền** — `Archive Export`, ma trận `DT-ARCHIVE`. FR-M9-12, D2, Q2.
- [x] **T2 Gom bản ghi theo phạm vi** — `archive.related`. Q4, D1.
- [x] **T3 Sinh gói** — CSV, PDF, manifest, ZIP, File, SHA-256, thông báo; `verify`. Q1, Q3, D3.
- [x] **T4 RPC + Desk** — `tracecore.v1.archive.export/verify`, form JS, link trang chủ.
- [x] **T5 Bản dịch, tài liệu** — `vi.csv` (chèn giữa file), A-58, rtm.

## Acceptance criteria (EARS)
- AC1 Khi R01/R10 tạo phiếu xuất theo kỳ, hệ thống sinh nền một ZIP gồm PDF, CSV từng phạm vi và manifest SHA-256, rồi báo người xuất.
- AC2 Khi chọn một mẻ hoặc một lệnh thu hồi, gói chỉ chứa bản ghi liên quan tới mẻ/lệnh đó.
- AC3 Nếu không phải R01 có lý do, thì mã bệnh nhân trong gói luôn ở dạng che.
- AC4 Khi người dùng kiểm checksum, hệ thống so SHA-256 của file đang lưu với giá trị trên phiếu.
- AC5 Phiếu xuất không sửa tham số, không xóa được sau khi tạo.

## Phối hợp nhánh song song
FEAT-013 (A-56) sửa `hooks.py`, `errors.py`, `core/notification`, cuối `vi.csv`: FEAT-012 không sửa ba file đầu (audit ghi trong controller), bản dịch chèn giữa `vi.csv`.
