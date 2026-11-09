"""Dữ liệu màn SCR-50 (mẫu phiếu & lịch) và SCR-53 (báo cáo tuân thủ) trên Page tc-ksnk (FEAT-060 AC-13)."""

import frappe
from frappe.utils import add_days, today

from tracecore.compliance_audit import board, templates
from tracecore.compliance_audit.tests.factories import (
	R01,
	R02,
	R11,
	R13,
	answers,
	make_observer,
	make_template,
	template_values,
)
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase

ALL_PASS = dict.fromkeys(("PNC-01", "PNC-02", "PNC-03", "PNC-04", "PNC-05"), "Pass")


class BoardCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.r01 = factories.make_user("aud-board-r01@example.com", [R01])
		self.r11 = factories.make_user("aud-board-r11@example.com", [R11])
		self.r02 = factories.make_user("aud-board-r02@example.com", [R02])
		self.r13 = factories.make_user("aud-board-r13@example.com", [R13])
		self.dept = factories.make_department("Board Ward A")


class TestTemplateBoard(BoardCase):
	def test_versions_with_text_status(self):
		v1 = make_template("T-BRD")
		v2 = templates.new_version(v1.name)
		v2.effective_from = add_days(today(), 5)
		v2.save()
		v2.submit()
		draft = make_template("T-BRD-D", submit=False)
		frappe.set_user(self.r01)
		data = board.template_board()
		status = {row["name"]: row["status"] for row in data["templates"]}
		self.assertEqual(status[v1.name], "Approved")
		self.assertEqual(status[v2.name], "Scheduled")
		self.assertEqual(status[draft.name], "Draft")
		templates.new_version(v2.name)  # có thể làm V3 từ bản mới nhất
		frappe.set_user("Administrator")
		v1.reload()
		frappe.set_user(self.r01)
		detail = board.template_board(v1.name)["selected"]
		self.assertEqual(detail["name"], v1.name)
		self.assertFalse(detail["can_edit"])
		self.assertEqual(len(detail["items"]), 5)
		self.assertIn("Weighted Score", board.template_board()["options"]["scoring_methods"])

	def test_r11_saves_draft_r01_approves(self):
		values = template_values("T-BRD-NEW")
		values.pop("doctype")
		frappe.set_user(self.r11)
		saved = board.save_template(values)
		self.assertTrue(saved["ok"])
		name = saved["name"]
		values.update(name=name, title="Edited title")
		values["items"].append(
			{"item_code": "PNC-06", "question": "Photo", "answer_type": "Photo", "weight": 0}
		)
		self.assertTrue(board.save_template(values)["ok"])
		self.assertEqual(frappe.db.count("Audit Template Item", {"parent": name}), 6)
		self.assertFalse(board.template_board(name)["selected"]["can_approve"])
		denied = board.approve_template(name)
		self.assertIs(denied["ok"], False)
		frappe.set_user(self.r01)
		self.assertTrue(board.template_board(name)["selected"]["can_approve"])
		self.assertTrue(board.approve_template(name)["ok"])
		self.assertEqual(frappe.db.get_value("Audit Template", name, "docstatus"), 1)

	def test_saving_approved_template_returns_inline_error(self):
		v1 = make_template("T-BRD-LOCK")
		values = template_values("T-BRD-LOCK")
		values.update(name=v1.name, title="Changed")
		frappe.set_user(self.r01)
		res = board.save_template(values)
		self.assertIs(res["ok"], False)
		self.assertIn("V2", res["error"]["reason"])
		res = board.new_version(v1.name)
		self.assertEqual(res["name"], "MP-T-BRD-LOCK-V2")


class TestScheduleBoard(BoardCase):
	def test_r02_creates_schedule_and_sees_coverage(self):
		tpl = make_template("T-BRD-SCH")
		assignee = make_observer(first_name="Board Assignee")
		frappe.set_user(self.r02)
		res = board.save_schedule(
			{
				"audit_template": tpl.name,
				"frequency": "Monthly",
				"target_count": 4,
				"assignee": assignee,
				"departments": [{"department": self.dept}],
			}
		)
		self.assertTrue(res["ok"], res)
		frappe.set_user("Administrator")
		doc = frappe.get_doc(
			{
				"doctype": "Audit Session",
				"audit_template": tpl.name,
				"department": self.dept,
				"observer": make_observer(),
				"answers": answers(**ALL_PASS),
			}
		).insert()
		doc.submit()
		frappe.set_user(self.r02)
		row = next(r for r in board.schedule_board()["schedules"] if r["name"] == res["name"])
		self.assertEqual(row["coverage"][0]["label"], "1/4")
		self.assertEqual(row["coverage_pct"], 25)

	def test_schedule_on_draft_template_inline_error(self):
		draft = make_template("T-BRD-SD", submit=False)
		frappe.set_user(self.r02)
		res = board.save_schedule(
			{
				"audit_template": draft.name,
				"frequency": "Monthly",
				"target_count": 1,
				"assignee": make_observer(),
				"departments": [{"department": self.dept}],
			}
		)
		self.assertIs(res["ok"], False)


class TestComplianceBoard(BoardCase):
	def setUp(self):
		super().setUp()
		self.template = make_template("T-BRD-C")
		observer = make_observer(first_name="Board Observer")
		for rows in (ALL_PASS, {**ALL_PASS, "PNC-04": "Fail"}):
			doc = frappe.get_doc(
				{
					"doctype": "Audit Session",
					"audit_template": self.template.name,
					"department": self.dept,
					"observer": observer,
					"answers": answers(**rows),
				}
			)
			for row in doc.answers:
				row.note = "x" if row.answer == "Fail" else None
			doc.insert().submit()

	def test_cards_rows_recent_and_pending(self):
		frappe.set_user(self.r11)
		data = board.compliance_board({"template_code": "T-BRD-C"})
		self.assertEqual(data["cards"]["posted"], 2)
		self.assertEqual(data["cards"]["passed"], 1)
		self.assertEqual(data["cards"]["critical"], 1)
		self.assertEqual(data["rows"][0]["rate_label"], "50 % (n = 2)")
		self.assertEqual(len(data["recent"]), 2)
		self.assertTrue(data["can_decide"])
		self.assertEqual(len([p for p in data["pending"] if p["template_code"] == "T-BRD-C"]), 1)

	def test_r13_sees_totals_only(self):
		frappe.set_user(self.r13)
		data = board.compliance_board({"template_code": "T-BRD-C"})
		self.assertEqual(data["cards"]["posted"], 2)
		self.assertEqual(data["recent"], [])
		self.assertEqual(data["pending"], [])
		self.assertFalse(data["can_decide"])
