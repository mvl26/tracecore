"""Bộ mẫu phiếu khởi tạo (FEAT-061 AC-1, AC-11, AC-12; FR-M12-02 .1 .2; BRU-AUD-001; NFR-MAINT-04, D10).

Bộ mẫu đã được nạp ở ``after_install``/``after_migrate`` của site test; ``Audit Template`` không xóa được (Audit Log), nên
các ca "nạp khi còn thiếu" chạy trên bản sao mã hậu tố ``-X`` rồi hoàn tác cuối ca.
"""

import frappe

from tracecore.compliance_audit import hand_hygiene, seed, templates
from tracecore.tests.utils import IsolatedTestCase, bru

CODES = ["VST", "PPE", "VAP", "CLABSI", "CAUTI", "SSI", "VSMT", "OUTSRC"]
test_ignore = ["Item", "Batch", "Supplier", "Incident CAPA", "Department", "User", "Employee"]


def seeded(codes=CODES):
	return frappe.get_all(
		"Audit Template",
		filters={"template_code": ["in", codes]},
		fields=[
			"name",
			"template_code",
			"docstatus",
			"audit_type",
			"scoring_method",
			"bundle_type",
			"legal_ref",
		],
		order_by="template_code asc",
	)


def copies():
	"""Bộ mẫu với mã hậu tố -X (chưa có trong DB)."""
	return [{**row, "template_code": row["template_code"] + "-X"} for row in seed.rows()]


class TestSeedTemplates(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		seed.ensure_seed()  # idempotent: site test đã có bộ mẫu từ lúc migrate

	@bru("BRU-AUD-001")
	def test_exactly_eight_draft_templates_with_legal_ref(self):
		self.assertEqual(len(seed.TEMPLATES), 8)
		rows = seeded()
		self.assertEqual(sorted(row.template_code for row in rows), sorted(CODES))
		self.assertEqual({row.docstatus for row in rows}, {0})  # Nháp: R01 duyệt tại bệnh viện
		self.assertTrue(all(row.legal_ref for row in rows))
		self.assertTrue(all(row.name.endswith("-V1") for row in rows))

	def test_a_missing_set_is_created_whole_in_draft(self):
		created = templates.install_templates(copies())
		self.assertEqual(len(created), 8)
		self.assertEqual({row.docstatus for row in seeded([code + "-X" for code in CODES])}, {0})

	@bru("BRU-AUD-001")
	def test_running_twice_creates_no_duplicates(self):
		templates.install_templates(copies())
		self.assertEqual(templates.install_templates(copies()), [])
		self.assertEqual(seed.ensure_seed(), [])
		self.assertEqual(len(seeded()), 8)

	def test_kinds_cover_hygiene_ppe_bundles_environment_and_vendor(self):
		by_code = {row.template_code: row for row in seeded()}
		self.assertEqual(
			(by_code["VST"].audit_type, by_code["VST"].scoring_method), ("Hand Hygiene", "By Opportunity")
		)
		self.assertEqual(by_code["PPE"].scoring_method, "Weighted Score")
		bundles = ("VAP", "CLABSI", "CAUTI", "SSI")
		self.assertEqual(
			{code: by_code[code].bundle_type for code in bundles}, dict(zip(bundles, bundles, strict=True))
		)
		self.assertTrue(all(by_code[code].scoring_method == "All or None" for code in bundles))
		self.assertEqual(by_code["VSMT"].audit_type, "Environmental Hygiene")
		self.assertEqual(by_code["OUTSRC"].audit_type, "Outsourced Service")

	def test_hospital_edit_is_never_overwritten(self):
		name = frappe.db.get_value("Audit Template", {"template_code": "PPE"}, "name")
		doc = frappe.get_doc("Audit Template", name)
		doc.title = "PPE của bệnh viện"
		doc.items[0].question = "Câu hỏi đã sửa"
		doc.save()
		doc.submit()
		seed.ensure_seed()
		after = frappe.get_doc("Audit Template", name)
		self.assertEqual(
			(after.title, after.items[0].question, after.docstatus),
			("PPE của bệnh viện", "Câu hỏi đã sửa", 1),
		)
		self.assertEqual(len([row for row in seeded() if row.template_code == "PPE"]), 1)

	def test_bundles_have_a_critical_item(self):
		for code in ("VAP", "CLABSI", "CAUTI", "SSI"):
			doc = frappe.get_doc("Audit Template", {"template_code": code})
			self.assertTrue(any(row.is_critical for row in doc.items), code)

	def test_hygiene_template_moments_come_from_its_items(self):
		name = frappe.db.get_value("Audit Template", {"template_code": "VST"}, "name")
		self.assertEqual(hand_hygiene.moments(name), ["1", "2", "3", "4", "5"])
		self.assertEqual(frappe.db.get_value("Audit Template", name, "min_sample"), 30)

	def test_text_is_stored_in_vietnamese_from_the_translation_file(self):
		missing = [text for text in seed.source_texts() if frappe._(text, "vi") == text]
		# "TT 16/2018/TT-BYT" giống nhau ở hai ngôn ngữ nên không đổi khi dịch
		self.assertEqual([text for text in missing if text != "TT 16/2018/TT-BYT"], [])
		row = next(row for row in seed.rows() if row["template_code"] == "VST")
		self.assertEqual(row["title"], frappe._("Hand hygiene - 5 moments", "vi"))
		self.assertNotEqual(row["items"][0]["question"], "Before touching a patient")
		self.assertTrue(row["legal_ref"].startswith("QĐ"))

	def test_approved_seed_template_is_usable_for_sessions(self):
		name = frappe.db.get_value("Audit Template", {"template_code": "VST"}, "name")
		frappe.get_doc("Audit Template", name).submit()
		self.assertEqual(templates.active_version("VST"), name)
