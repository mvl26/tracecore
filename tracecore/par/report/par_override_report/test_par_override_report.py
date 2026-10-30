"""Par Override Report (SCR-31, FR-M8-04.3, AC-11): ghi đè theo tháng và KPI."""

import frappe
from frappe.utils import add_days, today

from tracecore.par import override
from tracecore.par.report.par_override_report.par_override_report import execute
from tracecore.par.tests.test_override import OverrideCase, exceeded_set
from tracecore.tests.utils import bru

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

COLUMNS = [
	"name",
	"set_unit",
	"set_type",
	"department",
	"status",
	"requested_by",
	"requested_at",
	"reason",
	"cycles_used",
	"max_cycles",
	"extra_cycles",
	"cycles_consumed",
	"valid_until",
	"decided_by",
	"decided_at",
	"decision_reason",
]


def _summary(report):
	return {item["label"].split(" (")[0]: item["value"] for item in report[4]}


class TestParOverrideReport(OverrideCase):
	def _filters(self, **extra):
		return {"from_date": today(), "to_date": today(), **extra}

	@bru("BRU-PAR-004")
	def test_lists_override_requests_with_decision(self):
		approved_unit, _codes = exceeded_set()
		rejected_unit, _codes = exceeded_set()
		open_unit, _codes = exceeded_set()
		approved = override.request(approved_unit, "Cần gấp").name
		rejected = override.request(rejected_unit, "Không rõ").name
		pending = override.request(open_unit, "Đang chờ").name
		self.approve(approved, extra=3, reason="OK")
		frappe.set_user(self.approver)
		override.reject(rejected, "Bộ đã mòn", "246810")
		frappe.set_user("Administrator")

		report = execute(self._filters())
		self.assertEqual([column["fieldname"] for column in report[0]], COLUMNS)
		rows = {row["name"]: row for row in report[1]}
		self.assertTrue({approved, rejected, pending} <= set(rows))
		self.assertEqual(rows[approved]["extra_cycles"], 3)
		self.assertEqual(rows[approved]["decided_by"], self.approver)
		self.assertEqual(rows[approved]["decision_reason"], "OK")
		self.assertEqual(rows[rejected]["decision_reason"], "Bộ đã mòn")
		self.assertIsNone(rows[pending]["decided_by"])
		self.assertEqual(rows[pending]["set_unit"], open_unit)
		self.assertEqual((rows[pending]["cycles_used"], rows[pending]["max_cycles"]), (300, 300))

	def test_filters_by_status_and_date_range(self):
		unit, _codes = exceeded_set()
		name = override.request(unit, "Cần").name
		self.assertIn(name, [row["name"] for row in execute(self._filters(status="Requested"))[1]])
		self.assertNotIn(name, [row["name"] for row in execute(self._filters(status="Approved"))[1]])
		yesterday = add_days(today(), -1)
		past = execute({"from_date": add_days(yesterday, -5), "to_date": yesterday})[1]
		self.assertNotIn(name, [row["name"] for row in past])

	@bru("BRU-PAR-004")
	def test_kpi_overridden_share_of_sets_at_their_limit(self):
		first, _codes = exceeded_set()
		second, _codes = exceeded_set()
		self.approve(override.request(first, "Cần").name)
		override.request(second, "Cần")
		summary = _summary(execute(self._filters()))
		self.assertGreaterEqual(summary["Sets at Their Limit"], 2)
		self.assertGreaterEqual(summary["Approved Overrides"], 1)
		self.assertGreaterEqual(summary["Override Requests"], 2)
		report = execute(self._filters())
		share = next(item for item in report[4] if "Overridden Share" in item["label"])
		expected = round(100 * summary["Approved Overrides"] / summary["Sets at Their Limit"], 1)
		self.assertEqual(share["value"], expected)

	def test_default_range_is_previous_month(self):
		columns, rows, _msg, _chart, summary = execute({})
		self.assertEqual(len(columns), len(COLUMNS))
		self.assertEqual(len(summary), 4)

	def test_report_roles(self):
		roles = frappe.get_all(
			"Has Role", filters={"parent": "Par Override Report", "parenttype": "Report"}, pluck="role"
		)
		self.assertEqual(set(roles), {"TC R01", "TC R02", "TC R10", "System Manager"})
