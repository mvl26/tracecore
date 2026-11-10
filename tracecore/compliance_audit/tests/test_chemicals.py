"""Hóa chất KSNK theo khoa–tháng từ 3 nguồn (FEAT-066; FR-M12-12, FR-M12-12.1, FR-M12-12.2; UC-46; A-142)."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import today

from tracecore.compliance_audit import chemicals
from tracecore.compliance_audit.tests import chemical_factories as cf
from tracecore.core import indicators
from tracecore.tests import factories


class ChemicalCase(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		factories.use_stock_company(self)
		self.icu = factories.make_department("KSNK Test Hồi sức")
		self.surg = factories.make_department("KSNK Test Ngoại")
		self.rub = cf.make_chemical("TC-HC-VST", "Hand Rub")
		self.soap = cf.make_chemical("TC-HC-XP", "Soap")
		self.surface = cf.make_chemical("TC-HC-BM", "Surface Disinfectant", stock_uom=cf.BOTTLE, litre_factor=2)
		self.plain = cf.make_chemical("TC-HC-NOTYPE", None)
		self.period = today()[:7]
		# mỗi test một khoa riêng: dữ liệu giữa các test trong class không bị hoàn tác
		self.dept = factories.make_department(f"KSNK {self._testMethodName[5:40]}")


class TestChemicalRecord(ChemicalCase):
	def test_doctype_is_submittable_named_hc_and_cannot_be_deleted(self):
		meta = frappe.get_meta(chemicals.DOCTYPE)
		self.assertTrue(meta.is_submittable)
		self.assertEqual(meta.autoname, "naming_series:")
		doc = cf.record(self.rub, self.icu, 2)
		self.assertTrue(doc.name.startswith("HC-"))
		self.assertEqual(doc.docstatus, 1)
		self.assertEqual(doc.chemical_type, "Hand Rub")
		self.assertEqual(doc.qty_litre, 2)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc(chemicals.DOCTYPE, doc.name, ignore_permissions=True)

	def test_item_without_chemical_type_or_bad_values_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			cf.record(self.plain, self.icu, 1)
		with self.assertRaises(frappe.ValidationError):
			cf.record(self.rub, self.icu, 0)
		with self.assertRaises(frappe.ValidationError):
			cf.record(self.rub, self.icu, 1, period="2026-13")

	def test_litres_from_uom_conversion_or_missing(self):
		self.assertEqual(chemicals.to_litre(self.surface, 6), 3)
		bare = cf.make_chemical("TC-HC-BM-NOL", "Surface Disinfectant", stock_uom=cf.BOTTLE)
		self.assertIsNone(chemicals.to_litre(bare, 6))
		doc = cf.record(bare, self.icu, 6)
		self.assertFalse(doc.qty_litre)

	def test_cancel_needs_reason(self):
		doc = cf.record(self.rub, self.icu, 1)
		with self.assertRaises(frappe.ValidationError):
			doc.cancel()
		chemicals.cancel(doc.name, "Wrong department")
		self.assertEqual(frappe.db.get_value(chemicals.DOCTYPE, doc.name, "docstatus"), 2)


class TestStockEntrySource(ChemicalCase):
	def setUp(self):
		super().setUp()
		self.ward = cf.ward_warehouse("KSNK Test Kho HSTC", self.icu)

	def _rows(self, entry):
		return frappe.get_all(
			chemicals.DOCTYPE,
			filters={"source": chemicals.STOCK_ENTRY, "source_ref": entry},
			fields=["name", "docstatus", "department", "item", "qty", "qty_litre", "period", "source_row"],
		)

	def test_transfer_to_ward_warehouse_records_consumption(self):
		entry = cf.make_transfer(self.surface, 4, self.ward)
		rows = self._rows(entry.name)
		self.assertEqual(len(rows), 1)
		row = rows[0]
		self.assertEqual((row.department, row.item, row.qty, row.qty_litre), (self.icu, self.surface, 4, 2))
		self.assertEqual(row.period, str(entry.posting_date)[:7])
		self.assertEqual(row.docstatus, 1)
		# chạy lại hook không tạo trùng
		chemicals.on_stock_entry_submit(frappe.get_doc("Stock Entry", entry.name))
		self.assertEqual(len(self._rows(entry.name)), 1)

	def test_non_ward_warehouse_and_untyped_item_ignored(self):
		other = factories.make_warehouse("KSNK Test Kho chung")
		entry = cf.make_transfer(self.rub, 1, other)
		self.assertFalse(self._rows(entry.name))
		entry = cf.make_transfer(self.plain, 1, self.ward)
		self.assertFalse(self._rows(entry.name))

	def test_cancel_stock_entry_cancels_record(self):
		entry = cf.make_transfer(self.rub, 3, self.ward)
		entry.cancel()
		rows = self._rows(entry.name)
		self.assertEqual([row.docstatus for row in rows], [2])


class TestDuplicates(ChemicalCase):
	def test_two_sources_wait_for_confirmation_and_leave_totals(self):
		manual = cf.record(self.soap, self.dept, 5)
		imported = cf.record(
			self.soap, self.dept, 7, source=chemicals.IMPORT, source_ref="PX-1", source_row="k1"
		)
		for name in (manual.name, imported.name):
			self.assertEqual(
				frappe.db.get_value(chemicals.DOCTYPE, name, "duplicate_status"), chemicals.AWAITING
			)
		rows = chemicals.monthly(self.period, self.period)
		self.assertFalse([r for r in rows if r.department == self.dept and r.item == self.soap and not r.awaiting])
		summary = chemicals.summary(*chemicals.quarter_of(self.period))
		dept = next(d for d in summary["departments"] if d["department"] == self.dept)
		self.assertEqual(dept["litres"]["Soap"], 0)
		self.assertEqual(dept["awaiting"], 1)

	def test_choose_source_cancels_other_source_with_audit_log(self):
		manual = cf.record(self.soap, self.dept, 5)
		imported = cf.record(
			self.soap, self.dept, 7, source=chemicals.IMPORT, source_ref="PX-2", source_row="k2"
		)
		cancelled = chemicals.choose_source(self.period, self.dept, self.soap, chemicals.IMPORT, "Pharmacy file is complete")
		self.assertEqual(cancelled, [manual.name])
		self.assertEqual(frappe.db.get_value(chemicals.DOCTYPE, manual.name, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value(chemicals.DOCTYPE, imported.name, "duplicate_status"), chemicals.KEPT)
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": chemicals.DOCTYPE, "ref_name": manual.name, "action": "Cancel"})
		)
		summary = chemicals.summary(*chemicals.quarter_of(self.period))
		dept = next(d for d in summary["departments"] if d["department"] == self.dept)
		self.assertEqual(dept["litres"]["Soap"], 7)

	def test_choose_source_requires_reason_and_conflict(self):
		cf.record(self.soap, self.dept, 5)
		with self.assertRaises(frappe.ValidationError):
			chemicals.choose_source(self.period, self.dept, self.soap, chemicals.MANUAL, "no conflict")
		cf.record(self.soap, self.dept, 7, source=chemicals.IMPORT, source_ref="PX-3", source_row="k3")
		with self.assertRaises(frappe.ValidationError):
			chemicals.choose_source(self.period, self.dept, self.soap, chemicals.MANUAL, " ")

	def test_same_source_twice_is_not_duplicate(self):
		cf.record(self.soap, self.dept, 1)
		second = cf.record(self.soap, self.dept, 2)
		self.assertFalse(frappe.db.get_value(chemicals.DOCTYPE, second.name, "duplicate_status"))


class TestSummary(ChemicalCase):
	def test_quarter_equals_sum_of_months(self):
		year, quarter = 2026, 1
		for month, qty in (("2026-01", 1.5), ("2026-02", 2), ("2026-03", 3.25)):
			cf.record(self.rub, self.dept, qty, period=month)
		cf.record(self.surface, self.dept, 4, period="2026-02")  # 2 lít
		summary = chemicals.summary(year, quarter)
		dept = next(d for d in summary["departments"] if d["department"] == self.dept)
		months = [
			sum(r.qty_litre for r in chemicals.monthly(p, p, department=self.dept) if r.chemical_type == "Hand Rub")
			for p in ("2026-01", "2026-02", "2026-03")
		]
		self.assertAlmostEqual(dept["litres"]["Hand Rub"], sum(months))
		self.assertAlmostEqual(dept["litres"]["Hand Rub"], 6.75)
		self.assertAlmostEqual(dept["litres"]["Surface Disinfectant"], 2)
		self.assertAlmostEqual(summary["total"]["litres"]["Hand Rub"], sum(
			d["litres"]["Hand Rub"] for d in summary["departments"]
		))

	def test_per_1000_patient_days_when_census_exists(self):
		cf.record(self.rub, self.dept, 12, period="2026-04")
		with patch.object(chemicals, "patient_days", return_value=600):
			summary = chemicals.summary(2026, 2)
		dept = next(d for d in summary["departments"] if d["department"] == self.dept)
		self.assertAlmostEqual(dept["hand_rub_per_1000"], 20)

	def test_no_census_shows_no_denominator(self):
		cf.record(self.rub, self.dept, 12, period="2026-07")
		with patch.object(chemicals, "patient_days", return_value=None):
			summary = chemicals.summary(2026, 3)
		dept = next(d for d in summary["departments"] if d["department"] == self.dept)
		self.assertIsNone(dept["hand_rub_per_1000"])
		self.assertIsNone(dept["patient_days"])

	def test_patient_days_none_without_census_doctype(self):
		with patch("frappe.db.exists", return_value=False):
			self.assertIsNone(chemicals.patient_days(["2026-07"], self.dept))

	def test_indicator_registered_as_litres_over_patient_days(self):
		registry = indicators.registry()
		self.assertIn(chemicals.INDICATOR, registry)
		cf.record(self.rub, self.dept, 3, period="2026-05")
		with patch.object(chemicals, "patient_days", return_value=150):
			self.assertEqual(registry[chemicals.INDICATOR]("2026-05", self.dept), (3, 150, 150))
		with patch.object(chemicals, "patient_days", return_value=None):
			self.assertEqual(registry[chemicals.INDICATOR]("2026-05", self.dept), (3, 0, 0))

	def test_script_report_columns_and_total(self):
		from tracecore.compliance_audit.report.ic_chemical_consumption_by_department import (
			ic_chemical_consumption_by_department as report,
		)

		cf.record(self.rub, self.dept, 2, period="2026-10")
		columns, data = report.execute({"year": 2026, "quarter": 4})[:2]
		fields = [c["fieldname"] for c in columns]
		for field in ("department", "hand_rub", "soap", "surface", "instrument", "other", "hand_rub_per_1000"):
			self.assertIn(field, fields)
		self.assertTrue(any(row.get("department") == self.dept and row["hand_rub"] == 2 for row in data))
		self.assertTrue(data[-1].get("is_total"))
