"""Việc hằng ngày M16: nhắc mốc theo dõi, thuốc dự phòng, xóa định danh (FEAT-071; FR-M16-04, 04.1, 08, 08.1;
NFR-PRIV-02; A-137 e, h, l)."""

import frappe
from frappe.utils import add_days, add_months, now_datetime, today

from tracecore.core import notification
from tracecore.occupational_safety import exposure, jobs, pep_stock
from tracecore.occupational_safety.tests import os_fixtures as fx
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

DOCTYPE = "Occupational Exposure"


class TestFollowupReminders(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		fx.clear_templates()
		fx.thresholds()
		self.user = factories.make_user("os-job-staff@example.com", roles=["TC R08"])
		self.r11 = factories.make_user("os-job-r11@example.com", roles=["TC R11"])
		self.employee = fx.employee("PN Job Staff", factories.make_department("PN Job Khoa"), user=self.user)
		fx.template(steps=(("Step 1", 0), ("Step 2", 10)))
		doc = exposure.create_report(
			{"employee": self.employee, "exposure_type": fx.SHARPS, "occurred_at": now_datetime()}
		)
		self.doc = exposure.record_handling(doc.name, first_aid_done=1, prophylaxis="Not Indicated")
		exposure.mark_followup_done(self.doc.name, self.doc.followups[0].name, today())

	def deliveries(self, user):
		return frappe.db.count(
			"Notification Delivery",
			{"event_code": "EXPOSURE_FOLLOWUP_DUE", "recipient": user, "ref_name": self.doc.name},
		)

	def test_reminds_three_days_before_once(self):
		self.assertEqual(jobs.remind_followups(add_days(today(), 6)), 0)  # còn 4 ngày
		self.assertEqual(jobs.remind_followups(add_days(today(), 7)), 1)  # còn 3 ngày
		self.assertEqual(jobs.remind_followups(add_days(today(), 8)), 0)
		self.assertEqual(self.deliveries(self.user), 1)
		self.assertEqual(self.deliveries(self.r11), 1)

	def test_overdue_reminded_daily_at_most_seven_times(self):
		"""FR-M16-04.1."""
		sent = sum(jobs.remind_followups(add_days(today(), 10 + day)) for day in range(1, 11))
		self.assertEqual(sent, 7)
		self.assertEqual(jobs.remind_followups(add_days(today(), 11)), 0)  # cùng ngày không nhắc lại

	def test_done_step_not_reminded(self):
		exposure.mark_followup_done(self.doc.name, self.doc.followups[1].name, today())
		self.assertEqual(jobs.remind_followups(add_days(today(), 12)), 0)


class TestRetention(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		fx.thresholds()
		self.employee = fx.employee("PN Ret Staff", factories.make_department("PN Ret Khoa"))
		self.doc = exposure.create_report(
			{
				"employee": self.employee,
				"exposure_type": fx.SPLASH,
				"occurred_at": add_months(now_datetime(), -30),
				"source_known": "Yes",
				"source_patient_code": "BN-RET-0001",
			}
		)
		exposure.cancel(self.doc.name, "Test record")

	def test_empty_retention_changes_nothing(self):
		frappe.db.set_single_value("IC Program Settings", "exposure_retention_months", None)
		self.assertEqual(jobs.deidentify_expired(), 0)
		self.assertEqual(frappe.db.get_value(DOCTYPE, self.doc.name, "employee"), self.employee)

	def test_expired_records_lose_identifiers_keep_totals(self):
		frappe.db.set_single_value("IC Program Settings", "exposure_retention_months", 24)
		self.assertEqual(jobs.deidentify_expired(), 1)
		row = frappe.db.get_value(
			DOCTYPE,
			self.doc.name,
			[
				"employee",
				"employee_name",
				"source_patient_code_hash",
				"source_patient_code_masked",
				"department",
				"exposure_type",
				"deidentified",
			],
			as_dict=True,
		)
		self.assertFalse(row.employee or row.employee_name or row.source_patient_code_hash)
		self.assertFalse(row.source_patient_code_masked)
		self.assertTrue(row.department and row.exposure_type and row.deidentified)
		self.assertFalse(
			frappe.db.exists(
				"__Auth", {"doctype": DOCTYPE, "name": self.doc.name, "fieldname": "source_patient_code"}
			)
		)
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_doctype": DOCTYPE, "ref_name": self.doc.name}))
		self.assertEqual(jobs.deidentify_expired(), 0)


class TestPepStock(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		frappe.db.sql("update `tabItem` set tc_is_pep_drug = 0")
		self.r01 = factories.make_user("os-pep-r01@example.com", roles=["TC R01"])
		self.warehouse = factories.ensure_stock_masters()["warehouse"]
		self.item_code = f"PN-PEP-{frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": self.item_code,
				"item_name": self.item_code,
				"item_group": factories.ITEM_GROUP_ROOT,
				"stock_uom": factories.ITEM_UOM,
				"is_stock_item": 1,
				"has_batch_no": 1,
				"has_expiry_date": 1,
				"tc_is_pep_drug": 1,
				"reorder_levels": [
					{
						"warehouse": self.warehouse,
						"warehouse_reorder_level": 10,
						"warehouse_reorder_qty": 10,
						"material_request_type": "Purchase",
					}
				],
			}
		).insert(ignore_permissions=True)

	def test_no_flagged_item_no_alert(self):
		frappe.db.set_value("Item", self.item_code, "tc_is_pep_drug", 0)
		self.assertEqual(pep_stock.check(), [])

	def test_below_minimum_and_expiring_batch_alert_r01(self):
		"""FR-M16-08: tồn (Bin, không có = 0) dưới mức tối thiểu và lô còn tồn hết hạn trong 30 ngày → báo R01."""
		batch = frappe.get_doc(
			{
				"doctype": "Batch",
				"batch_id": f"PN-B-{frappe.generate_hash(length=6)}",
				"item": self.item_code,
				"expiry_date": add_days(today(), 20),
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Batch", batch.name, "batch_qty", 5)
		far = frappe.get_doc(
			{
				"doctype": "Batch",
				"batch_id": f"PN-B-{frappe.generate_hash(length=6)}",
				"item": self.item_code,
				"expiry_date": add_days(today(), 200),
			}
		).insert(ignore_permissions=True)
		frappe.db.set_value("Batch", far.name, "batch_qty", 5)
		alerts = pep_stock.check()
		kinds = {(a["kind"], a.get("warehouse") or a.get("batch")) for a in alerts}
		self.assertIn(("below_min", self.warehouse), kinds)
		self.assertIn(("expiring", batch.name), kinds)
		self.assertNotIn(("expiring", far.name), kinds)
		self.assertTrue(
			frappe.db.exists(
				"Notification Delivery", {"event_code": "PEP_STOCK_ALERT", "recipient": self.r01}
			)
		)

	def test_custom_field_exists(self):
		self.assertEqual(frappe.get_meta("Item").get_field("tc_is_pep_drug").fieldtype, "Check")


class TestRunDaily(IsolatedTestCase):
	def test_run_daily_hook_registered_and_runs(self):
		self.assertIn(
			"tracecore.occupational_safety.jobs.run_daily", frappe.get_hooks("scheduler_events")["daily"]
		)
		jobs.run_daily()
