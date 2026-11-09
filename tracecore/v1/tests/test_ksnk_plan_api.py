"""RPC tracecore.v1.ksnk_plan.* — màn SCR-48 (FEAT-058 AC-1, AC-4, AC-12, AC-13; UC-41; plan D7)."""

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.ui import ksnk
from tracecore.v1 import ksnk_plan as api

YEAR = getdate(today()).year


class TestKsnkPlanApi(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		fx.clear_plans(YEAR)
		frappe.db.sql("delete from `tabIC Procedure Document`")
		self.r01, self.r13, self.r02 = (
			fx.user("R01", "api-plan"),
			fx.user("R13", "api-plan"),
			fx.user("R02", "api-plan"),
		)
		self.owner_user = fx.user("R11", "api-plan-owner")
		self.owner = fx.employee("Api Owner", user=self.owner_user)
		self.ind = fx.indicator("T-API-HH")
		fx.indicator_value(self.ind, f"{YEAR}-01", 784, 1000, locked=0)
		self.plan = fx.plan(
			YEAR,
			indicators=[(self.ind, 71, 80)],
			activities=[
				{"activity": "Late", "responsible": self.owner, "due_date": add_days(today(), -2)},
				{
					"activity": "Done",
					"responsible": self.owner,
					"due_date": add_days(today(), 30),
					"status": "Completed",
				},
			],
		)

	def test_registry_entry(self):
		screen = next(s for s in ksnk.SCREENS if s["slug"] == "ke-hoach")
		self.assertEqual((screen["scr"], screen["uc"], screen["group"]), ("SCR-48", "UC-41", "program"))
		self.assertNotIn("TC R02", screen["roles"])
		self.assertIn(
			"tracecore.infection_program.annual_plan.badges", frappe.get_hooks("tracecore_ksnk_badges")
		)

	def test_status_shape_for_r01(self):
		fx.procedure("API-01", issued_on=add_days(today(), -400), review_due=add_days(today(), -1))
		frappe.set_user(self.r01)
		data = api.status()
		plan = data["plan"]
		self.assertEqual(plan["name"], self.plan.name)
		self.assertEqual((plan["activities_completed"], plan["activities_total"]), (1, 2))
		self.assertEqual(plan["overdue"], 1)
		self.assertEqual(plan["activities"][0]["display_status"], "overdue")
		self.assertTrue(plan["activities"][0]["can_update"] is False)  # Nháp: chưa cập nhật tiến độ
		self.assertAlmostEqual(plan["indicators"][0]["latest"], 78.4)
		self.assertEqual(plan["total_budget_vnd"], 2000000)
		self.assertEqual(data["documents"][0]["status_key"], "overdue")
		self.assertEqual(data["documents_attention"], 1)
		self.assertFalse(data["can_approve"])
		self.assertFalse(data["can_amend"])

	def test_r02_cannot_open(self):
		frappe.set_user(self.r02)
		with self.assertRaises(frappe.PermissionError):
			api.status()

	@bru("BRU-ICP-004")
	def test_r13_approves_from_screen_and_r01_amends(self):
		frappe.set_user(self.r13)
		self.assertTrue(api.status()["can_approve"])
		result = api.approve_plan(self.plan.name)
		self.assertTrue(result["ok"])
		self.assertEqual(result["status"]["plan"]["docstatus"], 1)
		frappe.set_user(self.r01)
		data = api.status()
		self.assertTrue(data["can_amend"])
		self.assertTrue(data["plan"]["activities"][0]["can_update"])
		amended = api.make_amendment(self.plan.name)
		self.assertTrue(amended["ok"])
		self.assertEqual(api.status()["plan"]["pending_amendment"], amended["name"])

	@bru("BRU-ICP-004")
	def test_r01_approve_is_rejected(self):
		frappe.set_user(self.r01)
		with self.assertRaises(frappe.PermissionError):
			api.approve_plan(self.plan.name)

	def test_block_body_on_validation_error(self):
		fx.approve(self.plan, self.r13)
		frappe.set_user(self.r13)
		result = api.approve_plan(self.plan.name)  # đã ghi sổ
		self.assertFalse(result["ok"])
		self.assertEqual(set(result["error"]), {"title", "reason", "action"})

	def test_update_activity_by_responsible(self):
		plan = fx.approve(self.plan, self.r13)
		frappe.set_user(self.owner_user)
		result = api.update_activity(plan.name, plan.activities[0].name, "Completed", "XN-2026-00118")
		self.assertTrue(result["ok"])
		bad = api.update_activity(plan.name, plan.activities[0].name, "Bogus")
		self.assertFalse(bad["ok"])

	def test_latest_meeting_and_open_conclusions(self):
		older = fx.meeting(
			[("Old open item", self.owner, add_days(today(), 5))],
			meeting_date=add_days(today(), -60),
			submit=True,
		)
		latest = fx.meeting(
			[("New item", self.owner, add_days(today(), -1))], meeting_date=today(), submit=True
		)
		frappe.set_user(self.r13)
		data = api.status()
		self.assertEqual(data["meeting"]["name"], latest.name)
		self.assertEqual(data["meeting"]["resolutions"][0]["display_status"], "overdue")
		self.assertIn(older.name, [row["meeting"] for row in data["open_resolutions"]])
		self.assertNotIn(latest.name, [row["meeting"] for row in data["open_resolutions"]])
