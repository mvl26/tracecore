"""RPC tracecore.v1.notification.* — hộp thư SCR-42 trên Desk và chuông trạm/PDA bằng token phiên thẻ (FEAT-010)."""

import frappe

from tracecore.core import notification
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase
from tracecore.v1 import notification as api
from tracecore.v1.tests.station_fixtures import make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
EVENT = "API_TEST_EVENT"


def make_rule(users, urgency="Normal"):
	if frappe.db.exists("Notification Rule", EVENT):
		frappe.delete_doc("Notification Rule", EVENT, force=True, ignore_permissions=True)
	frappe.get_doc(
		{
			"doctype": "Notification Rule",
			"event_code": EVENT,
			"enabled": 1,
			"urgency": urgency,
			"ch_in_app": 1,
			"recipients": [{"recipient_type": "User", "user": user} for user in users],
		}
	).insert(ignore_permissions=True)


class TestNotificationApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.worker = make_user("ntf-api-r04@example.com", ["TC R04"])
		self.other = make_user("ntf-api-r03@example.com", ["TC R03"])
		self.addCleanup(frappe.set_user, "Administrator")

	def test_inbox_unread_and_mark_read_for_the_session_user(self):
		make_rule([self.worker, self.other])
		notification.emit(EVENT, subject="Hello")
		frappe.set_user(self.worker)
		box = api.inbox()
		self.assertEqual([row["subject"] for row in box["rows"]], ["Hello"])
		self.assertEqual((box["ok"], box["unread"]), (True, 1))
		self.assertEqual(api.unread_count()["unread"], 1)
		self.assertEqual(api.mark_read([box["rows"][0]["name"]])["changed"], 1)
		self.assertEqual(api.unread_count()["unread"], 0)
		frappe.set_user(self.other)
		self.assertEqual(api.unread_count()["unread"], 1)  # thông báo của người kia không đổi

	def test_mark_all_read_and_filters(self):
		make_rule([self.worker])
		notification.emit(EVENT, subject="One")
		notification.emit(EVENT, subject="Two")
		frappe.set_user(self.worker)
		self.assertEqual(len(api.inbox(event_code=EVENT)["rows"]), 2)
		self.assertEqual(api.mark_all_read(EVENT)["changed"], 2)
		self.assertEqual(api.inbox(only_unread=1, event_code=EVENT)["rows"], [])

	def test_guest_is_refused(self):
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			api.inbox()

	def test_station_summary_uses_the_card_session_user(self):
		make_rule([self.worker], urgency="Urgent")
		notification.emit(EVENT, subject="Recall now")
		session = make_station_session(self.worker)
		frappe.set_user("Guest")
		result = api.station_summary(session["token"])
		self.assertEqual((result["ok"], result["unread"]), (True, 1))
		self.assertEqual(result["urgent"]["subject"], "Recall now")
		self.assertEqual(api.station_summary("bad-token")["error"]["code"], "SESSION_INVALID")

	def test_station_inbox_and_mark_read_by_card_session(self):
		make_rule([self.worker])
		notification.emit(EVENT, subject="Scan me")
		session = make_station_session(self.worker)
		frappe.set_user("Guest")
		box = api.station_inbox(session["token"])
		self.assertEqual([row["subject"] for row in box["rows"]], ["Scan me"])
		result = api.station_mark_read(session["token"], [box["rows"][0]["name"]])
		self.assertEqual((result["ok"], result["changed"], result["unread"]), (True, 1, 0))
		self.assertEqual(api.station_inbox(session["token"])["rows"], [])
		self.assertEqual(api.station_inbox("bad-token")["error"]["code"], "SESSION_INVALID")
		self.assertEqual(api.station_mark_read("bad-token", [])["error"]["code"], "SESSION_INVALID")

	def test_station_mark_read_rejects_bad_names(self):
		session = make_station_session(self.worker)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.ValidationError):
			api.station_mark_read(session["token"], "not-a-list")

	def test_station_summary_has_no_urgent_when_everything_is_read(self):
		make_rule([self.worker], urgency="Urgent")
		notification.emit(EVENT, subject="Recall now")
		frappe.set_user(self.worker)
		api.mark_all_read(EVENT)
		frappe.set_user("Administrator")
		session = make_station_session(self.worker)
		frappe.set_user("Guest")
		result = api.station_summary(session["token"])
		self.assertEqual((result["unread"], result["urgent"]), (0, None))
