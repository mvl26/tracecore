# FEAT-013 Trợ giúp theo trạm và gửi phản hồi/báo lỗi kèm ảnh màn hình — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps dùng checkbox (`- [ ]`).

**Goal:** Trên mọi màn trạm/PDA (Page `station`), nút **Trợ giúp** mở hướng dẫn 3–5 bước có ảnh của đúng trạm và cho
gửi phản hồi / báo lỗi phần mềm tới R10 kèm ảnh chụp màn hình (FR-M9-15, Could).

**Spec:** `docs/implementation-plan.md` §3 dòng FEAT-013 (`ui.station.help`; `v1.feedback.create`; W: Incident CAPA
(loại Phần mềm) hoặc Frappe `Issue`; phụ thuộc 002; S5); `docs/srs.md` FR-M9-15; `docs/ux-foundations.md` STN
"màn trợ giúp theo trạm (FR-M9-15, Could) mở từ rail"; `docs/design.md` §4.13 modal, §4.7 alert; architecture §8
(RPC `tracecore.v1.*`, ADR-003 idempotent), FR-M9-14 (4 trạng thái).

**Nhánh:** `feat/FEAT-013-station-help` cắt từ `develop` (ea1ffa5), bench riêng `~/tracecore-f006` (site test
`test_f006`); không đụng `~/tracecore-dev` (tab song song). Số amendment: **A-55**.

## Quyết định (Amendment A-55, người dùng duyệt D1–D3 ngày 30/10/2026; D4–D10 là chi tiết hiện thực theo D1–D3)

| # | Quyết định |
| --- | --- |
| D1 | Phản hồi lưu vào **ERPNext `Issue`** (không dùng Incident CAPA để lỗi phần mềm không lẫn vào số liệu NC/CAPA tái xử lý). Issue Type `TraceCore Software` (tạo idempotent ở `after_migrate`). Custom Field `Issue-tc_station` (Link Zone Station), `Issue-tc_employee` (Link Employee), `Issue-tc_feedback_kind` (Select Bug/Suggestion) qua fixture. |
| D2 | Nội dung trợ giúp là **Frappe `Help Article`** (DocType có sẵn), Help Category `TraceCore Stations`. Custom Field `Help Article-tc_station_key` (Select: T1…T8, T5b, LIN, General) gắn bài với bước trạm; trạm không có bước hoặc chưa có bài → bài `General`. R10 sửa chữ và tải ảnh thật trên Desk, không cần deploy. |
| D3 | Ảnh chụp màn hình bằng **html2canvas 1.4.1 (MIT)** để trong app (`public/js/lib/html2canvas.min.js` + LICENSE), nạp lười bằng `frappe.require` khi bấm Trợ giúp: không tải mạng ngoài, không dependency npm/CI mới. |
| D4 | Bước = mục `<li>` của danh sách đầu tiên trong `content`; ảnh = `<img>` đầu tiên trong mục. Hook `validate` của Help Article có `tc_station_key`: 3–5 bước, ảnh chỉ nhận file công khai `/files/…`. Server trả `steps: [{text, image}]` (chữ thuần), client render bằng `esc()`: không chèn HTML của bài. |
| D5 | `after_migrate` seed 11 bài (T1…T8, T5b, LIN, General) 3–4 bước chữ, chưa có ảnh; không ghi đè bài đã có. Chữ seed là chuỗi nguồn tiếng Anh qua `_()` (dịch ở `vi.csv`) theo ngôn ngữ hệ thống. |
| D6 | `tracecore.v1.help.get(station)` GET, `allow_guest` (trước khi quét thẻ cũng xem được), kiểm trạm tồn tại; chỉ bài `published`. Kiosk cache bài cuối theo trạm trong `localStorage` (try/catch) để xem khi offline. |
| D7 | `tracecore.v1.feedback.create(station, kind, description, screenshot, context, client_ts, token)` POST, `@station_session` (mọi vai trò TC R01–R10 + System Manager), `@idempotent`. Mô tả 10–2000 ký tự; ảnh data URL PNG/JPEG ≤ 1,5 MB (kiểm magic bytes) → `File` private gắn vào Issue; `context` chỉ giữ khóa whitelist (screen, step, online, last_error, app_version, user_agent, viewport), mỗi giá trị cắt 200 ký tự. Tối đa 10 phản hồi/nhân viên/giờ → từ chối `FEEDBACK_RATE_LIMIT`. |
| D8 | Thông báo R10 qua `core.notification.emit("SOFTWARE_FEEDBACK", issue)`: sự kiện mới, vai trò mặc định `TC R10`, in-app. |
| D9 | Chụp màn trước khi mở overlay; `onclone` che giá trị mọi `input[type=password]`, `[name=patient_code]`, `[data-tc-mask]` (mã bệnh nhân không rời trạm). Người dùng xem trước ảnh và bỏ tick được. Offline: xem hướng dẫn từ cache; nút gửi bị khóa kèm lý do (không xếp hàng phản hồi). Chưa quét thẻ: xem hướng dẫn được, gửi phản hồi yêu cầu quét thẻ. |
| D10 | Nút **Trợ giúp** (≥ 48 px, chữ) ở thanh tiêu đề trạm `.tc-title` (kiosk không có rail); overlay modal §4.13 đóng bằng Đóng/Esc, Tab vòng trong modal, đóng xong focus về ô quét. Đủ loading / empty / error / offline. |

Quyền: `Issue` cho TC R10 (read, write, report, print), `Help Article`/`Help Category` cho TC R10 (read, write, create) —
thêm vào ma trận `Custom DocPerm` idempotent.

## Tasks

- [ ] **Task 0 — Tài liệu:** A-55 vào Revision History `architecture.md`; ghi chú cột kỹ thuật FEAT-013 trong
  implementation-plan; plan này.
- [ ] **Task 1 — Dịch vụ `tracecore/ui/station_help.py`** (FR-M9-15; D2, D4, D5): `steps_from_html`, `validate_article`
  (hook), `article_for(station)`, `ensure_station_help()`; Custom Field fixture. Test: `tracecore/ui/tests/test_station_help.py`.
- [ ] **Task 2 — RPC `tracecore.v1.help.get`** (D6). Test: `tracecore/v1/tests/test_help_api.py`.
- [ ] **Task 3 — Dịch vụ `tracecore/ui/feedback.py` + RPC `tracecore.v1.feedback.create`** (D1, D7, D8; quyền Issue).
  Test: `tracecore/v1/tests/test_feedback_api.py`.
- [ ] **Task 4 — Client `public/js/station_help.js` + lib html2canvas + CSS** (D3, D9, D10), nối qua `page_js`,
  nút trong `station.html`. Test tĩnh: `tracecore/tests/test_station_help_assets.py`.
- [ ] **Task 5 — Hoàn thiện:** bản dịch `vi.csv`, `rtm.md` FR-M9-15, ghi chú hiện thực; full test + diff-cover ≥ 70 %,
  lint; merge `develop` mới nhất trước khi push.

## Acceptance (EARS, suy từ FR-M9-15)

- AC1 Khi người dùng bấm Trợ giúp trên một trạm, hệ thống phải hiển thị 3–5 bước có ảnh của bước trạm đó (hoặc bài
  General).
- AC2 Khi người dùng đã quét thẻ gửi phản hồi/báo lỗi, hệ thống phải tạo Issue loại `TraceCore Software` gắn trạm,
  nhân viên, ngữ cảnh và ảnh chụp màn hình private, và báo R10.
- AC3 Nếu ảnh không phải PNG/JPEG, quá 1,5 MB, mô tả ngoài 10–2000 ký tự hoặc vượt 10 lần/giờ, thì hệ thống phải từ
  chối kèm lý do và hành động.
- AC4 Khi trạm offline, hệ thống phải hiển thị hướng dẫn đã cache và khóa nút gửi kèm lý do.
- AC5 Ảnh chụp không chứa giá trị ô mã bệnh nhân / PIN.

## Ghi chú hiện thực

_(điền khi xong)_
