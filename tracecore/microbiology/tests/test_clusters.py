"""Cảnh báo cụm ca (FEAT-069; FR-M13-13, .1; UC-50 bước 1-4, A1, A3, E1; A-150 Q2)."""

from unittest.mock import patch

import frappe
from frappe.utils import getdate

from tracecore.core.errors import BlockedError
from tracecore.microbiology import clusters
from tracecore.microbiology.tests import outbreak_fixtures as of
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase

DAY = getdate("2026-11-03")
VAP = "Ventilator-associated Pneumonia"


class ClusterCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.db.delete(clusters.ALERT_DOCTYPE)
		frappe.db.delete(clusters.RULE_DOCTYPE)
		self.icu = of.make_clinical("CC Hồi sức tích cực")
		self.ward = of.make_clinical("CC Khoa Nội")
		for department in (self.icu, self.ward):
			frappe.db.delete("HAI Case", {"department": department})
			frappe.db.delete("Microbiology Isolate", {"department": department})

	def run_day(self, day=DAY):
		with patch("tracecore.core.notification.emit") as emit:
			alerts = clusters.run_daily(day)
		return alerts, emit.call_args_list

	def three_vap(self, department=None):
		department = department or self.icu
		return [
			of.make_case(department, "2026-10-22", "BN-0000002031"),
			of.make_case(department, "2026-10-24", "BN-0000005517"),
			of.make_case(department, "2026-10-30", "BN-0000007730"),
		]


class TestNoThreshold(ClusterCase):
	def test_no_rule_no_alert(self):
		self.three_vap()
		alerts, calls = self.run_day()
		self.assertEqual((alerts, calls), ([], []))
		self.assertFalse(clusters.configured())

	def test_disabled_rule_no_alert(self):
		of.make_rule(infection_site=VAP, disabled=1)
		self.three_vap()
		self.assertEqual(self.run_day()[0], [])


class TestHaiThreshold(ClusterCase):
	def test_three_confirmed_cases_in_window_raise_urgent_alert(self):
		rule = of.make_rule(infection_site=VAP, window_days=14, min_cases=3)
		cases = self.three_vap()
		of.make_case(self.ward, "2026-10-25", "BN-0000000001")  # khoa khác — đếm riêng
		alerts, calls = self.run_day()
		self.assertEqual(len(alerts), 1)
		alert = frappe.get_doc(clusters.ALERT_DOCTYPE, alerts[0])
		self.assertEqual((alert.rule, alert.department, alert.case_count), (rule.name, self.icu, 3))
		self.assertEqual(set(alert.case_refs.split()), set(cases))
		self.assertEqual(alert.status, clusters.NEW)
		self.assertEqual(calls[0].args[0], clusters.EVENT)
		self.assertIn(f"alert={alert.name}", calls[0].kwargs["link"])

	def test_suspected_excluded_and_out_of_window_not_counted(self):
		of.make_rule(infection_site=VAP, window_days=14, min_cases=3)
		of.make_case(self.icu, "2026-10-24", "BN-1", status="Suspected")
		of.make_case(self.icu, "2026-10-25", "BN-2", status="Excluded")
		of.make_case(self.icu, "2026-10-01", "BN-3")
		of.make_case(self.icu, "2026-10-30", "BN-4")
		of.make_case(self.icu, "2026-10-31", "BN-5")
		of.make_case(self.icu, "2026-10-31", "BN-6", site="Other")
		self.assertEqual(self.run_day()[0], [])

	def test_rule_for_one_department_ignores_others(self):
		of.make_rule(infection_site=VAP, department=self.ward)
		self.three_vap(self.icu)
		self.assertEqual(self.run_day()[0], [])

	def test_no_repeat_until_new_case(self):
		of.make_rule(infection_site=VAP)
		self.three_vap()
		first, _calls = self.run_day()
		again, calls = self.run_day(getdate("2026-11-04"))
		self.assertEqual((again, calls), ([], []))
		clusters.dismiss(first[0], "Đã xem: các ca không liên quan dịch tễ")
		self.assertEqual(self.run_day(getdate("2026-11-04"))[0], [])
		of.make_case(self.icu, "2026-11-04", "BN-0000009999")
		fresh, calls = self.run_day(getdate("2026-11-04"))
		self.assertEqual(len(fresh), 1)
		self.assertNotEqual(fresh[0], first[0])
		self.assertEqual(frappe.db.get_value(clusters.ALERT_DOCTYPE, fresh[0], "case_count"), 4)

	def test_new_case_on_open_alert_updates_and_renotifies(self):
		of.make_rule(infection_site=VAP)
		self.three_vap()
		first, _calls = self.run_day()
		of.make_case(self.icu, "2026-11-04", "BN-0000009999")
		again, calls = self.run_day(getdate("2026-11-04"))
		self.assertEqual(again, first)
		self.assertEqual(len(calls), 1)
		self.assertEqual(frappe.db.get_value(clusters.ALERT_DOCTYPE, first[0], "case_count"), 4)


class TestIsolateThreshold(ClusterCase):
	def test_same_organism_counts_patients_once(self):
		of.make_rule(
			title="CRE",
			source="Microbiology Isolate",
			organism="kpn",
			mdro_only=1,
			window_days=14,
			min_cases=2,
		)
		of.make_isolate(self.icu, "CC-1", "BN-0000000011", "2026-10-28", mdro=1, flags="CRE")
		of.make_isolate(self.icu, "CC-2", "BN-0000000011", "2026-10-29", mdro=1, flags="CRE")
		of.make_isolate(self.icu, "CC-3", "BN-0000000022", "2026-10-30", mdro=0)
		self.assertEqual(self.run_day()[0], [])
		third = of.make_isolate(self.icu, "CC-4", "BN-0000000033", "2026-11-01", mdro=1, flags="CRE")
		alerts, _calls = self.run_day()
		self.assertEqual(len(alerts), 1)
		alert = frappe.get_doc(clusters.ALERT_DOCTYPE, alerts[0])
		self.assertEqual(alert.case_count, 2)
		self.assertIn(third, alert.case_refs.split())
		self.assertIn("Klebsiella", alert.key_label)


class TestRuleAndDismiss(ClusterCase):
	def test_rule_validation(self):
		with self.assertRaises(frappe.ValidationError):
			of.make_rule(infection_site=VAP, window_days=0)
		with self.assertRaises(frappe.ValidationError):
			of.make_rule(infection_site=VAP, min_cases=1)
		with self.assertRaises(frappe.ValidationError):
			of.make_rule(source="Microbiology Isolate")  # thiếu loài và không chọn chỉ đa kháng

	def test_dismiss_needs_reason_and_ic_role(self):
		of.make_rule(infection_site=VAP)
		self.three_vap()
		alert = self.run_day()[0][0]
		r13 = make_user("cc-r13@example.com", ["TC R13"])
		r11 = make_user("cc-r11@example.com", ["TC R11"])
		with self.assertRaises(BlockedError) as caught:
			clusters.dismiss(alert, " ")
		self.assertEqual(caught.exception.block.code, "CLUSTER_REASON_REQUIRED")
		frappe.set_user(r13)
		with self.assertRaises(frappe.PermissionError):
			clusters.dismiss(alert, "lý do")
		frappe.set_user(r11)
		doc = clusters.dismiss(alert, "Đã xem xét: khác chủng")
		self.assertEqual((doc.status, doc.reviewed_by), (clusters.DISMISSED, "cc-r11@example.com"))
		with self.assertRaises(BlockedError):
			clusters.dismiss(alert, "lần hai")

	def test_open_alerts_and_badges(self):
		of.make_rule(infection_site=VAP)
		self.three_vap()
		self.run_day()
		rows = clusters.open_alerts()
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["case_count"], 3)
		r11 = make_user("cc-r11b@example.com", ["TC R11"])
		self.assertGreaterEqual(clusters.badges(r11).get("o-dich", 0), 1)
		self.assertEqual(clusters.badges(make_user("cc-r13b@example.com", ["TC R13"])), {})

	def test_alert_cannot_be_deleted_or_created_by_hand(self):
		rule = of.make_rule(infection_site=VAP)
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc({"doctype": clusters.ALERT_DOCTYPE, "rule": rule.name}).insert(
				ignore_permissions=True
			)
