"""Xuất báo cáo NKVM / NK hồi sức theo hồ sơ ánh xạ cột, chỉ tổng hợp hoặc mã BN che (FEAT-064; FR-M13-12, 12.1;
BRU-RPT-002; A-147 Q4, j) và chỉ số NKVM, KSDP (FR-M13-09; A-147 h)."""

import csv
import io

import frappe
from openpyxl import load_workbook

from tracecore.core import exporter
from tracecore.hai_surveillance import exports, ssi, ssi_indicators
from tracecore.hai_surveillance.tests import factories as f
from tracecore.hai_surveillance.tests import hai_fixtures as h
from tracecore.hai_surveillance.tests import ssi_fixtures as s
from tracecore.tests.utils import IsolatedTestCase, bru


def _rows(content):
	return list(load_workbook(io.BytesIO(content)).active.iter_rows(values_only=True))


class TestSSIExport(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward = f.make_ward("KSNK Export CTCH")
		self.icu = f.make_ward("KSNK Export Hồi sức")
		frappe.db.set_value("Department", self.icu, "tc_icu", 1)
		self.group = s.make_group("T-APPY", name="Cắt ruột thừa test", t=60)
		s.set_threshold(60)
		self.a = s.make_ssi(self.ward, self.group.name, surgery="2026-10-02", duration_min=90)  # NNIS 2
		self.b = s.make_ssi(
			self.ward,
			self.group.name,
			surgery="2026-10-05",
			code="BN-0000000777",
			asa_score=1,
			duration_min=40,
			prophylaxis_minutes_before_incision=-5,
		)  # NNIS 0, Muộn
		frappe.db.set_value(ssi.DOCTYPE, self.a.name, "outcome", ssi.SSI)
		self.r11 = f.factories.make_user("export-r11@test.local", [h.R11])
		self.r13 = f.factories.make_user("export-r13@test.local", [h.R13])

	def test_indicators(self):
		self.assertEqual(ssi_indicators.ssi_rate("2026-10", self.ward), (1, 2, 2))
		self.assertEqual(ssi_indicators.prophylaxis_rate("2026-10", self.ward), (2, 2, 2))
		self.assertEqual(ssi_indicators.prophylaxis_on_time("2026-10", self.ward), (1, 2, 2))
		self.assertEqual(
			ssi_indicators.ssi_rate("2026-09", self.ward), (0, 0, 0)
		)  # mẫu số 0 → engine "Không tính"
		self.assertEqual(set(ssi_indicators.register()), set(ssi_indicators.KEYS))

	def test_summary_by_group_and_nnis(self):
		row = next(r for r in ssi_indicators.summary("2026-10") if r["procedure_group"] == self.group.name)
		self.assertEqual((row["surgeries"], row["ssi"], row["ssi_rate"]), (2, 1, 50.0))
		self.assertEqual((row["nnis_2"], row["ssi_nnis_2"], row["ssi_rate_nnis_2"]), (1, 1, 100.0))
		self.assertEqual(
			(row["nnis_0"], row["ssi_rate_nnis_0"], row["nnis_1"], row["ssi_rate_nnis_1"]), (1, 0.0, 0, None)
		)
		self.assertEqual(row["on_time_rate"], 50.0)

	@bru("BRU-RPT-002")
	def test_ssi_cases_file_has_masked_code_only(self):
		frappe.set_user(self.r11)
		_name, content, _type = exporter.build(
			exports.SSI_CASES, {"period_from": "2026-10", "period_to": "2026-10"}
		)
		rows = _rows(content)
		text = frappe.as_json(rows)
		self.assertIn("***6612", text)
		self.assertNotIn("BN-0000006612", text)
		self.assertNotIn(frappe.db.get_value(ssi.DOCTYPE, self.a.name, "patient_code_hash"), text)
		self.assertEqual(len(rows), 3)

	def test_profile_shapes_ssi_summary_csv(self):
		frappe.get_doc(
			{
				"doctype": exporter.PROFILE_DOCTYPE,
				"profile_name": "NKVM Sở Y tế thử",
				"export_kind": exports.SSI_SUMMARY,
				"file_format": "CSV",
				"delimiter": ";",
				"columns": [
					{"source_field": "group_name", "header": "Nhóm PT"},
					{"source_field": "surgeries", "header": "Số ca mổ"},
					{"source_field": "ssi", "header": "Số ca NKVM"},
					{"source_field": "ssi_rate", "header": "Tỷ lệ %"},
				],
			}
		).insert(ignore_permissions=True)
		frappe.set_user(self.r11)
		_name, content, _type = exporter.build(
			exports.SSI_SUMMARY, {"period_from": "2026-10", "period_to": "2026-10"}, "NKVM Sở Y tế thử"
		)
		rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))
		self.assertEqual(rows[0], ["Nhóm PT", "Số ca mổ", "Số ca NKVM", "Tỷ lệ %"])
		self.assertIn(["Cắt ruột thừa test", "2", "1", "50.0"], rows)

	def test_icu_report_only_icu_departments(self):
		h.clear_definitions("TVAP")
		h.make_definition("TVAP", hours=0, days=0, device=None)
		from tracecore.hai_surveillance import cases

		in_icu = h.make_case(self.icu, onset="2026-10-20", admitted="2026-10-14 08:00:00")
		elsewhere = h.make_case(
			self.ward, onset="2026-10-20", admitted="2026-10-14 08:00:00", code="BN-0000000888"
		)
		frappe.set_user(self.r11)
		cases.decide(in_icu.name, "Confirmed")
		cases.decide(elsewhere.name, "Confirmed")
		_name, content, _type = exporter.build(
			exports.ICU_CASES, {"period_from": "2026-10", "period_to": "2026-10"}
		)
		text = frappe.as_json(_rows(content))
		self.assertIn(in_icu.name, text)
		self.assertNotIn(elsewhere.name, text)
		self.assertNotIn("BN-0000004821", text)
		_name, content, _type = exporter.build(
			exports.ICU_SUMMARY, {"period_from": "2026-10", "period_to": "2026-10"}
		)
		summary = _rows(content)
		self.assertEqual(len(summary), 2)
		self.assertEqual(summary[1][0:2], ("2026-10", "KSNK Export Hồi sức"))
		self.assertEqual(summary[1][6], 1)

	def test_script_report_rows_aggregated(self):
		from tracecore.hai_surveillance.report.ssi_by_procedure_group import ssi_by_procedure_group as report

		columns, rows = report.execute({"period_from": "2026-10"})
		self.assertIn("ssi_rate_nnis_2", [column["fieldname"] for column in columns])
		row = next(r for r in rows if r["procedure_group"] == self.group.name)
		self.assertEqual((row["surgeries"], row["ssi"]), (2, 1))
		self.assertNotIn("patient_code_masked", frappe.as_json(rows))
		self.assertEqual(report.execute({})[1], [])
		roles = {r.role for r in frappe.get_doc("Report", "SSI by Procedure Group").roles}
		self.assertIn("TC R13", roles)

	def test_r13_cannot_export(self):
		frappe.set_user(self.r13)
		with self.assertRaises(frappe.PermissionError):
			exporter.build(exports.SSI_SUMMARY, {"period_from": "2026-10"})

	def test_period_range_required_and_valid(self):
		with self.assertRaises(Exception):
			exporter.build(exports.SSI_CASES, {"period_from": "2026-13"})
