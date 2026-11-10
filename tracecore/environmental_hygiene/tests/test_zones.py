"""Vùng vệ sinh và mức nguy cơ (FEAT-070; FR-M15-01, .1, .2; BRU-ENV-001; UC-54 E1; A-148 a)."""

import frappe

from tracecore.core.errors import BlockedError
from tracecore.environmental_hygiene import zones
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.factories import make_supplier
from tracecore.tests.utils import IsolatedTestCase, bru


class ZoneCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward = ef.make_department("VV Khoa Gây mê")
		self.other = ef.make_department("VV Khoa Nội")
		for department in (self.ward, self.other):
			frappe.db.delete(zones.DOCTYPE, {"department": department})
		self.high = ef.make_level("T Rất cao", minimum=4, high=1)
		self.low = ef.make_level("T Thấp", minimum=1, high=0, order=10)


class TestZoneRules(ZoneCase):
	def test_risk_level_and_party_are_required(self):
		with self.assertRaises(BlockedError) as raised:
			ef.make_zone(self.ward, level="", party="Department")
		self.assertEqual(raised.exception.block.code, "ENV_ZONE_RISK_REQUIRED")
		with self.assertRaises(BlockedError) as raised:
			ef.make_zone(self.ward, party="")
		self.assertEqual(raised.exception.block.code, "ENV_ZONE_PARTY_REQUIRED")

	def test_outsourced_zone_needs_vendor_and_department_zone_drops_it(self):
		with self.assertRaises(BlockedError) as raised:
			ef.make_zone(self.ward, party="Outsourced Vendor")
		self.assertEqual(raised.exception.block.code, "ENV_ZONE_VENDOR_REQUIRED")
		vendor = make_supplier("VV Công ty vệ sinh A")
		zone = ef.make_zone(self.ward, party="Outsourced Vendor", supplier=vendor)
		self.assertEqual(zone.supplier, vendor)
		own = ef.make_zone(self.ward, area="Hành lang", party="Department", supplier=vendor)
		self.assertFalse(own.supplier)

	@bru("BRU-ENV-001")
	def test_minimum_audits_come_from_risk_level_unless_set(self):
		zone = ef.make_zone(self.ward, level=self.high)
		self.assertEqual(zone.min_audits_per_month, 4)
		custom = ef.make_zone(self.ward, area="Hồi tỉnh", level=self.high, min_audits_per_month=6)
		self.assertEqual(custom.min_audits_per_month, 6)

	def test_disabled_risk_level_cannot_be_used(self):
		frappe.db.set_value("Environment Risk Level", self.low, "disabled", 1)
		with self.assertRaises(BlockedError) as raised:
			ef.make_zone(self.ward, level=self.low)
		self.assertEqual(raised.exception.block.code, "ENV_ZONE_RISK_REQUIRED")


class TestCoverage(ZoneCase):
	@bru("BRU-ENV-001")
	def test_high_risk_zone_with_one_of_four_audits_is_short(self):
		"""FR-M15-01.1: vùng nguy cơ cao yêu cầu 4 phiếu/tháng mà mới có 1 → vào danh sách thiếu."""
		zone = ef.make_zone(self.ward, level=self.high)
		low = ef.make_zone(self.ward, area="Hành lang khám", level=self.low)
		template = ef.make_env_template().name
		ef.make_session(template, self.ward, zone.name, audit_date="2026-10-05")
		ef.make_session(template, self.ward, low.name, audit_date="2026-10-06")
		rows = {row["zone"]: row for row in zones.coverage("2026-10-15")}
		self.assertEqual((rows[zone.name]["done"], rows[zone.name]["required"]), (1, 4))
		self.assertTrue(rows[zone.name]["short"])
		self.assertFalse(rows[low.name]["short"])
		self.assertEqual([row["zone"] for row in zones.short_zones("2026-10-15", self.ward)], [zone.name])

	def test_coverage_counts_only_posted_audits_of_the_month(self):
		zone = ef.make_zone(self.ward, level=self.low)
		template = ef.make_env_template().name
		ef.make_session(template, self.ward, zone.name, audit_date="2026-09-30")
		ef.make_session(template, self.ward, zone.name, audit_date="2026-10-02", submit=False)
		row = next(row for row in zones.coverage("2026-10-01") if row["zone"] == zone.name)
		self.assertEqual(row["done"], 0)
		self.assertTrue(row["short"])

	def test_disabled_zone_is_not_listed(self):
		zone = ef.make_zone(self.ward, level=self.high, disabled=1)
		self.assertNotIn(zone.name, [row["zone"] for row in zones.coverage("2026-10-01")])


class TestZoneScope(ZoneCase):
	def test_network_member_sees_only_own_department_zones(self):
		"""FR-M15-01.2: R12 làm phiếu khoa mình — chỉ thấy vùng của khoa có User Permission."""
		from tracecore.compliance_audit.tests.factories import make_dept_user

		mine = ef.make_zone(self.ward, level=self.high)
		theirs = ef.make_zone(self.other, area="Buồng bệnh", level=self.low)
		user = make_dept_user("vv-r12@example.com", ef.R12, self.ward)
		self.assertIn(self.ward, zones.query_conditions(user))
		self.assertTrue(zones.has_permission(mine, user))
		self.assertFalse(zones.has_permission(theirs, user))
		wide = make_dept_user("vv-r11@example.com", ef.R11, self.other)
		self.assertEqual(zones.query_conditions(wide), "")
		self.assertIsNone(zones.has_permission(theirs, wide))
