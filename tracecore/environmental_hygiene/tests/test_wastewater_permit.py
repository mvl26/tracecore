"""Giấy phép môi trường (GPMT) có phiên bản và mẫu quy chuẩn nước thải (FEAT-095; FR-M15-08, .1, .2; BRU-ENV-004;
AC-095-01, 03, 04; A-153 W2)."""

import frappe

from tracecore.environmental_hygiene import wastewater
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.utils import IsolatedTestCase, bru


class PermitCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.point = ef.make_point().name


class TestPermitValidation(PermitCase):
	def test_permit_requires_core_fields_and_at_least_one_parameter(self):
		"""AC-095-01."""
		with self.assertRaises(frappe.ValidationError):
			ef.make_permit("T-NOROW", rows=[], submit=False)
		with self.assertRaises(frappe.MandatoryError):
			ef.make_permit("T-NOCOL", rows=ef.rows_for(self.point), submit=False, standard_column="")

	def test_non_auto_row_requires_frequency_but_auto_row_does_not(self):
		rows = ef.rows_for(self.point)
		rows[1]["frequency_months"] = ""
		with self.assertRaises(frappe.ValidationError) as raised:
			ef.make_permit("T-FREQ", rows=rows, submit=False)
		self.assertIn("COD", str(raised.exception))
		permit = ef.make_permit("T-FREQ2", rows=ef.rows_for(self.point), submit=False)
		self.assertEqual(permit.parameters[-1].frequency_months, "")

	def test_row_needs_a_limit_and_min_not_above_max(self):
		rows = ef.rows_for(self.point)
		rows[1].pop("max_value")
		with self.assertRaises(frappe.ValidationError):
			ef.make_permit("T-NOLIM", rows=rows, submit=False)
		rows = ef.rows_for(self.point)
		rows[0]["min_value"] = 10
		with self.assertRaises(frappe.ValidationError):
			ef.make_permit("T-MINMAX", rows=rows, submit=False)

	def test_parameter_listed_twice_for_same_point_is_blocked(self):
		rows = ef.rows_for(self.point)
		rows.append(dict(rows[1]))
		with self.assertRaises(frappe.ValidationError):
			ef.make_permit("T-DUP", rows=rows, submit=False)


class TestPermitVersions(PermitCase):
	@bru("BRU-ENV-004")
	def test_name_is_versioned_and_new_version_supersedes_old(self):
		"""AC-095-03, FR-M15-08.1."""
		v1 = ef.make_permit("T-0154", rows=ef.rows_for(self.point))
		self.assertEqual((v1.name, v1.version_no), ("GPMT-T-0154-V1", 1))
		v2 = wastewater.new_version(v1.name)
		self.assertEqual((v2.name, v2.docstatus), ("GPMT-T-0154-V2", 0))
		self.assertEqual(len(v2.parameters), len(v1.parameters))
		self.assertEqual(wastewater.new_version(v1.name).name, v2.name)
		v2.effective_from = "2026-07-01"
		v2.save()
		v2.submit()
		self.assertEqual(frappe.db.get_value("Wastewater Permit", v1.name, "superseded_by"), v2.name)

	def test_approved_permit_is_locked(self):
		v1 = ef.make_permit("T-LOCK", rows=ef.rows_for(self.point))
		v1.reload()
		v1.permit_no = "Khác"
		with self.assertRaises(frappe.ValidationError):
			v1.save()

	@bru("BRU-ENV-004")
	def test_active_permit_for_point_is_the_approved_version_in_effect_on_the_date(self):
		v1 = ef.make_permit("T-ACT", rows=ef.rows_for(self.point))
		v2 = wastewater.new_version(v1.name)
		v2.effective_from = "2026-07-01"
		v2.save()
		v2.submit()
		self.assertEqual(wastewater.active_permit(self.point, "2026-06-30"), v1.name)
		self.assertEqual(wastewater.active_permit(self.point, "2026-07-01"), v2.name)
		self.assertIsNone(wastewater.active_permit(self.point, "2025-12-31"))
		other = ef.make_point("T Điểm xả khác", "Discharge").name
		self.assertIsNone(wastewater.active_permit(other, "2026-07-01"))

	def test_days_to_expiry(self):
		permit = ef.make_permit("T-EXP", rows=ef.rows_for(self.point), valid_until="2027-01-31")
		self.assertEqual(wastewater.days_to_expiry(permit, "2026-11-02"), 90)


class TestStandardTemplates(PermitCase):
	def test_qcvn28_column_b_has_limits_and_qcvn40_lists_parameters_without_limits(self):
		"""AC-095-04, FR-M15-08.2: mẫu là dữ liệu, chỉ nạp khi R01 yêu cầu."""
		before = frappe.db.count("Wastewater Permit")
		rows = {row["parameter"]: row for row in wastewater.template("QCVN 28:2010/BTNMT", "B")}
		self.assertEqual((rows["pH"]["min_value"], rows["pH"]["max_value"]), (6.5, 8.5))
		self.assertEqual(rows["COD"]["max_value"], 100)
		self.assertTrue(rows["Salmonella"]["detect_only"])
		self.assertIn("QCVN 28:2010", rows["COD"]["legal_ref"])
		self.assertEqual(wastewater.template("QCVN 28:2010/BTNMT", "A")[0]["parameter"], "pH")
		new = wastewater.template("QCVN 40:2025/BTNMT", "B")
		self.assertTrue(new)
		self.assertTrue(all(not row.get("max_value") for row in new))
		self.assertEqual(frappe.db.count("Wastewater Permit"), before)
		with self.assertRaises(frappe.ValidationError):
			wastewater.template("QCVN 99", "B")

	def test_template_rows_go_into_a_draft_permit_for_a_point(self):
		rows = wastewater.template("QCVN 28:2010/BTNMT", "B", point=self.point, frequency="3")
		self.assertTrue(all(row["wastewater_point"] == self.point for row in rows))
		permit = ef.make_permit("T-TPL", rows=rows, submit=False)
		self.assertEqual(permit.docstatus, 0)
		self.assertGreaterEqual(len(permit.parameters), 10)
