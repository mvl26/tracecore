"""FEAT-102 (A-162, FR-M9-33): RPC chỉ đọc của khu Trưởng khoa KSNK trên Page tc-flow."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from tracecore.v1 import lead, lead_board
from tracecore.v1._common import BadRequestError

NOBODY = "tcf.lead.nobody@example.com"


def make_plain_user():
	if not frappe.db.exists("User", NOBODY):
		frappe.get_doc(
			{"doctype": "User", "email": NOBODY, "first_name": "Nobody", "send_welcome_email": 0}
		).insert(ignore_permissions=True)
	return NOBODY


class TestLeadApi(FrappeTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.set_user("Administrator")

	def test_only_head_of_infection_control_roles_can_open(self):
		frappe.set_user(make_plain_user())
		for call in (
			lead.overview,
			lead.overrides,
			lead.recalls,
			lead.costs,
			lead.equipment,
			lead.staff,
			lead.sterilization_log,
		):
			with self.assertRaises(frappe.PermissionError):
				call()

	def test_overview_counts_come_from_real_records(self):
		sterile = {
			"by_set_type": [{"count": 3}, {"count": 4}],
			"expiring": [{"cycle_id": "A"}, {"cycle_id": "B"}],
		}
		sets = {
			"ok": True,
			"sets": [{"state": "blocked"}, {"state": "warn"}, {"state": "warn"}, {"state": "override"}],
		}
		with (
			patch.object(lead_board.storage, "overview", return_value=sterile),
			patch.object(lead_board.par, "check", return_value=sets),
		):
			out = lead.overview()
		kpis = out["kpis"]
		self.assertEqual(
			kpis["reprocessing"], frappe.db.count("Set Unit", {"status": ["in", ["Processing", "Reprocess"]]})
		)
		start, end = lead_board.board.period_range("day")
		loads = frappe.get_all(
			"Sterilization Load",
			filters=[["started_at", ">=", start], ["started_at", "<", end], ["docstatus", "<", 2]],
			pluck="status",
		)
		self.assertEqual(kpis["loads_today"], len(loads))
		waiting = [status for status in loads if status in ("Cycle Complete", "Quarantine")]
		self.assertEqual(kpis["loads_waiting"], len(waiting))
		self.assertEqual(
			kpis["open_nc"],
			frappe.db.count(
				"Incident CAPA", {"status": ["not in", ["Closed", "Cancelled"]], "docstatus": ["<", 2]}
			),
		)
		self.assertEqual(kpis["sterile"], 7)
		self.assertEqual(kpis["expiring"], 2)
		self.assertEqual(kpis["par_blocked"], 1)
		self.assertEqual(kpis["par_warn"], 2)
		self.assertIsInstance(kpis["cost_per_pack"], int)
		for key in ("decisions", "output", "departments"):
			self.assertIsInstance(out[key], dict if key == "decisions" else list)

	def test_overview_decisions_reuse_the_dashboard_blocks(self):
		overrides = {"count": 1, "rows": [{"name": "GD-1", "set_unit": "SU-1"}]}
		recalls = {"count": 1, "rows": [{"name": "TH-1", "pack_count": 4, "confirmed_count": 2}]}
		machines = {"count": 1, "rows": [{"name": "MH-02", "status": "Locked"}]}
		certs = {"count": 2, "rows": [{"employee": "E1"}, {"employee": "E2"}]}
		with (
			patch.object(lead_board.board, "pending_overrides", return_value=overrides),
			patch.object(lead_board.board, "open_recalls", return_value=recalls),
			patch.object(lead_board.board, "equipment_attention", return_value=machines),
			patch.object(lead_board.board, "expiring_certificates", return_value=certs),
		):
			decisions = lead.overview()["decisions"]
		self.assertEqual(decisions["overrides"], overrides)
		self.assertEqual(decisions["recalls"], recalls)
		self.assertEqual(decisions["equipment"], machines)
		self.assertEqual(decisions["certificates"], certs)

	def test_department_par_state_has_words_not_only_colour(self):
		self.assertEqual(lead_board.par_state(3, 4, 8), "below")
		self.assertEqual(lead_board.par_state(8, 6, 10), "within")
		self.assertEqual(lead_board.par_state(11, 6, 10), "above")
		self.assertEqual(lead_board.par_state(5, None, None), "none")
		self.assertEqual(lead_board.par_state(0, 0, 4), "within")

	def test_department_rows_compare_stock_with_par(self):
		levels = [
			frappe._dict(department="K1", min_qty=6, max_qty=10),
			frappe._dict(department="K1", min_qty=2, max_qty=2),
			frappe._dict(department="K2", min_qty=4, max_qty=8),
		]
		stock = {"K1": {"A": 5, "B": 3}, "K2": {"A": 1}}
		with (
			patch.object(
				lead_board.frappe, "get_all", side_effect=[levels, [("K1", "Ward 1"), ("K2", "Ward 2")]]
			),
			patch.object(lead_board.issuing, "department_stock", side_effect=lambda name: stock[name]),
		):
			rows = lead_board.department_par()
		self.assertEqual(
			rows,
			[
				{
					"department": "K1",
					"department_name": "Ward 1",
					"stock": 8,
					"min": 8,
					"max": 12,
					"state": "within",
				},
				{
					"department": "K2",
					"department_name": "Ward 2",
					"stock": 1,
					"min": 4,
					"max": 8,
					"state": "below",
				},
			],
		)

	def test_overrides_list_sets_with_replacement_forecast(self):
		sets = {
			"ok": True,
			"sets": [{"set_unit": "SU-1", "state": "blocked"}, {"set_unit": "SU-2", "state": "warn"}],
		}
		forecast = [{"set_unit": "SU-1", "month": "2026-11", "price": 48000000}]
		with (
			patch.object(lead_board.par, "check", return_value=sets) as check,
			patch.object(lead_board.slog, "life_forecast", return_value=forecast),
		):
			out = lead.overrides()
		self.assertEqual(check.call_args.kwargs["states"], ["blocked", "warn", "override"])
		self.assertEqual(out["sets"][0]["forecast"], {"month": "2026-11", "price": 48000000})
		self.assertIsNone(out["sets"][1]["forecast"])
		self.assertIsInstance(out["requests"], list)
		# Administrator có mọi vai trò: được duyệt (R01 / R02 theo par.override.DECIDE_ROLES)
		self.assertTrue(out["can_decide"])

	def test_recall_lines_never_carry_the_full_patient_code(self):
		self.assertIn("patient_code_masked", lead_board.RECALL_LINE_FIELDS)
		self.assertFalse([field for field in lead_board.RECALL_LINE_FIELDS if field == "patient_code"])
		out = lead.recalls()
		self.assertIsInstance(out["orders"], list)
		self.assertIsInstance(out["incidents"], list)
		for order in out["orders"]:
			for line in order["lines"]:
				self.assertNotIn("patient_code", line)

	def test_costs_month_is_validated(self):
		for bad in ("2026-13", "abc", "2026-1"):
			with self.assertRaises(BadRequestError):
				lead.costs(bad)
		out = lead.costs()
		self.assertEqual(out["month"], today()[:7])
		for key in ("per_load", "per_pack", "packs", "change_pct", "components", "set_types", "inputs"):
			self.assertIn(key, out)

	def test_month_without_costed_packs_has_no_change_figure(self):
		empty = {"per_load": 0, "per_pack": 0, "packs": 0, "loads": 0}
		before = {"per_load": 90, "per_pack": 25, "packs": 4, "loads": 1}
		with patch.object(lead_board, "cost_summary", side_effect=[empty, before]):
			self.assertIsNone(lead.costs("2026-11")["change_pct"])
		now = {"per_load": 80, "per_pack": 30, "packs": 2, "loads": 1}
		with patch.object(lead_board, "cost_summary", side_effect=[now, before]):
			self.assertEqual(lead.costs("2026-11")["change_pct"], 20.0)

	def test_cost_summary_weights_by_pack(self):
		sheets = [
			frappe._dict(total_cost=100, pack_count=4, steam=1),
			frappe._dict(total_cost=60, pack_count=2, steam=1),
			frappe._dict(total_cost=50, pack_count=4, steam=0),
		]
		out = lead_board.cost_summary(sheets)
		self.assertEqual(out, {"per_load": 80, "per_pack": 21, "packs": 10, "loads": 3})
		self.assertEqual(lead_board.cost_summary([]), {"per_load": 0, "per_pack": 0, "packs": 0, "loads": 0})
		self.assertEqual(lead_board.change_pct(21, 25), -16.0)
		self.assertIsNone(lead_board.change_pct(21, 0))

	def test_staff_state_follows_the_nearest_certificate(self):
		soon = {"status": "Valid", "expires_on": add_days(today(), 22), "no_expiry": 0}
		later = {"status": "Valid", "expires_on": add_days(today(), 400), "no_expiry": 0}
		gone = {"status": "Expired", "expires_on": add_days(today(), -3), "no_expiry": 0}
		forever = {"status": "Valid", "expires_on": None, "no_expiry": 1}
		self.assertEqual(lead_board.staff_state([later, soon]), ("expiring", 22))
		self.assertEqual(lead_board.staff_state([later]), ("ok", 400))
		self.assertEqual(lead_board.staff_state([gone]), ("expired", -3))
		self.assertEqual(lead_board.staff_state([forever]), ("ok", None))
		self.assertEqual(lead_board.staff_state([]), ("none", None))
		# bản đã gia hạn (Superseded) không tính
		self.assertEqual(lead_board.staff_state([{**gone, "status": "Superseded"}]), ("none", None))

	def test_staff_lists_active_employees_with_certificates_or_stations(self):
		out = lead.staff()
		self.assertIsInstance(out["rows"], list)
		for row in out["rows"]:
			self.assertIn(row["state"], ("expiring", "ok", "expired", "none"))
			self.assertIsInstance(row["stations"], list)

	def test_equipment_lists_machines_with_today_tests_and_programs(self):
		out = lead.equipment()
		self.assertEqual(len(out["rows"]), frappe.db.count("Equipment", {"status": ["!=", "Retired"]}))
		for row in out["rows"]:
			for key in ("name", "status", "tests", "programs", "inspection_days", "expiring"):
				self.assertIn(key, row)

	def test_sterilization_log_reads_the_register_of_one_machine_and_day(self):
		rows = [{"load": "ME-1", "pack_count": 6}]
		with patch.object(lead_board.slog, "log_rows", return_value=rows) as log_rows:
			out = lead.sterilization_log(equipment=None, date="2026-11-13")
		log_rows.assert_called_once_with(
			{"from_date": "2026-11-13", "to_date": "2026-11-13", "equipment": None}
		)
		self.assertEqual(out["rows"], rows)
		self.assertEqual(out["date"], "2026-11-13")
		self.assertIsInstance(out["machines"], list)
		for bad in ("13/11/2026", "2026-02-30"):
			with self.assertRaises(BadRequestError):
				lead.sterilization_log(date=bad)
		with self.assertRaises(BadRequestError):
			lead.sterilization_log(equipment="NO-SUCH-MACHINE", date="2026-11-13")
