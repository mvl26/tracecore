"""Phản hồi khoa và NC Compliance từ phiếu giám sát (FEAT-060 AC-9, AC-10; FR-M12-08, FR-M12-09, BRU-AUD-005)."""

import frappe

from tracecore.compliance_audit import nc
from tracecore.compliance_audit.tests.factories import (
	R01,
	R08,
	R11,
	R12,
	answers,
	make_dept_user,
	make_observer,
	make_template,
)
from tracecore.core import notification
from tracecore.core.errors import BlockedError
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

ALL_PASS = dict.fromkeys(("PNC-01", "PNC-02", "PNC-03", "PNC-04", "PNC-05"), "Pass")


class FeedbackCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		notification.ensure_default_rules()
		self.dept_a = factories.make_department("Feedback Ward A")
		self.dept_b = factories.make_department("Feedback Ward B")
		self.template = make_template("T-FB")
		self.observer = make_observer(first_name="Feedback Observer")
		self.r08_a = make_dept_user("aud-fb-r08-a@example.com", R08, self.dept_a)
		self.r12_a = make_dept_user("aud-fb-r12-a@example.com", R12, self.dept_a)
		self.r12_b = make_dept_user("aud-fb-r12-b@example.com", R12, self.dept_b)
		self.r01 = factories.make_user("aud-fb-r01@example.com", [R01])
		self.r11 = factories.make_user("aud-fb-r11@example.com", [R11])

	def post(self, department=None, rows=None, notes=None):
		doc = frappe.get_doc(
			{
				"doctype": "Audit Session",
				"audit_template": self.template.name,
				"department": department or self.dept_a,
				"observer": self.observer,
				"answers": answers(**{**ALL_PASS, **(rows or {})}),
			}
		)
		for row in doc.answers:
			row.note = (notes or {}).get(row.item_code)
		doc.insert()
		doc.submit()
		return doc

	def received(self, event, user, ref=None):
		filters = {"event_code": event, "recipient": user, "channel": "In App"}
		if ref:
			filters["ref_name"] = ref
		return frappe.db.count("Notification Delivery", filters)


class TestFeedback(FeedbackCase):
	def test_feedback_to_head_and_network_member_of_department(self):
		doc = self.post(rows={"PNC-03": "Fail"}, notes={"PNC-03": "Wrong order"})
		self.assertEqual(self.received("AUDIT_FEEDBACK", self.r08_a, doc.name), 1)
		self.assertEqual(self.received("AUDIT_FEEDBACK", self.r12_a, doc.name), 1)
		self.assertEqual(self.received("AUDIT_FEEDBACK", self.r12_b, doc.name), 0)
		self.assertEqual(self.received("AUDIT_FEEDBACK", self.r01, doc.name), 0)
		message = frappe.db.get_value(
			"Notification Delivery", {"event_code": "AUDIT_FEEDBACK", "recipient": self.r12_a}, "message"
		)
		self.assertIn("87.5", message)
		self.assertIn("PNC-03", message)

	def test_department_without_network_member_also_alerts_r01(self):
		"""UC-45 A1: khoa không có mạng lưới viên → phản hồi trưởng khoa và cảnh báo R01."""
		dept_c = factories.make_department("Feedback Ward C")
		r08_c = make_dept_user("aud-fb-r08-c@example.com", R08, dept_c)
		doc = self.post(department=dept_c)
		self.assertEqual(self.received("AUDIT_FEEDBACK", r08_c, doc.name), 1)
		self.assertEqual(self.received("AUDIT_FEEDBACK", self.r01, doc.name), 1)

	@bru("BRU-AUD-005")
	def test_critical_fail_alerts_r01_and_r11(self):
		doc = self.post(rows={"PNC-04": "Fail"}, notes={"PNC-04": "Two-handed recap"})
		self.assertEqual(self.received("AUDIT_CRITICAL_FAIL", self.r01, doc.name), 1)
		self.assertEqual(self.received("AUDIT_CRITICAL_FAIL", self.r11, doc.name), 1)
		self.assertEqual(self.received("AUDIT_CRITICAL_FAIL", self.r12_a, doc.name), 0)
		ok = self.post()
		self.assertEqual(self.received("AUDIT_CRITICAL_FAIL", self.r01, ok.name), 0)


class TestComplianceNc(FeedbackCase):
	def setUp(self):
		super().setUp()
		self.failed = self.post(rows={"PNC-04": "Fail"}, notes={"PNC-04": "Two-handed recap"})

	@bru("BRU-AUD-005")
	def test_open_nc_creates_one_compliance_incident(self):
		frappe.set_user(self.r11)
		name = nc.open_nc(self.failed.name)
		frappe.set_user("Administrator")
		incident = frappe.get_doc("Incident CAPA", name)
		self.assertEqual(
			(incident.incident_category, incident.incident_type, incident.source_doctype, incident.source_name),
			("Compliance", "Compliance Nonconformity", "Audit Session", self.failed.name),
		)
		self.assertEqual(incident.department, self.dept_a)
		self.assertIn("PNC-04", incident.description)
		self.assertEqual(
			frappe.db.get_value("Audit Session", self.failed.name, ["nc_status", "nc_name"]), ("Opened", name)
		)
		frappe.set_user(self.r01)
		self.assertEqual(nc.open_nc(self.failed.name), name)
		self.assertEqual(frappe.db.count("Incident CAPA", {"source_name": self.failed.name}), 1)

	def test_only_r01_r11_open_or_dismiss(self):
		frappe.set_user(self.r12_a)
		with self.assertRaises(frappe.PermissionError):
			nc.open_nc(self.failed.name)
		with self.assertRaises(frappe.PermissionError):
			nc.dismiss_nc(self.failed.name, "x")

	def test_nc_only_when_suggested(self):
		ok = self.post()
		with self.assertRaises(BlockedError) as caught:
			nc.open_nc(ok.name)
		self.assertEqual(caught.exception.block.code, "AUDIT_NC_NOT_SUGGESTED")

	def test_dismiss_needs_reason_and_is_logged(self):
		with self.assertRaises(BlockedError) as caught:
			nc.dismiss_nc(self.failed.name, "  ")
		self.assertEqual(caught.exception.block.code, "REASON_REQUIRED")
		nc.dismiss_nc(self.failed.name, "Corrected on the spot and retrained")
		self.assertEqual(
			frappe.db.get_value("Audit Session", self.failed.name, ["nc_status", "nc_reason"]),
			("Dismissed", "Corrected on the spot and retrained"),
		)
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": "Audit Session", "ref_name": self.failed.name,
				"reason": "Corrected on the spot and retrained"})
		)
		with self.assertRaises(BlockedError):
			nc.open_nc(self.failed.name)

	def test_pending_lists_suggested_and_badge(self):
		self.post(department=self.dept_b, rows={"PNC-01": "Fail"}, notes={"PNC-01": "No hand rub"})
		pending = nc.pending()
		self.assertEqual({row["name"] for row in pending} >= {self.failed.name}, True)
		row = next(row for row in pending if row["name"] == self.failed.name)
		self.assertEqual(row["failed_items"][0]["item_code"], "PNC-04")
		self.assertGreaterEqual(nc.badges(self.r01)["tuan-thu"], 2)
		self.assertEqual(nc.badges(self.r12_a), {})
