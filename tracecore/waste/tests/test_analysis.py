"""Báo cáo, sự cố và định mức chất thải (FEAT-050, UC-37, FR-M10-06, .1-.3, FR-M10-07, .1-.3, FR-M10-08, .1, .3, .4, BRU-WST-001, A-63)."""

import frappe
from frappe.utils import add_days, add_to_date, flt, now_datetime, today

from tracecore.core import notification
from tracecore.reprocessing import incidents
from tracecore.tests.factories import (
	make_department,
	make_employee,
	make_user,
	make_waste_location,
	make_waste_station,
	make_waste_type,
	make_waste_vendor,
)
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import waste as api
from tracecore.waste import analysis, collection, handover, storage
from tracecore.waste.report.waste_report.waste_report import execute

CARD = "WASTE-REPORT-CARD"


class AnalysisCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		notification.ensure_default_rules()
		self.station = make_waste_station()
		self.department = make_department("Khoa Bao Cao")
		self.giver = make_employee(card=CARD, department=self.department, first_name="Giao").name
		self.collector = make_employee(first_name="Thu gom").name
		self.waste = make_waste_type(waste_group="General").name
		self.r01 = make_user("waste-report-r01@example.com", ["TC R01"])
		self.r02 = make_user("waste-report-r02@example.com", ["TC R02"])

	def collect(self, kg=10, days_ago=0, **line):
		doc = collection.record(
			self.station,
			self.collector,
			CARD,
			[{"waste_type": self.waste, "qty": 1, "weight_kg": kg, "weight_source": "Scale", **line}],
		)
		if days_ago:
			moved = add_to_date(doc.collected_at, days=-days_ago)
			frappe.db.set_value("Waste Collection", doc.name, "collected_at", moved)
			frappe.db.set_value("Waste Container", {"collection": doc.name}, "collected_at", moved)
		return doc, frappe.get_all("Waste Container", filters={"collection": doc.name}, pluck="name")

	def deliveries(self, event, recipient=None):
		return frappe.db.count(
			"Notification Delivery",
			{"event_code": event, "recipient": recipient or self.r02, "channel": "In App"},
		)


class TestIncident(AnalysisCase):
	def test_waste_incident_gets_its_category(self):
		doc = incidents.create(
			{
				"incident_type": "Waste Spill",
				"severity": "Medium",
				"description": "Tràn",
				"department": self.department,
				"waste_type": self.waste,
			}
		)
		self.assertEqual(doc.incident_category, "Waste")

	def test_other_incident_has_no_category(self):
		doc = incidents.create(
			{"incident_type": "Other", "severity": "Low", "description": "x", "employee": self.giver}
		)
		self.assertFalse(doc.incident_category)

	def test_sharps_exposure_needs_employee_and_source(self):
		values = {"incident_type": "Sharps Exposure", "description": "Kim đâm", "department": self.department}
		with self.assertRaises(frappe.ValidationError):
			incidents.create({**values, "exposure_source": "Kim"})
		with self.assertRaises(frappe.ValidationError):
			incidents.create({**values, "employee": self.giver})

	def test_sharps_exposure_is_high_and_alerts_r01_at_once(self):
		doc = incidents.create(
			{
				"incident_type": "Sharps Exposure",
				"description": "Kim đâm",
				"employee": self.giver,
				"exposure_source": "Kim tiêm BN",
			}
		)
		self.assertEqual(doc.severity, "High")
		self.assertEqual(self.deliveries("INCIDENT", self.r01), 1)
		self.assertEqual(self.deliveries("INCIDENT", self.r02), 1)

	def test_auto_nc_fills_type_department_and_source(self):
		_doc, [bag] = self.collect(misclassified=1, misclass_note="Trộn")
		row = frappe.db.get_value(
			"Incident CAPA",
			{"source_name": bag},
			["incident_category", "waste_type", "department", "waste_source_doc"],
			as_dict=True,
		)
		self.assertEqual(
			(row.incident_category, row.waste_type, row.department, row.waste_source_doc),
			("Waste", self.waste, self.department, bag),
		)

	@bru("BRU-WST-001")
	def test_three_misclassifications_in_30_days_alert_r01_once(self):
		for _i in range(2):
			self.collect(misclassified=1, misclass_note="Trộn")
		analysis.run_daily()
		self.assertEqual(self.deliveries("WASTE_MISCLASS_REPEAT", self.r01), 0)
		self.collect(misclassified=1, misclass_note="Trộn")
		analysis.run_daily()
		analysis.run_daily()
		self.assertEqual(self.deliveries("WASTE_MISCLASS_REPEAT", self.r01), 1)

	def test_repeat_limit_is_configurable(self):
		frappe.db.set_single_value("TraceCore Settings", "waste_misclass_count", 1)
		self.collect(misclassified=1, misclass_note="Trộn")
		self.assertIn(self.department, analysis.repeat_departments())


class TestAnomaly(AnalysisCase):
	def test_above_average_alerts_r02_once_a_day(self):
		self.collect(kg=10, days_ago=1)
		self.collect(kg=10, days_ago=2)
		self.assertEqual(self.deliveries("WASTE_ANOMALY"), 0)
		self.collect(kg=20)
		self.collect(kg=1)
		self.assertEqual(self.deliveries("WASTE_ANOMALY"), 1)

	def test_small_change_and_no_history_do_not_alert(self):
		self.collect(kg=10)
		self.assertEqual(self.deliveries("WASTE_ANOMALY"), 0)
		self.collect(kg=10, days_ago=1)
		self.assertIsNone(analysis.anomaly(self.department, make_waste_type().name))

	def test_short_history_is_marked_not_enough_data(self):
		self.collect(kg=10, days_ago=1)
		self.collect(kg=30)
		result = analysis.anomaly(self.department, self.waste)
		self.assertTrue(result["insufficient"])
		self.assertTrue(result["over"])

	def test_threshold_is_configurable(self):
		frappe.db.set_single_value("TraceCore Settings", "waste_anomaly_percent", 500)
		self.collect(kg=10, days_ago=1)
		self.collect(kg=30)
		self.assertEqual(self.deliveries("WASTE_ANOMALY"), 0)


class TestQuota(AnalysisCase):
	def quota(self, **kwargs):
		doc = frappe.get_doc(
			{
				"doctype": "Waste Quota",
				"department": self.department,
				"waste_type": self.waste,
				"bags_per_day": 5,
				"kg_per_bed_day": 0.5,
				"effective_from": today(),
				**kwargs,
			}
		)
		doc.flags.ignore_links = True
		return doc.insert(ignore_permissions=True)

	def test_duplicate_effective_date_is_refused(self):
		self.quota()
		with self.assertRaises(frappe.ValidationError):
			self.quota()

	def test_report_uses_the_quota_in_force(self):
		self.quota(bags_per_day=3, effective_from=add_days(today(), -5))
		self.quota(bags_per_day=7)
		self.collect()
		row = analysis.report_rows(today(), today(), self.department)[0]
		self.assertEqual((row["bags_per_day"], row["quota_missing"]), (7, False))

	def test_missing_quota_only_warns(self):
		self.collect()
		self.assertTrue(analysis.report_rows(today(), today(), self.department)[0]["quota_missing"])


class TestReport(AnalysisCase):
	def handed(self):
		location = make_waste_location([self.waste])
		vendor = make_waste_vendor([self.waste], rate=1000)
		_doc, [bag] = self.collect(kg=10)
		storage.store(bag, location)
		draft = handover.create(self.station, self.collector, vendor)
		handover.add(draft.name, bag)
		handover.sign(
			draft.name,
			self.collector,
			weights=[{"waste_type": self.waste, "handover_kg": 9.8, "weight_source": "Scale"}],
			vendor_signer="A",
			vendor_signature="data:image/png;base64,AA==",
		)
		return handover.submit(draft.name), bag

	def test_row_has_weights_difference_cost_and_compliance(self):
		self.handed()
		row = analysis.report_rows(today(), today(), self.department, self.waste)[0]
		self.assertEqual((row["bags"], row["collected_kg"], row["handover_kg"]), (1, 10, 9.8))
		self.assertEqual(row["difference_kg"], -0.2)
		self.assertEqual(row["cost"], 9800)
		self.assertEqual(row["cost_per_kg"], 1000)
		self.assertEqual(row["compliance_percent"], 100)

	def test_overdue_bag_lowers_compliance(self):
		_doc, [bag] = self.collect()
		frappe.db.set_value("Waste Container", bag, "overdue_at", now_datetime())
		row = analysis.report_rows(today(), today(), self.department, self.waste)[0]
		self.assertEqual(row["compliance_percent"], 0)

	def test_no_data_gives_no_rows(self):
		self.assertEqual(analysis.report_rows(today(), today(), self.department, self.waste), [])

	def test_report_period_is_provisional_until_locked(self):
		self.collect()
		filters = {"from_date": today(), "to_date": today(), "department": self.department}
		columns, rows = execute(filters)
		self.assertIn("report_status", [column["fieldname"] for column in columns])
		self.assertEqual(rows[0]["report_status"], "Provisional")
		frappe.db.set_single_value("TraceCore Settings", "report_locked_until", today())
		self.addCleanup(frappe.db.set_single_value, "TraceCore Settings", "report_locked_until", None)
		self.assertEqual(execute(filters)[1][0]["report_status"], "Final")

	def test_incidents_of_the_period_are_listed(self):
		self.collect(misclassified=1, misclass_note="Trộn")
		rows = analysis.incidents(today(), today(), self.department)
		self.assertEqual([row.incident_type for row in rows], ["Waste Misclassification"])


class TestBlocks(AnalysisCase):
	def test_dashboard_block_counts(self):
		_doc, [bag] = self.collect(kg=4)
		self.collect(kg=1, days_ago=1)
		row = frappe.db.get_value("Waste Container", bag, ["collected_at", "storage_due"], as_dict=True)
		frappe.db.set_value("Waste Container", bag, "storage_due", add_to_date(row.collected_at, minutes=-1))
		block = analysis.dashboard()
		self.assertIn({"waste_type": self.waste, "kg": 4}, block["kg_today"])
		self.assertGreaterEqual(block["overdue"], 1)
		self.assertEqual(flt(block["pending_documents"]) >= 0, True)

	def test_ward_sees_only_its_own_department(self):
		self.collect(kg=4)
		self.collect(misclassified=1, misclass_note="Trộn")
		other_user = make_user("waste-report-r08b@example.com", ["TC R08"])
		make_employee(department=make_department("Khoa Khac"), first_name="Khac", user_id=other_user)
		frappe.set_user(other_user)
		self.addCleanup(frappe.set_user, "Administrator")
		self.assertEqual(api.my_department(today(), today())["rows"], [])

	def test_ward_summary_shows_kg_and_misclassifications(self):
		self.collect(kg=4)
		self.collect(misclassified=1, misclass_note="Trộn")
		result = analysis.department_summary(self.department, today(), today())
		self.assertEqual(result["rows"][0]["waste_type"], self.waste)
		self.assertEqual(len(result["misclassifications"]), 1)
