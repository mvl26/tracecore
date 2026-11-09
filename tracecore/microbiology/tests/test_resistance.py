"""Báo cáo kháng thuốc theo quý (FEAT-067 AC-12, AC-13; FR-M14-08, FR-M14-08.1; BRU-MDR-002; NFR-PRIV-01; A-136 Q8)."""

import frappe

from tracecore.microbiology import resistance
from tracecore.microbiology.report.antimicrobial_resistance_by_quarter import (
	antimicrobial_resistance_by_quarter as report,
)
from tracecore.microbiology.tests.factories import make_organism, new_isolate
from tracecore.tests.factories import make_department
from tracecore.tests.utils import IsolatedTestCase, bru


class TestResistance(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		make_organism()
		make_organism("eco", "Escherichia coli", "Enterobacterales")
		frappe.db.delete("MDRO Rule", {"rule_code": ["not like", "T-%"]})
		frappe.db.delete("Microbiology Isolate", {"period_key": "2026-Q3"})
		self.icu = make_department("Khoa Hồi sức vi sinh")
		self.surgery = make_department("Khoa Ngoại vi sinh")
		# 3 người bệnh, 4 chủng K. pneumoniae trong quý III; người bệnh 1 có chủng lặp lại (không tính)
		new_isolate(lab="Q1", patient="BN1", collected_on="2026-07-05", results=(("MEM", "R"), ("CIP", "S")))
		new_isolate(lab="Q2", patient="BN1", collected_on="2026-08-05", results=(("MEM", "S"), ("CIP", "S")))
		new_isolate(lab="Q3", patient="BN2", collected_on="2026-08-06", results=(("MEM", "S"), ("CIP", "I")))
		new_isolate(
			lab="Q4",
			patient="BN3",
			collected_on="2026-09-07",
			department=self.surgery,
			results=(("MEM", "R"),),
		)
		new_isolate(lab="Q5", patient="BN4", collected_on="2026-10-01", results=(("MEM", "R"),))

	@bru("BRU-MDR-002")
	def test_rates_use_first_isolates_only(self):
		rows = {(r["organism"], r["antibiotic"]): r for r in resistance.compute(2026, 3)}
		mem = rows[("kpn", "MEM")]
		self.assertEqual((mem["tested"], mem["s_pct"], mem["i_pct"], mem["r_pct"]), (3, 33.3, 0.0, 66.7))
		cip = rows[("kpn", "CIP")]
		self.assertEqual((cip["tested"], cip["s_pct"], cip["i_pct"]), (2, 50.0, 50.0))
		self.assertTrue(mem["small_sample"])

	def test_by_department_and_threshold_setting(self):
		frappe.db.set_single_value("IC Program Settings", "ast_min_isolates", 2)
		rows = resistance.compute(2026, 3, by_department=True)
		icu = next(r for r in rows if r["department"] == self.icu and r["antibiotic"] == "MEM")
		surgery = next(r for r in rows if r["department"] == self.surgery and r["antibiotic"] == "MEM")
		self.assertEqual((icu["tested"], icu["r_pct"], icu["small_sample"]), (2, 50.0, False))
		self.assertEqual((surgery["tested"], surgery["small_sample"]), (1, True))
		only_icu = resistance.compute(2026, 3, department=self.icu)
		self.assertEqual({r["tested"] for r in only_icu if r["antibiotic"] == "MEM"}, {2})

	def test_report_columns_have_no_patient_code_and_warn_in_text(self):
		frappe.local.lang = "vi"
		self.addCleanup(setattr, frappe.local, "lang", "en")
		columns, data, message, _chart, summary = report.execute({"year": 2026, "quarter": "3"})
		names = {column["fieldname"] for column in columns}
		self.assertFalse(names & {"patient_code", "patient_code_masked", "patient_code_hash", "name"})
		self.assertNotIn("BN1", frappe.as_json(data))
		warning = next(row for row in data if row["antibiotic"] == "MEM")["warning"]
		self.assertIn("30", warning)
		self.assertTrue(summary)
		self.assertTrue(message)

	def test_quarter_validation(self):
		with self.assertRaises(frappe.ValidationError):
			resistance.compute(2026, 5)
