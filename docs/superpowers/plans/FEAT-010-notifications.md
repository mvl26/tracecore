# FEAT-010 Trung tâm thông báo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Mọi sự kiện nghiệp vụ cần báo người khác đi qua một cửa `core.notification.emit`: R10 cấu hình thêm người nhận, kênh và mức khẩn; người nhận có hộp thư (đã gửi / đã đọc) trên Desk, trạm và PDA; email/SMS lỗi được gửi lại; thông báo khẩn chưa đọc quá 15 phút được leo thang cho R01.

**Architecture:** Package `tracecore/core/notification/` (`__init__.py` lõi, `sms.py` adapter) + DocType `Notification Rule`, `Notification Rule Recipient`, `Notification Delivery` (module TraceCore) + RPC `tracecore.v1.notification.*` + Page `notifications` (SCR-42) + chuông trên Page `station`.

**Tech Stack:** Frappe v15, `frappe.sendmail` (Email Queue), `Notification Log` chuẩn (chuông Desk), scheduler cron `*/5`, `IsolatedTestCase`.

**Spec:** `docs/srs.md` FR-M9-10, FR-M9-10.1; `docs/use-cases.md` UC-38; `docs/architecture.md` §5.3, ADR-014; Amendment A-42.

## Global Constraints
- Chỉ `core.notification` ghi `Notification Delivery`; người dùng chỉ đọc thông báo của mình (R10 và System Manager đọc tất cả); không xóa.
- RPC chỉ đọc không kéo dài phiên trạm; chuỗi qua `_()`/`__()` có bản dịch, từ chung dùng context để không đè bản dịch của Frappe; UI chỉ token `--tc-*`; trạng thái luôn có chữ.
- Không làm: gateway SMS thật (chưa có), push Firebase (OQ-16), thông báo realtime trên trạm (hỏi lại 60 giây).

## Quyết định (Amendment A-42, tạm — chờ chủ đầu tư)
| # | Quyết định | AC |
| :- | :- | :- |
| N1 | `Notification Delivery` thay `Notification Log` (trùng DocType Frappe); một dòng cho mỗi người nhận × kênh. | FR-M9-10 |
| N2 | Người nhận = người gắn với sự kiện (nơi gọi truyền) + người Rule cấu hình thêm; Rule tắt thì không gửi; chưa có Rule thì gửi cho người gắn với sự kiện hoặc R02 và cảnh báo R10. | UC-38 A2, E2 |
| N3 | Email qua `frappe.sendmail`; SMS qua adapter, tắt sẵn. Lỗi: giữ in-app, thử lại 3 lần mỗi 5 phút rồi báo R10. | FR-M9-10.1, UC-38 E1 |
| N4 | Urgent chưa đọc quá `escalate_after_min` (mặc định 15) → email/SMS cho R01, một lần. | UC-38 E3 |
| N5 | Đánh dấu đã đọc ghi Audit Log và đồng bộ chuông Desk. | UC-38 bước 6 |
| N6 | 5 chỗ báo tạm sang `emit`: thanh lý bộ (2), bộ mượn quá hạn, ghi đè cơ số (2), sự cố (2), thu hồi (2). | — |

## Tasks
- [x] **T1 Test + lõi** `core/tests/test_notification.py` (22 test): người nhận, in-app, đã đọc, email, SMS, thử lại, leo thang, Rule mặc định.
- [x] **T2 DocType** Notification Rule / Rule Recipient / Delivery; `TraceCore Settings` thêm cờ và cấu hình SMS; quyền theo người nhận.
- [x] **T3 Scheduler** `*/5`: `retry_failed`, `escalate_unread`; `ensure_default_rules` ở `after_install` và `after_migrate`.
- [x] **T4 Chuyển 5 chỗ báo tạm**; chạy lại test cũ của disposal, loaner, override, incidents, recall.
- [x] **T5 RPC** `v1/tests/test_notification_api.py` (8 test): Desk và trạm/PDA.
- [x] **T6 UI** Page `notifications` (SCR-42), chuông + banner khẩn + bảng chưa đọc trên Page `station`, link ở trang chủ TraceCore.

## Review Focus
- Rule không bớt được người nhận theo nghiệp vụ (chỉ bổ sung); người dùng đọc được thông báo của người khác qua danh sách hay `mark_read`.
- Chuông trạm hỏi 60 giây một lần bằng token, không kéo dài phiên; mất mạng giữ số cũ.
- Email/SMS lỗi không làm mất thông báo in-app; không gửi lại quá 3 lần.
