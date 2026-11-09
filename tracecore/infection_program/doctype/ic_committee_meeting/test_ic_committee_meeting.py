"""IC Committee Meeting — biên bản họp Hội đồng (FEAT-058 AC-11, AC-12; FR-M11-08, FR-M11-08.1, .2; UC-41 A3)."""

import frappe
from frappe.utils import add_days, today

from tracecore.infection_program import meetings
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix

DOCTYPE = "IC Committee Meeting"


class TestICCommitteeMeeting(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.owner_user = fx.user("R11", prefix="meet-owner")
		self.with_user = fx.employee("Meet Owner", user=self.owner_user)
		self.no_user = fx.employee("Meet NoUser")

	def _three(self):
		due = add_days(today(), 20)
		return [
			("Add pharmacy representative", self.with_user, due),
			("Roll out VAP bundle", self.with_user, due),
			("Approve hand rub budget", self.no_user, due),
		]

	def test_meta_and_permissions(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertTrue(meta.is_submittable)
		self.assertEqual(meta.get_field("attendees").options, "IC Meeting Attendee")
		self.assertEqual(meta.get_field("resolutions").options, "IC Resolution")
		self.assertIsNone(frappe.get_meta("IC Resolution").get_field("owner"))
		assert_permission_matrix(self, DOCTYPE)

	def test_three_conclusions_make_three_todos(self):
		frappe.clear_messages()
		doc = fx.meeting(self._three(), attendees=[self.with_user], submit=True)
		doc.reload()
		todos = [row.todo for row in doc.resolutions]
		self.assertEqual(len(set(filter(None, todos))), 3)
		first = frappe.get_doc("ToDo", todos[0])
		self.assertEqual(first.allocated_to, self.owner_user)
		self.assertEqual(first.reference_type, DOCTYPE)
		self.assertEqual(first.reference_name, doc.name)
		self.assertEqual(str(first.date), str(doc.resolutions[0].due_date))
		self.assertEqual(frappe.db.get_value("ToDo", todos[2], "allocated_to"), "Administrator")
		self.assertIn("Meet NoUser", str(frappe.get_message_log()))
		self.assertEqual(frappe.db.count("ToDo", {"reference_name": doc.name}), 3)

	def test_closing_todo_closes_conclusion_and_cancel_cancels_todos(self):
		doc = fx.meeting(self._three(), submit=True)
		doc.reload()
		todo = frappe.get_doc("ToDo", doc.resolutions[0].todo)
		todo.status = "Closed"
		todo.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("IC Resolution", doc.resolutions[0].name, "status"), "Done")
		todo.reload()
		todo.status = "Open"
		todo.save(ignore_permissions=True)
		self.assertEqual(frappe.db.get_value("IC Resolution", doc.resolutions[0].name, "status"), "Open")
		doc.cancel()
		self.assertEqual(frappe.db.get_value("ToDo", doc.resolutions[1].todo, "status"), "Cancelled")

	def test_open_conclusions_from_previous_meetings(self):
		first = fx.meeting(self._three(), meeting_date=add_days(today(), -90), submit=True)
		first.reload()
		frappe.db.set_value("IC Resolution", first.resolutions[2].name, "status", "Done")
		draft = fx.meeting(meeting_date=today())
		rows = meetings.open_resolutions(exclude=draft.name)
		mine = [row for row in rows if row.meeting == first.name]
		self.assertEqual(len(mine), 2)
		self.assertEqual(mine[0].content, "Add pharmacy representative")
		self.assertNotIn(first.name, [row.meeting for row in meetings.open_resolutions(exclude=first.name)])
		r13, r02 = fx.user("R13", prefix="meet"), fx.user("R02", prefix="meet")
		frappe.set_user(r13)
		self.assertTrue(meetings.open_resolutions_for(draft.name))
		frappe.set_user(r02)
		with self.assertRaises(frappe.PermissionError):
			meetings.open_resolutions_for(draft.name)

	def test_committee_in_force_filled_and_attendee_unique(self):
		committee = fx.committee(fx.full_committee_members("MT"), valid_from=add_days(today(), -400), submit=True)
		doc = fx.meeting(attendees=[self.with_user])
		self.assertEqual(doc.committee, committee.name)
		with self.assertRaises(frappe.ValidationError):
			fx.meeting(attendees=[self.with_user, self.with_user])
