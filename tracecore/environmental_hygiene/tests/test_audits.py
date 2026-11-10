"""Phiếu vệ sinh môi trường và hạ tầng gắn vùng qua engine M12 (FEAT-070; FR-M15-02, .1, FR-M15-06, .1; UC-54 bước 3,
7, E4; A-148 e)."""

from unittest.mock import patch

import frappe

from tracecore.core.errors import BlockedError
from tracecore.environmental_hygiene import audits, zones
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.factories import make_supplier
from tracecore.tests.utils import IsolatedTestCase


class AuditCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.ward = ef.make_department("PH Khoa Gây mê")
		self.other = ef.make_department("PH Khoa Nội")
		for department in (self.ward, self.other):
			frappe.db.delete(zones.DOCTYPE, {"department": department})
		self.high = ef.make_level("T Rất cao", minimum=4, high=1)
		self.low = ef.make_level("T Thấp", minimum=1, high=0, order=10)
		self.vendor = make_supplier("PH Công ty vệ sinh B")
		self.or_zone = ef.make_zone(self.ward, area="Phòng mổ PH", level=self.high).name
		self.hall = ef.make_zone(
			self.ward, area="Hành lang PH", level=self.low, party="Outsourced Vendor", supplier=self.vendor
		).name
		self.template = ef.make_env_template().name


class TestZoneOnAudit(AuditCase):
	def test_cleaning_audit_of_department_with_zones_needs_zone(self):
		with self.assertRaises(BlockedError) as raised:
			ef.make_session(self.template, self.ward, None)
		self.assertEqual(raised.exception.block.code, "ENV_ZONE_REQUIRED")
		# khoa chưa khai báo vùng: phiếu vẫn ghi được như trước FEAT-070
		ef.make_session(self.template, self.other, None)

	def test_zone_must_belong_to_audit_department(self):
		with self.assertRaises(BlockedError) as raised:
			ef.make_session(self.template, self.other, self.or_zone)
		self.assertEqual(raised.exception.block.code, "ENV_ZONE_MISMATCH")

	def test_zone_is_dropped_from_other_audit_types(self):
		from tracecore.compliance_audit.tests import factories as af

		session = frappe.get_doc(
			{
				"doctype": "Audit Session",
				"audit_template": af.make_template("T-PNC-PH").name,
				"department": self.ward,
				"environment_zone": self.or_zone,
				"observer": af.make_observer(),
				"answers": af.answers(**{"PNC-01": "Pass"}),
			}
		).insert(ignore_permissions=True)
		self.assertFalse(session.environment_zone)

	def test_infrastructure_audit_fills_next_due_from_interval(self):
		template = ef.make_infra_template(interval=180).name
		session = ef.make_session(template, self.ward, self.or_zone, audit_date="2026-05-05")
		self.assertEqual(str(session.next_due), "2026-11-01")
		own = ef.make_session(
			template, self.ward, self.or_zone, audit_date="2026-05-06", next_due="2026-06-30"
		)
		self.assertEqual(str(own.next_due), "2026-06-30")

	def test_infrastructure_audit_without_interval_needs_next_due(self):
		template = ef.make_infra_template("T-INFRA-NUOC", "Water Supply", interval=0).name
		with self.assertRaises(BlockedError) as raised:
			ef.make_session(template, self.ward, self.or_zone)
		self.assertEqual(raised.exception.block.code, "ENV_NEXT_DUE_REQUIRED")


class TestPassRates(AuditCase):
	def test_pass_rate_by_risk_level_department_and_responsible_party(self):
		"""FR-M15-02, .1: tỷ lệ đạt theo mức nguy cơ, khoa, bên chịu trách nhiệm; tách từng đơn vị thuê ngoài."""
		ef.make_session(self.template, self.ward, self.or_zone, audit_date="2026-10-02")
		ef.make_session(self.template, self.ward, self.or_zone, passed=False, audit_date="2026-10-03")
		ef.make_session(self.template, self.ward, self.hall, audit_date="2026-10-04")
		rates = audits.pass_rates("2026-10-01", "2026-10-31")
		by_risk = {row["key"]: row for row in rates["by_risk"]}
		self.assertEqual((by_risk[self.high]["passed"], by_risk[self.high]["total"]), (1, 2))
		self.assertEqual(by_risk[self.high]["pct"], 50.0)
		by_party = {row["key"]: row for row in rates["by_party"]}
		self.assertEqual(by_party[self.vendor]["total"], 1)
		self.assertEqual(by_party["Department"]["total"], 2)
		by_dept = {row["key"]: row for row in rates["by_department"]}
		self.assertEqual(by_dept[self.ward]["total"], 3)
		self.assertEqual(audits.high_risk_pass("2026-10-01", "2026-10-31"), (1, 2))


class TestInfrastructure(AuditCase):
	def test_systems_status_and_on_time_rate(self):
		"""FR-M15-06, .1: hệ thống quá hạn không tính đúng hạn."""
		vent = ef.make_infra_template("T-INFRA-VENT", "Ventilation", interval=30).name
		water = ef.make_infra_template("T-INFRA-NUOC", "Water Supply", interval=30).name
		ef.make_session(vent, self.ward, self.or_zone, audit_date="2026-10-01", next_due="2026-10-31")
		ef.make_session(vent, self.ward, self.hall, audit_date="2026-10-01", next_due="2026-11-20")
		ef.make_session(water, self.ward, self.or_zone, audit_date="2026-10-01", next_due="2026-11-15")
		systems = {(row["template_code"], row["zone"]): row for row in audits.infra_systems("2026-11-10")}
		self.assertEqual(systems[("T-INFRA-VENT", self.or_zone)]["status"], "Overdue")
		self.assertEqual(systems[("T-INFRA-NUOC", self.or_zone)]["status"], "Due Soon")
		self.assertEqual(systems[("T-INFRA-VENT", self.hall)]["status"], "In Date")
		self.assertEqual(audits.on_time("Ventilation", "2026-11-10"), (1, 2))
		self.assertEqual(audits.on_time("Water Supply", "2026-11-10"), (1, 1))

	def test_latest_inspection_of_a_system_counts(self):
		vent = ef.make_infra_template("T-INFRA-VENT", "Ventilation", interval=30).name
		ef.make_session(vent, self.ward, self.or_zone, audit_date="2026-09-01", next_due="2026-10-01")
		ef.make_session(vent, self.ward, self.or_zone, audit_date="2026-10-20", next_due="2026-11-19")
		self.assertEqual(audits.on_time("Ventilation", "2026-11-10"), (1, 1))

	def test_reminder_seven_days_before_due(self):
		vent = ef.make_infra_template("T-INFRA-VENT", "Ventilation", interval=30).name
		ef.make_session(vent, self.ward, self.or_zone, audit_date="2026-10-01", next_due="2026-11-17")
		with patch("tracecore.core.notification.emit") as emit:
			audits.run_daily("2026-11-09")
			self.assertFalse(emit.called)
			audits.run_daily("2026-11-10")
		self.assertEqual(emit.call_args.args[0], audits.INFRA_DUE_EVENT)
