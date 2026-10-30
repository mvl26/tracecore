"""Trung tâm thông báo đa kênh (FEAT-010, FR-M9-10, FR-M9-10.1, UC-38, ADR-014).

``emit(event_code, doc, subject, …)`` là cửa duy nhất để báo một sự kiện nghiệp vụ. Người nhận = người gắn với sự
kiện do nơi gọi truyền (``users``) + người nhận bổ sung R10 cấu hình ở `Notification Rule` (vai trò, người dùng,
khoa của chứng từ). Mỗi người nhận có một dòng `Notification Delivery` trên mỗi kênh:

- In App: dòng hộp thư (Sent → Read), kèm một dòng chuông Desk (`Notification Log` của Frappe) và realtime;
- Email: `frappe.sendmail` (Email Queue); SMS: adapter `sms.send` (tắt sẵn). Lỗi thì giữ in-app, `retry_failed` thử lại
  tối đa 3 lần rồi báo R10;
- thông báo khẩn chưa đọc quá ``escalate_after_min`` (mặc định 15) phút → `escalate_unread` gửi email/SMS cho R01.
"""

import frappe
from frappe import _
from frappe.utils import add_to_date, cint, get_datetime, now_datetime

from tracecore.core import audit
from tracecore.core.notification import sms

IN_APP, EMAIL, SMS = "In App", "Email", "SMS"
MAX_ATTEMPTS = 3
DEFAULT_ESCALATE_MIN = 15
MISSING_RULE_EVENT = "NOTIFICATION_RULE_MISSING"
DELIVERY_FAILED_EVENT = "NOTIFICATION_DELIVERY_FAILED"
FALLBACK_ROLE = "TC R02"
ADMIN_ROLE = "TC R10"
ESCALATION_ROLE = "TC R01"
INBOX_LIMIT = 200

# Loại sự kiện có sẵn: mã → (mô tả, mức khẩn, kênh email, kênh PDA, vai trò mặc định). Vai trò mặc định chỉ dùng cho
# sự kiện hệ thống không có người gắn kèm; còn lại người nhận theo nghiệp vụ do nơi gọi truyền.
EVENTS = {
	"RECALL_ORDER": ("Recall order", "Urgent", 1, 1, ()),
	"INCIDENT": ("Incident or non-conformance", "Normal", 0, 0, ()),
	"INCIDENT_OVERDUE": ("Overdue CAPA action", "Normal", 0, 0, ()),
	"SET_DISPOSAL_REQUESTED": ("Set disposal requested", "Normal", 0, 0, ()),
	"SET_DISPOSAL_DECIDED": ("Set disposal decided", "Normal", 0, 0, ()),
	"LOANER_OVERDUE": ("Loaner set overdue", "Normal", 0, 0, ()),
	"PAR_OVERRIDE_REQUESTED": ("Par override requested", "Normal", 0, 0, ()),
	"PAR_OVERRIDE_REPORT": ("Monthly par override report", "Normal", 0, 0, ()),
	"EQUIPMENT_LOCKED": ("Equipment locked for expired inspection or calibration", "Normal", 0, 0, ()),
	"MAINTENANCE_DUE": ("Equipment maintenance due", "Normal", 0, 0, ()),
	# FEAT-036: R02 nhận thêm theo Rule; nhân viên liên quan do nơi gọi truyền
	"CERTIFICATE_EXPIRING": ("Certificate expiring", "Normal", 0, 0, (FALLBACK_ROLE,)),
	"CERTIFICATE_EXPIRED": ("Certificate expired", "Normal", 0, 0, (FALLBACK_ROLE,)),
	"HEALTH_RECORD_EXPIRING": ("Health check or vaccination expiring", "Normal", 0, 0, (FALLBACK_ROLE,)),
	# FEAT-037: năng lực trạm bị tạm dừng vì chứng chỉ bắt buộc hết hạn
	"COMPETENCY_SUSPENDED": ("Station competency suspended", "Normal", 0, 0, (FALLBACK_ROLE,)),
	# FEAT-042: tiêu hao tự động thiếu tồn / không có định mức / lỗi; người nhận mặc định là kế toán vật tư (R09)
	"CONSUMPTION_SHORT": ("Consumption exceeds stock", "Normal", 0, 0, ("TC R09",)),
	"CONSUMPTION_NO_NORM": ("Consumption norm missing", "Normal", 0, 0, ("TC R09",)),
	"CONSUMPTION_FAILED": ("Automatic consumption failed", "Urgent", 0, 0, ("TC R09",)),
	# FEAT-035: đồ vải chênh lệch thu - trả - hủy trong tháng > 5 % hoặc tồn khoa dưới tối thiểu
	"LINEN_VARIANCE": ("Linen reconciliation variance", "Normal", 0, 0, (FALLBACK_ROLE,)),
	# FEAT-043: tồn dưới tối thiểu và lô sắp hết hạn; email cho kế toán vật tư (R09)
	"STOCK_BELOW_MIN": ("Stock below minimum", "Normal", 1, 0, ("TC R09",)),
	"BATCH_EXPIRING": ("Batch expiring soon", "Normal", 1, 0, ("TC R09",)),
	MISSING_RULE_EVENT: ("Notification rule missing", "Normal", 0, 0, (ADMIN_ROLE,)),
	DELIVERY_FAILED_EVENT: ("Notification delivery failed", "Normal", 0, 0, (ADMIN_ROLE,)),
}
SYSTEM_EVENTS = (MISSING_RULE_EVENT, DELIVERY_FAILED_EVENT)


# --- cấu hình ----------------------------------------------------------------------------------------------------


def ensure_default_rules():
	"""Tạo Notification Rule còn thiếu cho mọi loại sự kiện có sẵn; không ghi đè chỉnh sửa của R10."""
	for code, (description, urgency, email, pda, roles) in EVENTS.items():
		if frappe.db.exists("Notification Rule", code):
			continue
		frappe.get_doc(
			{
				"doctype": "Notification Rule",
				"event_code": code,
				"description": description,
				"enabled": 1,
				"urgency": urgency,
				"escalate_after_min": DEFAULT_ESCALATE_MIN,
				"ch_in_app": 1,
				"ch_pda": pda,
				"ch_email": email,
				"ch_sms": 0,
				"recipients": [{"recipient_type": "Role", "role": role} for role in roles],
			}
		).insert(ignore_permissions=True)


def _rule(event_code):
	return frappe.db.get_value(
		"Notification Rule",
		event_code,
		["name", "enabled", "urgency", "ch_in_app", "ch_pda", "ch_email", "ch_sms", "escalate_after_min"],
		as_dict=True,
	)


def _active_users(users):
	users = [user for user in dict.fromkeys(users or ()) if user and user not in frappe.STANDARD_USERS]
	if not users:
		return []
	return frappe.get_all("User", filters={"name": ["in", users], "enabled": 1}, pluck="name")


def _users_with_role(role):
	holders = frappe.get_all("Has Role", filters={"role": role, "parenttype": "User"}, pluck="parent")
	return _active_users(holders)


def _department_users(department):
	if not department:
		return []
	return _active_users(
		frappe.get_all("Employee", filters={"department": department, "status": "Active"}, pluck="user_id")
	)


def _rule_recipients(rule_name, doc):
	users = []
	for row in frappe.get_all(
		"Notification Rule Recipient",
		filters={"parent": rule_name, "parenttype": "Notification Rule"},
		fields=["recipient_type", "role", "user"],
		order_by="idx asc",
	):
		if row.recipient_type == "Role" and row.role:
			users += _users_with_role(row.role)
		elif row.recipient_type == "User" and row.user:
			users.append(row.user)
		elif row.recipient_type == "Department of document" and doc is not None:
			users += _department_users(doc.get("department"))
	return users


def _link(doc, link):
	if link:
		return link
	if doc is not None and doc.get("doctype") and doc.get("name"):
		return "/app/" + frappe.scrub(doc.doctype).replace("_", "-") + "/" + str(doc.name)
	return None


# --- phát thông báo ----------------------------------------------------------------------------------------------


def emit(event_code, doc=None, subject=None, message=None, users=(), link=None):
	"""Báo một sự kiện nghiệp vụ; trả danh sách người nhận. Chưa có Rule thì gửi cho người gắn với sự kiện (hoặc R02) và
	cảnh báo R10 thiếu cấu hình (UC-38 E2); Rule tắt thì không gửi gì."""
	rule = _rule(event_code)
	if rule and not rule.enabled:
		return []
	recipients = list(users or ())
	if rule:
		recipients += _rule_recipients(rule.name, doc)
	recipients = _active_users(recipients)
	if not rule:
		if event_code in SYSTEM_EVENTS:
			recipients = recipients or _users_with_role(ADMIN_ROLE)
		else:
			recipients = recipients or _users_with_role(FALLBACK_ROLE)
			_warn_missing_rule(event_code)
	if not recipients:
		return []
	urgency = rule.urgency if rule else "Normal"
	channels = (
		{IN_APP: cint(rule.ch_in_app or rule.ch_pda), EMAIL: cint(rule.ch_email), SMS: cint(rule.ch_sms)}
		if rule
		else {IN_APP: 1, EMAIL: 0, SMS: 0}
	)
	values = {
		"event_code": event_code,
		"urgency": urgency,
		"subject": subject or event_code,
		"message": message,
		"ref_doctype": doc.get("doctype") if doc is not None else None,
		"ref_name": doc.get("name") if doc is not None else None,
		"link": _link(doc, link),
	}
	pda = cint(rule.ch_pda) if rule else 0
	for user in recipients:
		if channels[IN_APP]:
			_deliver_in_app(user, values, pda)
		if channels[EMAIL]:
			_deliver_external(user, EMAIL, values)
		if channels[SMS]:
			_deliver_external(user, SMS, values)
	return recipients


def _warn_missing_rule(event_code):
	marker = _("Notification rule missing for event {0}.").format(event_code)
	today = now_datetime().strftime("%Y-%m-%d")
	if frappe.db.exists(
		"Notification Delivery",
		{"event_code": MISSING_RULE_EVENT, "message": marker, "creation": [">=", today]},
	):
		return
	emit(
		MISSING_RULE_EVENT,
		subject=_("Notification rule missing: {0}").format(event_code),
		message=marker,
		link="/app/notification-rule/new",
	)


def _new_delivery(user, channel, values, **extra):
	return frappe.get_doc(
		{
			"doctype": "Notification Delivery",
			"recipient": user,
			"channel": channel,
			"sent_at": now_datetime(),
			**values,
			**extra,
		}
	).insert(ignore_permissions=True)


def _deliver_in_app(user, values, pda):
	bell = frappe.get_doc(
		{
			"doctype": "Notification Log",
			"for_user": user,
			"from_user": frappe.session.user,
			"type": "Alert",
			"subject": values["subject"],
			"email_content": values["message"],
			"document_type": values["ref_doctype"],
			"document_name": values["ref_name"],
			"link": values["link"],
		}
	).insert(ignore_permissions=True)
	delivery = _new_delivery(user, IN_APP, values, status="Sent", show_on_pda=pda, bell_log=bell.name)
	frappe.publish_realtime(
		"tc_notification",
		{"name": delivery.name, "subject": values["subject"], "urgency": values["urgency"]},
		user=user,
		after_commit=True,
	)
	return delivery


def _deliver_external(user, channel, values):
	if channel == SMS and not sms.is_enabled():
		return None
	delivery = _new_delivery(user, channel, values, status="Failed", attempts=0)
	_attempt(delivery)
	return delivery


def _attempt(delivery):
	"""Một lần gửi email/SMS cho dòng `delivery`; ghi kết quả và số lần thử."""
	attempts = cint(delivery.attempts) + 1
	try:
		if delivery.channel == EMAIL:
			email = frappe.db.get_value("User", delivery.recipient, "email")
			if not email:
				raise ValueError(_("The user has no email address."))
			frappe.sendmail(
				recipients=[email],
				subject=delivery.subject,
				message=delivery.message or delivery.subject,
				reference_doctype=delivery.ref_doctype,
				reference_name=delivery.ref_name,
			)
		else:
			phone = _phone(delivery.recipient)
			if not phone:
				delivery.db_set(
					{
						"status": "Failed",
						"attempts": MAX_ATTEMPTS,
						"last_error": _("The user has no mobile number."),
					}
				)
				return False
			sms.send(phone, (delivery.subject or "")[:300])
	except Exception as error:
		frappe.log_error(title=_("Notification delivery failed"), message=frappe.get_traceback())
		delivery.db_set({"status": "Failed", "attempts": attempts, "last_error": str(error)[:140]})
		return False
	delivery.db_set({"status": "Sent", "attempts": attempts, "last_error": None, "sent_at": now_datetime()})
	return True


def _phone(user):
	number = frappe.db.get_value("User", user, "mobile_no")
	return number or frappe.db.get_value("Employee", {"user_id": user}, "cell_number")


# --- thử lại và leo thang (scheduler) ------------------------------------------------------------------------------


def retry_failed():
	"""Scheduler 5 phút: gửi lại email/SMS lỗi, tối đa 3 lần; hết lần thì báo R10 (FR-M9-10.1)."""
	rows = frappe.get_all(
		"Notification Delivery",
		filters={"channel": ["in", [EMAIL, SMS]], "status": "Failed", "attempts": ["<", MAX_ATTEMPTS]},
		pluck="name",
		order_by="sent_at asc",
		limit_page_length=100,
	)
	for name in rows:
		delivery = frappe.get_doc("Notification Delivery", name)
		if (
			not _attempt(delivery)
			and cint(frappe.db.get_value("Notification Delivery", name, "attempts")) >= MAX_ATTEMPTS
		):
			emit(
				DELIVERY_FAILED_EVENT,
				subject=_("Could not send {0} to {1}: {2}").format(
					_(delivery.channel), delivery.recipient, delivery.subject
				),
				message=frappe.db.get_value("Notification Delivery", name, "last_error"),
				link=f"/app/notification-delivery/{name}",
			)


def escalate_unread():
	"""Scheduler 5 phút: thông báo khẩn chưa đọc quá hạn → nhắc người nhận và gửi email/SMS cho R01 (UC-38 E3)."""
	pending = frappe.get_all(
		"Notification Delivery",
		filters={"channel": IN_APP, "status": "Sent", "urgency": "Urgent", "escalated": 0},
		fields=[
			"name",
			"recipient",
			"event_code",
			"subject",
			"message",
			"ref_doctype",
			"ref_name",
			"link",
			"sent_at",
		],
	)
	minutes = {}
	r01_users = None
	for row in pending:
		if row.event_code not in minutes:
			minutes[row.event_code] = (
				cint(frappe.db.get_value("Notification Rule", row.event_code, "escalate_after_min"))
				or DEFAULT_ESCALATE_MIN
			)
		if get_datetime(row.sent_at) > add_to_date(now_datetime(), minutes=-minutes[row.event_code]):
			continue
		frappe.db.set_value("Notification Delivery", row.name, "escalated", 1, update_modified=False)
		frappe.publish_realtime(
			"tc_notification",
			{"name": row.name, "subject": row.subject, "urgency": "Urgent", "reminder": 1},
			user=row.recipient,
			after_commit=True,
		)
		if r01_users is None:
			r01_users = _users_with_role(ESCALATION_ROLE)
		values = {
			"event_code": row.event_code,
			"urgency": "Urgent",
			"subject": _("Unread urgent notification: {0}").format(row.subject),
			"message": row.message,
			"ref_doctype": row.ref_doctype,
			"ref_name": row.ref_name,
			"link": row.link,
		}
		for user in r01_users:
			_deliver_external(user, EMAIL, values)
			_deliver_external(user, SMS, values)


# --- hộp thư của người dùng (SCR-42) -------------------------------------------------------------------------------


def _own_filters(surface=None):
	filters = {"recipient": frappe.session.user, "channel": IN_APP}
	if surface == "pda":
		filters["show_on_pda"] = 1
	return filters


def unread_count(surface=None):
	return frappe.db.count("Notification Delivery", {**_own_filters(surface), "status": "Sent"})


def inbox(only_unread=0, event_code=None, surface=None, start=0, limit=50):
	"""Thông báo của người dùng hiện tại, mới nhất trước. Trả ``{"rows", "unread", "has_more"}``."""
	filters = _own_filters(surface)
	if cint(only_unread):
		filters["status"] = "Sent"
	if event_code:
		filters["event_code"] = event_code
	limit = max(1, min(cint(limit) or 50, INBOX_LIMIT))
	rows = frappe.get_all(
		"Notification Delivery",
		filters=filters,
		fields=[
			"name",
			"recipient",
			"event_code",
			"urgency",
			"subject",
			"message",
			"ref_doctype",
			"ref_name",
			"link",
			"status",
			"sent_at",
			"read_at",
			"escalated",
		],
		order_by="sent_at desc, name desc",
		start=cint(start),
		limit_page_length=limit + 1,
	)
	has_more = len(rows) > limit
	rows = rows[:limit]
	labels = dict(
		frappe.get_all(
			"Notification Rule",
			filters={"name": ["in", list({row.event_code for row in rows})]} if rows else {"name": ""},
			fields=["name", "description"],
			as_list=True,
		)
	)
	for row in rows:
		row["event_label"] = labels.get(row.event_code) or row.event_code
	return {"rows": rows, "unread": unread_count(surface), "has_more": has_more}


def mark_read(names):
	"""Đánh dấu Đã đọc các thông báo của chính người dùng (kèm chuông Desk và Audit Log). Trả số dòng đã đổi."""
	changed = 0
	for name in dict.fromkeys(names or ()):
		row = frappe.db.get_value(
			"Notification Delivery",
			{"name": name, **_own_filters(), "status": "Sent"},
			["name", "bell_log"],
			as_dict=True,
		)
		if not row:
			continue
		frappe.db.set_value(
			"Notification Delivery",
			row.name,
			{"status": "Read", "read_at": now_datetime()},
			update_modified=False,
		)
		if row.bell_log and frappe.db.exists("Notification Log", row.bell_log):
			frappe.db.set_value("Notification Log", row.bell_log, "read", 1, update_modified=False)
		audit.log("Update", "Notification Delivery", row.name, new={"event": "Notification Read"})
		changed += 1
	return changed


def mark_all_read(event_code=None):
	filters = {**_own_filters(), "status": "Sent"}
	if event_code:
		filters["event_code"] = event_code
	return mark_read(frappe.get_all("Notification Delivery", filters=filters, pluck="name"))


# --- quyền ---------------------------------------------------------------------------------------------------------


def _sees_everything(user):
	return user == "Administrator" or bool(set(frappe.get_roles(user)) & {ADMIN_ROLE, "System Manager"})


def delivery_query_conditions(user=None):
	user = user or frappe.session.user
	if _sees_everything(user):
		return ""
	return f"`tabNotification Delivery`.`recipient` = {frappe.db.escape(user)}"


def delivery_has_permission(doc, user=None, permission_type=None):
	user = user or frappe.session.user
	return _sees_everything(user) or doc.recipient == user
