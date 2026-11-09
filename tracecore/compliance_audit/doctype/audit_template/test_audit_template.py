"""Audit Template — mẫu phiếu có phiên bản (FEAT-060 AC-1, AC-2, AC-4, AC-15; FR-M12-01, BRU-AUD-001, A-132)."""

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from tracecore.compliance_audit import templates
from tracecore.compliance_audit.tests.factories import (
	R01,
	R11,
	make_template,
	template_values,
)
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru

DOCTYPE = "Audit Template"


class TestAuditTemplate(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")

	def test_named_by_code_and_version_in_compliance_audit(self):
		doc = make_template("t-pnc", submit=False)
		self.assertEqual(doc.template_code, "T-PNC")
		self.assertEqual(doc.version_no, 1)
		self.assertEqual(doc.name, "MP-T-PNC-V1")
		self.assertEqual(frappe.get_meta(DOCTYPE).module, "Compliance Audit")
		self.assertTrue(frappe.get_meta(DOCTYPE).is_submittable)

	def test_options_of_type_and_scoring(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertEqual(
			meta.get_field("scoring_method").options.split("\n"),
			["By Opportunity", "All or None", "Weighted Score"],
		)
		self.assertIn("Prevention Bundle", meta.get_field("audit_type").options.split("\n"))
		self.assertEqual(
			frappe.get_meta("Audit Template Item").get_field("answer_type").options.split("\n"),
			["Pass/Fail", "Choice", "Number", "Photo"],
		)

	def test_invalid_template_rejected(self):
		cases = {
			"duplicate item code": dict(
				items=(("A-1", "", "Q1", 1, 0), ("A-1", "", "Q2", 1, 0)),
			),
			"negative weight": dict(items=(("A-1", "", "Q1", -1, 0),)),
			"no items": dict(items=()),
			"bad code": dict(code="T PNC"),
			"threshold above 100": dict(pass_threshold=120),
			"negative min sample": dict(min_sample=-1),
		}
		for label, values in cases.items():
			with self.subTest(label), self.assertRaises(frappe.ValidationError):
				code = values.pop("code", "T-BAD")
				frappe.get_doc(template_values(code, **values)).insert(ignore_permissions=True)

	def test_scored_template_needs_pass_fail_item(self):
		values = template_values("T-NUM")
		values["items"][0]["answer_type"] = "Number"
		values["items"] = values["items"][:1]
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc(values).insert(ignore_permissions=True)

	@bru("BRU-AUD-001")
	def test_only_r01_approves(self):
		r11 = factories.make_user("aud-r11@example.com", [R11])
		r01 = factories.make_user("aud-r01@example.com", [R01])
		frappe.set_user(r11)
		doc = frappe.get_doc(template_values("T-R11")).insert()
		with self.assertRaises(frappe.PermissionError):
			doc.submit()
		frappe.set_user(r01)
		doc = frappe.get_doc(DOCTYPE, doc.name)
		doc.submit()
		self.assertEqual(doc.docstatus, 1)

	@bru("BRU-AUD-001")
	def test_approved_content_is_locked_with_new_version_hint(self):
		doc = make_template("T-LOCK")
		doc.reload()
		doc.items[0].question = "Changed question"
		with self.assertRaises(frappe.ValidationError) as caught:
			doc.save()
		self.assertIn("V2", str(caught.exception))
		doc.reload()
		doc.items[0].weight = 9
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	@bru("BRU-AUD-001")
	def test_new_version_copies_items_and_supersedes_on_approval(self):
		v1 = make_template("T-VER")
		v2 = templates.new_version(v1.name)
		self.assertEqual(v2.name, "MP-T-VER-V2")
		self.assertEqual(v2.docstatus, 0)
		self.assertEqual([row.item_code for row in v2.items], [row.item_code for row in v1.items])
		self.assertEqual(
			templates.new_version(v1.name).name, v2.name
		)  # Nháp đang có thì trả lại, không tạo V3
		self.assertEqual(templates.active_version("T-VER"), v1.name)
		v2.items[0].question = "Revised question"
		v2.save()
		v2.submit()
		self.assertEqual(frappe.db.get_value(DOCTYPE, v1.name, "superseded_by"), v2.name)
		self.assertEqual(templates.active_version("T-VER"), v2.name)
		self.assertEqual(
			frappe.db.get_value("Audit Template Item", {"parent": v1.name, "idx": 1}, "question"),
			"Hand hygiene before gloving",
		)

	def test_only_latest_approved_version_can_be_revised(self):
		v1 = make_template("T-OLD")
		templates.new_version(v1.name).submit()
		with self.assertRaises(frappe.ValidationError):
			templates.new_version(v1.name)
		draft = make_template("T-DRAFT", submit=False)
		with self.assertRaises(frappe.ValidationError):
			templates.new_version(draft.name)

	def test_second_draft_of_same_code_rejected(self):
		make_template("T-TWO", submit=False)
		with self.assertRaises(frappe.ValidationError):
			make_template("T-TWO", submit=False)

	def test_future_version_not_active_yet(self):
		v1 = make_template("T-FUT")
		v2 = templates.new_version(v1.name)
		v2.effective_from = add_days(today(), 10)
		v2.save()
		v2.submit()
		self.assertEqual(templates.active_version("T-FUT"), v1.name)
		self.assertEqual(templates.active_version("T-FUT", add_days(today(), 10)), v2.name)
		self.assertIsNone(templates.active_version("T-NONE"))

	def test_bundle_without_critical_item_warns_and_logs(self):
		items = (("VAP-01", "", "Head of bed 30-45", 1, 0),)
		doc = make_template(
			"T-VAP", audit_type="Prevention Bundle", bundle_type="VAP", scoring="All or None", items=items
		)
		self.assertTrue(
			frappe.db.exists(
				"Audit Log",
				{
					"ref_doctype": DOCTYPE,
					"ref_name": doc.name,
					"action": "Submit",
					"reason": ["like", templates.NO_CRITICAL_REASON + "%"],
				},
			)
		)

	def test_install_templates_never_overwrites(self):
		"""Cơ chế NFR-MAINT-04: nạp mẫu khởi tạo chỉ chèn mã còn thiếu, giữ bản bệnh viện đã sửa/đã duyệt."""
		rows = [template_values("T-SEED-A"), template_values("T-SEED-B")]
		for row in rows:
			row.pop("doctype")
		self.assertEqual(templates.install_templates(rows), ["MP-T-SEED-A-V1", "MP-T-SEED-B-V1"])
		edited = frappe.get_doc(DOCTYPE, "MP-T-SEED-A-V1")
		edited.title = "Hospital title"
		edited.save()
		frappe.get_doc(DOCTYPE, "MP-T-SEED-B-V1").submit()
		self.assertEqual(templates.install_templates(rows), [])
		self.assertEqual(frappe.db.get_value(DOCTYPE, "MP-T-SEED-A-V1", "title"), "Hospital title")
		self.assertEqual(frappe.db.count(DOCTYPE, {"template_code": ["in", ["T-SEED-A", "T-SEED-B"]]}), 2)


class TestAuditTemplatePermissions(FrappeTestCase):
	def test_permission_matrix(self):
		assert_permission_matrix(self, DOCTYPE)
