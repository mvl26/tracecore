"""Ngưỡng môi trường có phiên bản (FEAT-070; FR-M15-03; BRU-ENV-002; NFR-MAINT-04; A-148 b)."""

import frappe

from tracecore.environmental_hygiene import limits, seed
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.utils import IsolatedTestCase, bru


class TestLimitVersions(IsolatedTestCase):
	def test_named_by_code_and_version(self):
		first = ef.make_limit("t-pm-kk")
		self.assertEqual(first.name, "NG-T-PM-KK-V1")
		second = limits.new_version(first.name)
		self.assertEqual((second.name, second.docstatus, second.version_no), ("NG-T-PM-KK-V2", 0, 2))

	def test_one_draft_per_code(self):
		ef.make_limit("T-NUOC", submit=False)
		with self.assertRaises(frappe.ValidationError):
			ef.make_limit("T-NUOC", submit=False)

	def test_approved_version_is_locked(self):
		doc = ef.make_limit("T-KHOA")
		doc.limit_value = 99
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	def test_lower_limit_cannot_exceed_upper_limit(self):
		with self.assertRaises(frappe.ValidationError):
			ef.make_limit("T-CLO", value=1, min_value=2, submit=False)

	@bru("BRU-ENV-002")
	def test_active_version_is_the_one_in_effect_on_the_date(self):
		first = ef.make_limit("T-BM", value=5, effective_from="2026-01-01")
		draft = limits.new_version(first.name)
		draft.limit_value = 3
		draft.effective_from = "2026-11-01"
		draft.save()
		draft.submit()
		self.assertEqual(limits.active_limit("T-BM", "2026-10-31"), first.name)
		self.assertEqual(limits.active_limit("T-BM", "2026-11-01"), draft.name)
		self.assertIsNone(limits.active_limit("T-BM", "2025-12-31"))
		self.assertEqual(frappe.db.get_value("Environmental Limit", first.name, "superseded_by"), draft.name)

	def test_evaluate_upper_and_lower_limits(self):
		upper = frappe._dict(limit_value=10, min_value=0)
		self.assertEqual(limits.evaluate(upper, 10), "Pass")
		self.assertEqual(limits.evaluate(upper, 10.5), "Fail")
		band = frappe._dict(limit_value=1.0, min_value=0.2)
		self.assertEqual(limits.evaluate(band, 0.1), "Fail")
		self.assertEqual(limits.evaluate(band, 0.5), "Pass")


class TestLimitSeed(IsolatedTestCase):
	def test_seed_is_draft_and_migrate_keeps_hospital_edits(self):
		"""NFR-MAINT-04: bộ khởi tạo ở Nháp; chạy lại không ghi đè bản bệnh viện đã sửa, không tạo bản trùng."""
		seed.ensure_seed()
		code = seed.LIMITS[0]["limit_code"]
		name = frappe.db.get_value("Environmental Limit", {"limit_code": code}, "name")
		doc = frappe.get_doc("Environmental Limit", name)
		self.assertEqual(doc.docstatus, 0)
		doc.limit_value = 42
		doc.save()
		seed.ensure_seed()
		self.assertEqual(frappe.db.count("Environmental Limit", {"limit_code": code}), 1)
		self.assertEqual(frappe.db.get_value("Environmental Limit", name, "limit_value"), 42)

	def test_seed_risk_levels_once(self):
		seed.ensure_seed()
		frappe.db.set_value(
			"Environment Risk Level", seed.RISK_LEVELS[0]["risk_name"], "min_audits_per_month", 9
		)
		seed.ensure_seed()
		self.assertEqual(
			frappe.db.get_value(
				"Environment Risk Level", seed.RISK_LEVELS[0]["risk_name"], "min_audits_per_month"
			),
			9,
		)
		self.assertTrue(any(row["is_high_risk"] for row in seed.RISK_LEVELS))

	def test_seed_text_has_vietnamese_translation(self):
		frappe.translate.clear_cache()
		missing = [text for text in seed.source_texts() if frappe._(text, "vi") == text]
		# "ATP" và căn cứ TT 16/2018 giống nhau ở hai ngôn ngữ
		self.assertEqual(
			[text for text in missing if text != "ATP" and not text.startswith("TT 16/2018")], []
		)
		self.assertEqual(seed.limit_rows()[0]["legal_ref"], frappe._(seed.DRAFT_REF, "vi"))

	def test_seed_infrastructure_and_food_templates_are_draft(self):
		seed.ensure_seed()
		rows = frappe.get_all(
			"Audit Template",
			filters={"template_code": ["in", list(seed.TEMPLATES)]},
			fields=["template_code", "docstatus", "audit_type", "infra_category", "inspection_interval_days"],
		)
		by_code = {row.template_code: row for row in rows}
		self.assertEqual(set(by_code), set(seed.TEMPLATES))
		self.assertEqual({row.docstatus for row in rows}, {0})
		self.assertEqual(
			(by_code["INFRA-VENT"].audit_type, by_code["INFRA-VENT"].infra_category),
			("Infrastructure", "Ventilation"),
		)
		self.assertEqual(by_code["ATTP"].audit_type, "Food Safety")
