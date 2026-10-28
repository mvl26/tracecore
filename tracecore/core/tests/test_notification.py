"""core.notification (FEAT-010, FR-M9-10, FR-M9-10.1, UC-38): người nhận theo cấu hình, in-app, email/SMS, thử lại, leo thang."""

from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime

from tracecore.core import notification
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
EVENT = "TEST_EVENT"


def make_rule(event=EVENT, recipients=(), urgency="Normal", **fields):
	if frappe.db.exists("Notification Rule", event):
		frappe.delete_doc("Notification Rule", event, force=True, ignore_permissions=True)
	doc = frappe.get_doc(
		{
			"doctype": "Notification Rule",
			"event_code": event,
			"description": "Test rule",
			"enabled": 1,
			"urgency": urgency,
			"ch_in_app": 1,
			"recipients": [
				dict(zip(("recipient_type", "role", "user"), row, strict=False)) for row in recipients
			],
			**fields,
		}
	)
	return doc.insert(ignore_permissions=True)


USERS = ["ntf-r01@example.com", "ntf-r02@example.com", "ntf-r10@example.com", "ntf-r04@example.com"]


def deliveries(user=None, channel=None, **filters):
	# site test còn người dùng khác giữ cùng vai trò (demo, fixture): chỉ xét người của bài test này
	filters["recipient"] = user or ["in", USERS]
	if channel:
		filters["channel"] = channel
	return frappe.get_all(
		"Notification Delivery",
		filters={"event_code": EVENT, **filters},
		fields=["name", "recipient", "channel", "status", "attempts", "show_on_pda", "escalated"],
	)


class TestNotification(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.r01 = make_user("ntf-r01@example.com", ["TC R01"])
		self.r02 = make_user("ntf-r02@example.com", ["TC R02"])
		self.r10 = make_user("ntf-r10@example.com", ["TC R10"])
		self.r04 = make_user("ntf-r04@example.com", ["TC R04"])
		frappe.db.set_value("User", self.r01, "mobile_no", "0900000001")
		self.addCleanup(frappe.set_user, "Administrator")

	# --- người nhận theo cấu hình ---
	def test_rule_roles_and_users_become_recipients_without_duplicates(self):
		make_rule(recipients=[("Role", "TC R01", None), ("User", None, self.r04), ("Role", "TC R01", None)])
		notification.emit(EVENT, subject="Subject A", users=[self.r04])
		self.assertEqual(
			sorted(d.recipient for d in deliveries(channel="In App")), sorted([self.r01, self.r04])
		)

	def test_caller_users_are_always_included(self):
		make_rule(recipients=[("Role", "TC R02", None)])
		notification.emit(EVENT, subject="S", users=[self.r04])
		self.assertEqual({d.recipient for d in deliveries(channel="In App")}, {self.r02, self.r04})

	def test_department_recipients_follow_the_document(self):
		make_rule(recipients=[("Department of document", None, None)])
		department = frappe.get_doc(
			{"doctype": "Department", "department_name": "NTF Khoa", "company": "_Test Company"}
		)
		department.insert(ignore_permissions=True, ignore_mandatory=True)
		frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Khoa NV",
				"gender": "Male",
				"date_of_birth": "1990-01-01",
				"date_of_joining": frappe.utils.today(),
				"company": "_Test Company",
				"status": "Active",
				"department": department.name,
				"user_id": self.r04,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
		doc = frappe._dict(doctype="User", name=self.r02, department=department.name)
		notification.emit(EVENT, doc, subject="S")
		self.assertEqual([d.recipient for d in deliveries(channel="In App")], [self.r04])

	def test_unconfigured_event_goes_to_r02_and_warns_r10(self):
		if frappe.db.exists("Notification Rule", EVENT):
			frappe.delete_doc("Notification Rule", EVENT, force=True, ignore_permissions=True)
		notification.emit(EVENT, subject="No rule yet")
		self.assertIn(self.r02, [d.recipient for d in deliveries(channel="In App")])
		warned = frappe.get_all(
			"Notification Delivery",
			filters={"event_code": notification.MISSING_RULE_EVENT, "recipient": self.r10},
		)
		self.assertTrue(warned)

	def test_disabled_rule_sends_nothing(self):
		rule = make_rule(recipients=[("Role", "TC R01", None)])
		rule.db_set("enabled", 0)
		notification.emit(EVENT, subject="S", users=[self.r04])
		self.assertEqual(deliveries(), [])

	def test_emit_is_not_sent_to_disabled_users(self):
		make_rule(recipients=[("Role", "TC R01", None)])
		frappe.db.set_value("User", self.r01, "enabled", 0)
		notification.emit(EVENT, subject="S")
		self.assertEqual(deliveries(), [])

	# --- in-app, đã đọc ---
	def test_in_app_creates_delivery_and_frappe_bell_entry(self):
		make_rule(recipients=[("User", None, self.r04)], ch_pda=1)
		doc = frappe._dict(doctype="User", name=self.r02)
		notification.emit(EVENT, doc, subject="Hello", message="Body")
		[row] = deliveries(self.r04, "In App")
		self.assertEqual((row.status, row.show_on_pda), ("Sent", 1))
		bell = frappe.get_all(
			"Notification Log",
			filters={"for_user": self.r04, "subject": "Hello"},
			fields=["document_type", "document_name"],
		)
		self.assertEqual([(b.document_type, b.document_name) for b in bell], [("User", self.r02)])
		self.assertEqual(
			frappe.db.get_value("Notification Delivery", row.name, "link"), f"/app/user/{self.r02}"
		)

	def test_mark_read_updates_status_bell_and_audit(self):
		make_rule(recipients=[("User", None, self.r04)])
		notification.emit(EVENT, subject="Read me")
		[row] = deliveries(self.r04, "In App")
		frappe.set_user(self.r04)
		self.assertEqual(notification.unread_count(), 1)
		notification.mark_read([row.name])
		after = frappe.db.get_value("Notification Delivery", row.name, ["status", "read_at"], as_dict=True)
		self.assertEqual(after.status, "Read")
		self.assertTrue(after.read_at)
		self.assertEqual(notification.unread_count(), 0)
		self.assertEqual(
			frappe.db.get_value("Notification Log", {"for_user": self.r04, "subject": "Read me"}, "read"), 1
		)
		frappe.set_user("Administrator")
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": "Notification Delivery", "ref_name": row.name, "user": self.r04}
			)
		)

	def test_user_cannot_mark_someone_elses_notification(self):
		make_rule(recipients=[("User", None, self.r04)])
		notification.emit(EVENT, subject="Private")
		[row] = deliveries(self.r04, "In App")
		frappe.set_user(self.r02)
		notification.mark_read([row.name])
		self.assertEqual(frappe.db.get_value("Notification Delivery", row.name, "status"), "Sent")

	def test_inbox_lists_only_own_and_filters_unread(self):
		make_rule(recipients=[("User", None, self.r04), ("User", None, self.r02)])
		notification.emit(EVENT, subject="One")
		notification.emit(EVENT, subject="Two")
		frappe.set_user(self.r04)
		everything = notification.inbox()
		self.assertEqual({row["recipient"] for row in everything["rows"]}, {self.r04})
		notification.mark_read([everything["rows"][0]["name"]])
		unread = notification.inbox(only_unread=1)
		self.assertEqual(len(unread["rows"]), 1)
		self.assertEqual(notification.mark_all_read(), 1)
		self.assertEqual(notification.unread_count(), 0)

	def test_pda_surface_shows_only_pda_enabled(self):
		make_rule(recipients=[("User", None, self.r04)])
		notification.emit(EVENT, subject="Desk only")
		make_rule(recipients=[("User", None, self.r04)], ch_pda=1)
		notification.emit(EVENT, subject="Also PDA")
		frappe.set_user(self.r04)
		self.assertEqual([r["subject"] for r in notification.inbox(surface="pda")["rows"]], ["Also PDA"])

	# --- email, SMS, thử lại ---
	def test_email_is_queued_and_marked_sent(self):
		make_rule(recipients=[("User", None, self.r04)], ch_email=1)
		with patch("tracecore.core.notification.frappe.sendmail") as send:
			notification.emit(EVENT, subject="Mail me", message="Body")
		send.assert_called_once()
		self.assertEqual(send.call_args.kwargs["recipients"], [self.r04])
		self.assertEqual([d.status for d in deliveries(self.r04, "Email")], ["Sent"])

	def test_failed_email_keeps_in_app_and_retries_three_times_then_alerts_r10(self):
		make_rule(recipients=[("User", None, self.r04)], ch_email=1)
		with patch("tracecore.core.notification.frappe.sendmail", side_effect=RuntimeError("smtp down")):
			notification.emit(EVENT, subject="Mail me")
			self.assertEqual([d.status for d in deliveries(self.r04, "In App")], ["Sent"])
			[mail] = deliveries(self.r04, "Email")
			self.assertEqual((mail.status, mail.attempts), ("Failed", 1))
			notification.retry_failed()
			notification.retry_failed()
		[mail] = deliveries(self.r04, "Email")
		self.assertEqual((mail.status, mail.attempts), ("Failed", 3))
		self.assertTrue(
			frappe.get_all(
				"Notification Delivery",
				filters={"event_code": notification.DELIVERY_FAILED_EVENT, "recipient": self.r10},
			)
		)
		with patch("tracecore.core.notification.frappe.sendmail") as send:
			notification.retry_failed()  # đã hết 3 lần: không gửi nữa
		send.assert_not_called()

	def test_retry_succeeds_after_gateway_recovers(self):
		make_rule(recipients=[("User", None, self.r04)], ch_email=1)
		with patch("tracecore.core.notification.frappe.sendmail", side_effect=RuntimeError("smtp down")):
			notification.emit(EVENT, subject="Mail me")
		with patch("tracecore.core.notification.frappe.sendmail"):
			notification.retry_failed()
		[mail] = deliveries(self.r04, "Email")
		self.assertEqual((mail.status, mail.attempts), ("Sent", 2))

	def test_sms_disabled_by_default_is_skipped_quietly(self):
		make_rule(recipients=[("User", None, self.r01)], ch_sms=1)
		with patch("tracecore.core.notification.sms.send") as send:
			notification.emit(EVENT, subject="S")
		send.assert_not_called()
		self.assertEqual(deliveries(self.r01, "SMS"), [])

	def test_sms_sent_through_adapter_when_enabled(self):
		make_rule(recipients=[("User", None, self.r01)], ch_sms=1)
		with (
			patch("tracecore.core.notification.sms.is_enabled", return_value=True),
			patch("tracecore.core.notification.sms.send") as send,
		):
			notification.emit(EVENT, subject="Urgent text")
		send.assert_called_once_with("0900000001", "Urgent text")
		self.assertEqual([d.status for d in deliveries(self.r01, "SMS")], ["Sent"])

	def test_sms_adapter_posts_to_the_configured_gateway(self):
		url = "https://sms.example.test/send"
		settings = frappe._dict(
			enable_sms=1,
			sms_gateway_url=url,
			sms_sender="CSSD",
			get_password=lambda *args, **kwargs: "secret",
		)
		with (
			patch("tracecore.core.notification.sms.frappe.get_cached_doc", return_value=settings),
			patch("tracecore.core.notification.sms.requests.post") as post,
		):
			self.assertTrue(notification.sms.is_enabled())
			notification.sms.send("0900000001", "Hello")
			settings.enable_sms = 0
			self.assertFalse(notification.sms.is_enabled())
		post.assert_called_once()
		self.assertEqual(post.call_args.args[0], url)
		self.assertEqual(
			post.call_args.kwargs["json"], {"to": "0900000001", "text": "Hello", "sender": "CSSD"}
		)
		self.assertEqual(post.call_args.kwargs["headers"], {"Authorization": "Bearer secret"})
		post.return_value.raise_for_status.assert_called_once()

	def test_sms_without_phone_number_is_marked_failed_with_reason(self):
		make_rule(recipients=[("User", None, self.r04)], ch_sms=1)
		with patch("tracecore.core.notification.sms.is_enabled", return_value=True):
			notification.emit(EVENT, subject="S")
		[row] = deliveries(self.r04, "SMS")
		self.assertEqual(row.status, "Failed")

	# --- leo thang ---
	def test_urgent_unread_after_15_minutes_escalates_once_to_r01_by_email(self):
		make_rule(recipients=[("User", None, self.r04)], urgency="Urgent")
		notification.emit(EVENT, subject="Recall now")
		[row] = deliveries(self.r04, "In App")
		frappe.db.set_value(
			"Notification Delivery", row.name, "sent_at", add_to_date(now_datetime(), minutes=-16)
		)
		with patch("tracecore.core.notification.frappe.sendmail") as send:
			notification.escalate_unread()
			first = send.call_count
			notification.escalate_unread()  # lần hai không nhắc lại
			self.assertEqual(send.call_count, first)
		sent_to = {address for call in send.call_args_list for address in call.kwargs["recipients"]}
		self.assertIn(self.r01, sent_to)
		self.assertNotIn(self.r04, sent_to)
		self.assertEqual(frappe.db.get_value("Notification Delivery", row.name, "escalated"), 1)

	def test_fresh_read_or_normal_notifications_do_not_escalate(self):
		make_rule(recipients=[("User", None, self.r04)], urgency="Urgent")
		notification.emit(EVENT, subject="Fresh")
		make_rule(recipients=[("User", None, self.r02)], urgency="Normal")
		notification.emit(EVENT, subject="Normal")
		with patch("tracecore.core.notification.frappe.sendmail") as send:
			notification.escalate_unread()
		send.assert_not_called()

	def test_escalation_honours_rule_minutes_and_skips_read(self):
		make_rule(recipients=[("User", None, self.r04)], urgency="Urgent", escalate_after_min=30)
		notification.emit(EVENT, subject="Slow")
		[row] = deliveries(self.r04, "In App")
		frappe.db.set_value(
			"Notification Delivery", row.name, "sent_at", add_to_date(now_datetime(), minutes=-20)
		)
		with patch("tracecore.core.notification.frappe.sendmail") as send:
			notification.escalate_unread()
		send.assert_not_called()
		frappe.db.set_value(
			"Notification Delivery",
			row.name,
			{"sent_at": add_to_date(now_datetime(), minutes=-40), "status": "Read"},
		)
		with patch("tracecore.core.notification.frappe.sendmail") as send:
			notification.escalate_unread()
		send.assert_not_called()

	# --- mặc định khi cài ---
	def test_default_rules_exist_for_every_catalog_event(self):
		notification.ensure_default_rules()
		for event in notification.EVENTS:
			self.assertTrue(frappe.db.exists("Notification Rule", event), event)
		self.assertEqual(frappe.db.get_value("Notification Rule", "RECALL_ORDER", "urgency"), "Urgent")

	def test_ensure_default_rules_does_not_overwrite_r10_changes(self):
		notification.ensure_default_rules()
		frappe.db.set_value("Notification Rule", "RECALL_ORDER", "enabled", 0)
		notification.ensure_default_rules()
		self.assertEqual(frappe.db.get_value("Notification Rule", "RECALL_ORDER", "enabled"), 0)
