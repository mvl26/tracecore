"""Báo cáo tuân thủ, nhãn cỡ mẫu và chỉ số cho M9 (FEAT-060 AC-11, AC-12; FR-M12-11, FR-M12-14, BRU-RPT-001)."""

import frappe
from frappe.utils import get_first_day, get_last_day, getdate

from tracecore.compliance_audit import compliance, indicators
from tracecore.compliance_audit.report.compliance_by_department import compliance_by_department as report
from tracecore.compliance_audit.tests.factories import (
	R12,
	R13,
	answers,
	make_dept_user,
	make_observer,
	make_template,
)
from tracecore.core import indicators as indicator_registry
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

TODAY = getdate()
PERIOD = TODAY.strftime("%Y-%m")
ALL_PASS = dict.fromkeys(("PNC-01", "PNC-02", "PNC-03", "PNC-04", "PNC-05"), "Pass")


class ComplianceCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.dept_a = factories.make_department("Report Ward A")
		self.dept_b = factories.make_department("Report Ward B")
		self.template = make_template("T-RPT", min_sample=20)
		self.observer = make_observer(first_name="Report Observer")

	def post(self, department, passed=True, submit=True, **values):
		rows = dict(ALL_PASS)
		if not passed:
			rows["PNC-04"] = "Fail"
		doc = frappe.get_doc(
			{
				"doctype": "Audit Session",
				"audit_template": self.template.name,
				"department": department,
				"observer": self.observer,
				"answers": answers(**rows),
				**values,
			}
		)
		for row in doc.answers:
			if row.answer == "Fail":
				row.note = "Failed"
		doc.insert()
		if submit:
			doc.submit()
		return doc

	def filters(self, **values):
		return frappe._dict(
			from_date=get_first_day(TODAY), to_date=get_last_day(TODAY), template_code="T-RPT", **values
		)


class TestCompliance(ComplianceCase):
	@bru("BRU-RPT-001")
	def test_rate_with_insufficient_sample_label(self):
		"""FR-M12-11.1: 8 phiếu, 6 Đạt, min_sample 20 → "75 % (n = 8, chưa đủ cỡ mẫu)"."""
		for passed in (True,) * 6 + (False,) * 2:
			self.post(self.dept_a, passed)
		row = next(r for r in compliance.aggregate(self.filters()) if r["department"] == self.dept_a)
		self.assertEqual((row["sessions"], row["passed"], row["pass_rate"]), (8, 6, 75.0))
		self.assertEqual(row["sample_note"], "Insufficient sample")
		self.assertEqual(compliance.rate_label(row), "75 % (n = 8, insufficient sample)")
		self.assertEqual(row["critical_failed"], 2)

	@bru("BRU-RPT-001")
	def test_no_audit_is_not_calculated(self):
		rows = compliance.aggregate(self.filters(department=self.dept_b))
		self.assertEqual(len(rows), 1)
		self.assertIsNone(rows[0]["pass_rate"])
		self.assertEqual(rows[0]["sample_note"], "Not calculated")
		self.assertEqual(compliance.rate_label(rows[0]), "Not calculated")

	def test_only_posted_audits_counted(self):
		"""FR-M12-14.1: số liệu báo cáo = tổng phiếu đã ghi sổ trong kỳ, không tính Nháp/Hủy."""
		self.post(self.dept_a)
		self.post(self.dept_a, passed=False)
		self.post(self.dept_a, submit=False)
		self.post(self.dept_a).cancel()
		row = next(r for r in compliance.aggregate(self.filters()) if r["department"] == self.dept_a)
		expected = frappe.db.count(
			"Audit Session", {"docstatus": 1, "department": self.dept_a, "template_code": "T-RPT"}
		)
		self.assertEqual(row["sessions"], expected)
		self.assertEqual(row["sessions"], 2)
		self.assertEqual(row["avg_score"], 87.5)

	def test_profession_filter(self):
		self.post(self.dept_a, subject_role="Nurse")
		self.post(self.dept_a, subject_role="Doctor", passed=False)
		row = compliance.aggregate(self.filters(profession="Nurse"))[0]
		self.assertEqual((row["sessions"], row["passed"]), (1, 1))

	def test_r12_sees_only_own_department(self):
		self.post(self.dept_a)
		self.post(self.dept_b)
		frappe.set_user(make_dept_user("aud-rpt-r12@example.com", R12, self.dept_a))
		self.assertEqual({r["department"] for r in compliance.aggregate(self.filters())}, {self.dept_a})


class TestIndicatorsAndReport(ComplianceCase):
	def test_pass_rate_registered_for_m9(self):
		self.post(self.dept_a)
		self.post(self.dept_a, passed=False)
		self.post(self.dept_b)
		registry = indicator_registry.registry()
		self.assertIn(indicators.RATE_ALL, registry)
		self.assertIn("AUDIT_PASS_PPE", registry)
		numerator, denominator, sample = registry[indicators.RATE_ALL](PERIOD, self.dept_a)
		self.assertEqual((numerator, denominator, sample), (1, 2, 2))
		self.assertGreaterEqual(registry["AUDIT_PASS_PPE"](PERIOD, None)[1], 3)

	def test_report_columns_and_rows(self):
		self.post(self.dept_a)
		columns, data = report.execute(self.filters())[:2]
		self.assertEqual(
			[c["fieldname"] for c in columns][:4], ["template_code", "department", "sessions", "passed"]
		)
		row = next(r for r in data if r.get("department") == self.dept_a)
		self.assertEqual(row["rate_label"], "100 % (n = 1, insufficient sample)")

	def test_r13_runs_report_but_r12_limited(self):
		self.post(self.dept_a)
		self.post(self.dept_b)
		frappe.set_user(factories.make_user("aud-rpt-r13@example.com", [R13]))
		data = report.execute(self.filters())[1]
		self.assertTrue({self.dept_a, self.dept_b} <= {r.get("department") for r in data})
