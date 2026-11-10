"""IC Improvement Project — dự án cải tiến chất lượng / đề tài nghiên cứu KSNK (FEAT-072 AC-1..AC-4; FR-M11-12,
FR-M11-12.1; UC-42 bước 5; A-149 Q2, Q4)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, getdate, today

from tracecore.infection_program import improvement
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix

DOCTYPE = "IC Improvement Project"


def project(status=improvement.PLAN, start=None, end=None, result="", **fields):
	return frappe.get_doc(
		{
			"doctype": DOCTYPE,
			"project_type": "Quality Improvement",
			"title": fields.pop("title", "Tăng tuân thủ vệ sinh tay"),
			"measure_group": "Hand Hygiene",
			"start_date": start or add_days(today(), -60),
			"end_date": end,
			"status": status,
			"result_summary": result,
			**fields,
		}
	).insert(ignore_permissions=True)


def clear():
	frappe.db.delete(DOCTYPE)


class TestICImprovementProject(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.local.lang = "en"
		clear()

	def test_meta(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertEqual(meta.module, "Infection Program")
		self.assertEqual(meta.autoname, "CI-.YYYY.-.###")
		self.assertFalse(meta.is_submittable)
		self.assertEqual(meta.get_field("status").options.split("\n"), list(improvement.STATUSES))
		self.assertEqual(meta.get_field("project_type").options.split("\n"), list(improvement.TYPES))
		self.assertEqual(meta.get_field("lead").options, "Employee")
		self.assertEqual(meta.get_field("attachments").fieldtype, "Attach")
		groups = frappe.get_meta("IC Indicator").get_field("measure_group").options
		self.assertEqual(meta.get_field("measure_group").options, groups)
		for field in ("project_type", "title", "measure_group", "start_date", "end_date", "result_summary"):
			self.assertIsNotNone(meta.get_field(field), field)

	def test_name_series(self):
		doc = project()
		self.assertTrue(doc.name.startswith(f"CI-{today()[:4]}-"), doc.name)

	def test_completed_requires_end_date_and_result(self):
		with self.assertRaises(frappe.ValidationError) as ctx:
			project(status=improvement.COMPLETED)
		self.assertIn("End Date", str(ctx.exception))
		self.assertIn("Result Summary", str(ctx.exception))
		doc = project(status=improvement.COMPLETED, end=today(), result="58 % → 69 %")
		self.assertEqual(doc.status, improvement.COMPLETED)

	def test_end_before_start_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			project(start=today(), end=add_days(today(), -1))

	def test_completed_in_future_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			project(status=improvement.COMPLETED, end=add_days(today(), 3), result="Xong")

	def test_audit_log_written(self):
		doc = project()
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_doctype": DOCTYPE, "ref_name": doc.name}))

	def test_indicator_counts_completed_year_to_date(self):
		year = getdate(today()).year
		project(status=improvement.COMPLETED, start=f"{year}-01-02", end=f"{year}-01-10", result="A")
		project(status=improvement.COMPLETED, start=f"{year - 1}-03-01", end=f"{year - 1}-12-20", result="B")
		project(status=improvement.CHECK, start=f"{year}-01-02")
		project(status=improvement.CANCELLED, start=f"{year}-01-02", end=f"{year}-01-05")
		self.assertEqual(improvement.completed_count(f"{year}-01"), (1, 0, 1))
		self.assertEqual(improvement.completed_count(f"{year - 1}-12"), (1, 0, 1))
		self.assertEqual(improvement.completed_count(f"{year - 1}-11"), (0, 0, 0))
		# dự án không thuộc khoa: theo khoa không ghi dòng
		self.assertEqual(improvement.completed_count(f"{year}-01", "Any Department"), (0, 0, 0))

	def test_registered_indicator_and_self_check(self):
		from tracecore.core import indicators

		self.assertIs(indicators.registry()[improvement.INDICATOR_KEY], improvement.completed_count)
		from tracecore.core import extension

		checks = {}
		for result in extension.run("tracecore_ic_self_checks"):
			checks.update(result or {})
		self.assertIn(improvement.SELF_CHECK_KEY, checks)

	def test_self_check_met_when_completed_in_year(self):
		year = getdate(today()).year
		self.assertEqual(improvement.self_check(year), {"status": "Not met", "source_ref": ""})
		doc = project(status=improvement.COMPLETED, start=f"{year}-01-02", end=f"{year}-01-10", result="A")
		self.assertEqual(improvement.self_check(year), {"status": "Met", "source_ref": doc.name})

	def test_rows_of_year(self):
		year = getdate(today()).year
		done = project(
			status=improvement.COMPLETED, start=f"{year}-01-02", end=f"{year}-01-10", result="58 → 69"
		)
		doing = project(status=improvement.DO, start=f"{year - 1}-06-01", title="Gói VAP")
		project(status=improvement.COMPLETED, start=f"{year - 2}-01-02", end=f"{year - 2}-03-01", result="cũ")
		project(status=improvement.CANCELLED, start=f"{year}-01-02")
		data = improvement.rows(year)
		self.assertEqual([row["name"] for row in data["projects"]], sorted([done.name, doing.name]))
		self.assertEqual((data["completed"], data["in_progress"], data["total"]), (1, 1, 2))
		labels = {row["name"]: row["status_label"] for row in data["projects"]}
		self.assertEqual(labels[doing.name], "Do (D)")


class TestICImprovementProjectPermissions(FrappeTestCase):
	def test_permission_matrix(self):
		assert_permission_matrix(self, DOCTYPE)

	def test_nobody_deletes(self):
		for row in frappe.get_meta(DOCTYPE).permissions:
			self.assertFalse(row.delete, row.role)

	def test_r11_reads_but_cannot_write(self):
		user = factories.make_user("ksnk-ci-r11@example.com", ["TC R11"])
		self.assertTrue(frappe.has_permission(DOCTYPE, "read", user=user))
		self.assertFalse(frappe.has_permission(DOCTYPE, "write", user=user))
		r01 = factories.make_user("ksnk-ci-r01@example.com", ["TC R01"])
		self.assertTrue(frappe.has_permission(DOCTYPE, "create", user=r01))
