"""Sự cố nghi ngộ độc thực phẩm (FEAT-073; FR-M17-04, FR-M17-04.1; BRU-FS-002; UC-56 bước 4, E2, A2; A-151 Q1, Q2)."""

import frappe
from frappe.utils import add_days, today

from tracecore.core.errors import BlockedError
from tracecore.food_safety import events
from tracecore.food_safety.tests import factories as ff
from tracecore.tests.utils import IsolatedTestCase, bru


class TestFoodborneEvent(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.r01 = ff.make_user("attp-ev-r01@example.com", [ff.R01])
		self.r11 = ff.make_user("attp-ev-r11@example.com", [ff.R11])
		ff.set_threshold(3)

	def _deliveries(self, event, user):
		return frappe.get_all(
			"Notification Delivery", filters={"event_code": event, "recipient": user}, pluck="ref_name"
		)

	def test_posting_notifies_r01_r11_and_suggests_nc(self):
		doc = ff.make_event(affected=2)
		for user in (self.r01, self.r11):
			self.assertIn(doc.name, self._deliveries(events.REPORTED_EVENT, user))
		self.assertEqual(frappe.db.get_value(events.DOCTYPE, doc.name, "nc_status"), events.SUGGESTED)
		self.assertFalse(frappe.db.get_value(events.DOCTYPE, doc.name, "outbreak_status"))
		self.assertEqual(frappe.db.get_value(events.DOCTYPE, doc.name, "threshold_applied"), 3)

	@bru("BRU-FS-002")
	def test_at_or_above_threshold_suggests_outbreak_investigation(self):
		doc = ff.make_event(affected=3)
		self.assertEqual(frappe.db.get_value(events.DOCTYPE, doc.name, "outbreak_status"), events.SUGGESTED)

	def test_threshold_not_set_only_nc_and_reminds_r01(self):
		ff.set_threshold(0)
		doc = ff.make_event(affected=40)
		values = frappe.db.get_value(
			events.DOCTYPE, doc.name, ["nc_status", "outbreak_status", "threshold_applied"], as_dict=True
		)
		self.assertEqual(
			(values.nc_status, values.outbreak_status, values.threshold_applied), ("Suggested", None, 0)
		)
		self.assertIn(doc.name, self._deliveries(events.THRESHOLD_EVENT, self.r01))
		self.assertNotIn(doc.name, self._deliveries(events.THRESHOLD_EVENT, self.r11))

	def test_validation_people_and_date(self):
		with self.assertRaises(BlockedError) as ctx:
			ff.make_event(affected=0, submit=False)
		self.assertEqual(ctx.exception.block.code, "FOODBORNE_COUNT_INVALID")
		with self.assertRaises(BlockedError):
			ff.make_event(event_date=add_days(today(), 1), submit=False)

	def test_open_nc_creates_food_safety_incident_once(self):
		doc = ff.make_event(affected=2)
		frappe.set_user(self.r11)
		incident = events.open_nc(doc.name)
		self.assertEqual(events.open_nc(doc.name), incident)
		values = frappe.db.get_value(
			"Incident CAPA",
			incident,
			["incident_type", "incident_category", "source_doctype", "source_name", "department"],
			as_dict=True,
		)
		self.assertEqual(values.incident_category, "Food Safety")
		self.assertEqual(values.incident_type, "Food Safety Nonconformity")
		self.assertEqual((values.source_doctype, values.source_name), (events.DOCTYPE, doc.name))
		self.assertEqual(values.department, doc.department)
		stored = frappe.db.get_value(events.DOCTYPE, doc.name, ["nc_status", "incident_capa"], as_dict=True)
		self.assertEqual((stored.nc_status, stored.incident_capa), (events.OPENED, incident))

	def test_dismiss_needs_reason_and_only_r01_r11_decide(self):
		doc = ff.make_event(affected=5)
		r12 = ff.make_user("attp-ev-r12@example.com", [ff.R12])
		frappe.set_user(r12)
		with self.assertRaises(frappe.PermissionError):
			events.open_nc(doc.name)
		frappe.set_user(self.r01)
		with self.assertRaises(BlockedError) as ctx:
			events.dismiss_nc(doc.name, " ")
		self.assertEqual(ctx.exception.block.code, "REASON_REQUIRED")
		events.dismiss_nc(doc.name, "Đã xác định không do thực phẩm")
		events.dismiss_outbreak(doc.name, "Ca rải rác, không cùng nguồn")
		values = frappe.db.get_value(
			events.DOCTYPE, doc.name, ["nc_status", "outbreak_status", "outbreak_reason"], as_dict=True
		)
		self.assertEqual((values.nc_status, values.outbreak_status), (events.DISMISSED, events.DISMISSED))
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": events.DOCTYPE, "ref_name": doc.name, "action": "Update"}
			)
		)
		with self.assertRaises(BlockedError):
			events.dismiss_outbreak(doc.name, "lần hai")

	def test_outbreak_opened_from_event_is_linked_back(self):
		doc = ff.make_event(affected=6)
		prefill = events.outbreak_prefill(doc.name)
		self.assertEqual((prefill["source_doctype"], prefill["source_name"]), (events.DOCTYPE, doc.name))
		self.assertEqual(prefill["start_date"], doc.event_date)
		outbreak = frappe._dict(
			doctype="Outbreak Investigation",
			name="OD-2026-001",
			source_doctype=events.DOCTYPE,
			source_name=doc.name,
		)
		events.on_outbreak_saved(outbreak)
		values = frappe.db.get_value(
			events.DOCTYPE, doc.name, ["outbreak_status", "outbreak_investigation"], as_dict=True
		)
		self.assertEqual(
			(values.outbreak_status, values.outbreak_investigation), (events.OPENED, "OD-2026-001")
		)
		events.on_outbreak_saved(frappe._dict(doctype="Outbreak Investigation", name="OD-2026-002"))
		self.assertEqual(
			frappe.db.get_value(events.DOCTYPE, doc.name, "outbreak_investigation"), "OD-2026-001"
		)

	def test_badges_count_events_waiting_for_decision(self):
		ff.make_event(affected=6)
		frappe.set_user(self.r11)
		self.assertGreaterEqual(events.pending_count(), 1)
