"""Audit Session — phiếu giám sát (FEAT-060 AC-3, AC-4, AC-6, AC-7, AC-9 phần quyền khoa; BRU-AUD-001/004/005)."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.compliance_audit import templates
from tracecore.compliance_audit.tests.factories import (
	R11,
	R12,
	answers,
	make_dept_user,
	make_observer,
	make_template,
)
from tracecore.core.errors import BlockedError
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

DOCTYPE = "Audit Session"
ALL_PASS = dict.fromkeys(("PNC-01", "PNC-02", "PNC-03", "PNC-04", "PNC-05"), "Pass")


# Link Supplier, Incident CAPA và Environment Zone (→ Environmental Sample → Incident CAPA) kéo bản ghi test của ERPNext (cần setup wizard)
test_ignore = [
	"Item",
	"Batch",
	"Supplier",
	"Incident CAPA",
	"Environment Zone",
	"Department",
	"User",
	"Employee",
]


class AuditSessionCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.dept_a = factories.make_department("Audit Ward A")
		self.dept_b = factories.make_department("Audit Ward B")
		self.template = make_template("T-SES", min_sample=3)
		self.observer = make_observer()
		self.subject = make_observer(first_name="Audit Subject")

	def make_session(self, rows=None, submit=False, **values):
		doc = frappe.get_doc(
			{
				"doctype": DOCTYPE,
				"audit_template": self.template.name,
				"department": self.dept_a,
				"observer": self.observer,
				"answers": answers(**(rows or {})),
				**values,
			}
		).insert()
		if submit:
			doc.submit()
		return doc

	def assertBlocked(self, code, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			fn(*args, **kwargs)
		self.assertEqual(caught.exception.block.code, code)


class TestAuditSession(AuditSessionCase):
	def test_named_by_series_in_compliance_audit(self):
		doc = self.make_session()
		self.assertTrue(doc.name.startswith("GS-"))
		self.assertEqual(frappe.get_meta(DOCTYPE).module, "Compliance Audit")
		self.assertEqual(doc.template_code, "T-SES")
		self.assertEqual(doc.scoring_method, "Weighted Score")

	@bru("BRU-AUD-001")
	def test_items_are_copied_from_the_template_version(self):
		doc = self.make_session({"PNC-02": "Fail"})
		self.assertEqual([row.item_code for row in doc.answers], list(ALL_PASS))
		row = doc.answers[1]
		self.assertEqual(
			(row.question, row.weight, row.is_critical, row.answer),
			("PPE matches exposure risk", 2, 1, "Fail"),
		)

	@bru("BRU-AUD-001")
	def test_snapshot_survives_new_template_version(self):
		doc = self.make_session(ALL_PASS, submit=True)
		v2 = templates.new_version(self.template.name)
		v2.items[0].question = "Revised question"
		v2.items[0].weight = 5
		v2.save()
		v2.submit()
		doc.reload()
		self.assertEqual((doc.answers[0].question, doc.answers[0].weight), ("Hand hygiene before gloving", 2))
		self.assertEqual(doc.audit_template, self.template.name)

	@bru("BRU-AUD-001")
	def test_snapshot_cannot_be_edited(self):
		doc = self.make_session()
		doc.answers[0].question = "Edited"
		with self.assertRaises(frappe.ValidationError):
			doc.save()
		doc.reload()
		doc.append("answers", {"item_code": "EXTRA", "question": "Extra", "answer": "Pass"})
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	@bru("BRU-AUD-001")
	def test_draft_or_superseded_template_rejected(self):
		draft = make_template("T-SES-D", submit=False)
		self.assertBlocked("AUDIT_TEMPLATE_NOT_APPROVED", self.make_session, audit_template=draft.name)
		old_draft_session = self.make_session(ALL_PASS)
		templates.new_version(self.template.name).submit()
		self.assertBlocked("AUDIT_TEMPLATE_NOT_APPROVED", self.make_session)
		old_draft_session.reload()
		old_draft_session.submit()  # phiếu tạo trước khi đổi phiên bản giữ bản chụp (UC-44 E3)
		self.assertEqual(old_draft_session.docstatus, 1)

	@bru("BRU-AUD-004")
	def test_observer_cannot_observe_self(self):
		self.assertBlocked("AUDIT_SELF_OBSERVATION", self.make_session, subject_employee=self.observer)
		self.assertBlocked(
			"AUDIT_SELF_OBSERVATION",
			self.make_session,
			opportunities=[{"moment": "1", "action": "Hand Rub", "subject_employee": self.observer}],
		)
		doc = self.make_session(subject_employee=self.subject)
		self.assertEqual(doc.subject_employee, self.subject)

	def test_unknown_item_rejected(self):
		self.assertBlocked("AUDIT_ITEM_UNKNOWN", self.make_session, {"NOPE": "Pass"})

	def test_submit_needs_every_pass_fail_answer_and_fail_note(self):
		doc = self.make_session({"PNC-01": "Pass"})
		self.assertBlocked("AUDIT_ANSWER_MISSING", doc.submit)
		doc = self.make_session({**ALL_PASS, "PNC-03": "Fail"})
		self.assertBlocked("AUDIT_FAIL_NOTE_REQUIRED", doc.submit)
		doc.reload()
		doc.answers[2].note = "Gloves removed first"
		doc.save()
		doc.submit()
		self.assertEqual((doc.score_pct, doc.result), (87.5, "Pass"))

	@bru("BRU-AUD-005")
	def test_critical_fail_marks_fail_and_suggests_nc(self):
		doc = self.make_session({**ALL_PASS, "PNC-04": "Fail"})
		doc.answers[3].note = "Recapped with two hands"
		doc.save()
		doc.submit()
		self.assertEqual((doc.score_pct, doc.result, doc.critical_failed), (75.0, "Fail", 1))
		self.assertEqual(frappe.db.get_value(DOCTYPE, doc.name, "nc_status"), "Suggested")

	def test_insufficient_sample_flag(self):
		"""FR-M12-11: khoa-tháng có số phiếu dưới min_sample của mẫu → cờ Chưa đủ mẫu kèm n."""
		first = self.make_session(ALL_PASS, submit=True)
		self.assertEqual(frappe.db.get_value(DOCTYPE, first.name, ["sample_n", "sample_flag"]), (1, 1))
		self.make_session(ALL_PASS, submit=True)
		third = self.make_session(ALL_PASS, submit=True)
		self.assertEqual(frappe.db.get_value(DOCTYPE, third.name, ["sample_n", "sample_flag"]), (3, 0))

	def test_print_format_shows_snapshot_and_result(self):
		doc = self.make_session(ALL_PASS, submit=True)
		html = frappe.get_print("Audit Session", doc.name, "TC Audit Session")
		self.assertIn(doc.name, html)
		self.assertIn("PNC-04", html)
		self.assertIn("No two-handed needle recapping", html)

	def test_observer_defaults_to_session_employee(self):
		user = factories.make_user("aud-obs-r11@example.com", [R11])
		employee = make_observer(user=user, first_name="Logged Observer")
		frappe.set_user(user)
		doc = frappe.get_doc(
			{"doctype": DOCTYPE, "audit_template": self.template.name, "department": self.dept_b}
		).insert()
		self.assertEqual(doc.observer, employee)


class TestAuditSessionDepartmentAccess(AuditSessionCase):
	"""FR-M12-08.1, NFR-SEC-09: R12 chỉ thấy và chỉ ghi phiếu khoa mình."""

	def setUp(self):
		super().setUp()
		self.on_a = self.make_session(ALL_PASS, submit=True)
		self.on_b = self.make_session(ALL_PASS, submit=True, department=self.dept_b)
		self.r12_a = make_dept_user("aud-r12-a@example.com", R12, self.dept_a)
		self.r12_none = factories.make_user("aud-r12-none@example.com", [R12])
		self.r11 = factories.make_user("aud-r11-all@example.com", [R11])

	def _visible(self, user):
		frappe.set_user(user)
		names = set(frappe.get_list(DOCTYPE, pluck="name"))
		frappe.set_user("Administrator")
		return names & {self.on_a.name, self.on_b.name}

	def test_r12_sees_only_own_department(self):
		self.assertEqual(self._visible(self.r12_a), {self.on_a.name})
		self.assertEqual(self._visible(self.r12_none), set())
		self.assertEqual(self._visible(self.r11), {self.on_a.name, self.on_b.name})

	def test_r12_cannot_open_or_create_other_department(self):
		frappe.set_user(self.r12_a)
		self.assertTrue(frappe.has_permission(DOCTYPE, "read", self.on_a.name))
		self.assertFalse(frappe.has_permission(DOCTYPE, "read", self.on_b.name))
		with self.assertRaises(frappe.PermissionError):
			self.make_session(department=self.dept_b)
		doc = self.make_session()
		self.assertEqual(doc.department, self.dept_a)


class TestAuditSessionPermissions(FrappeTestCase):
	def test_permission_matrix(self):
		assert_permission_matrix(self, DOCTYPE)
		assert_permission_matrix(self, "Audit Schedule")
