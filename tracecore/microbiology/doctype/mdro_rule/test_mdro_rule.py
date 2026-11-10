"""MDRO Rule có phiên bản, R01 duyệt (FEAT-067 AC-7, AC-8, AC-14; BRU-MDR-001; NFR-MAINT-04; A-136 Q1, Q3)."""

import frappe

from tracecore.microbiology import rules
from tracecore.microbiology.tests.factories import make_organism, make_rule
from tracecore.tests.utils import IsolatedTestCase, assert_permission_matrix, bru


def duplicate(doc):
	"""Như nút Duplicate của Desk: bản sao Nháp của phiên bản đã duyệt."""
	copy = frappe.copy_doc(doc)
	for row in [copy, *copy.get_all_children()]:
		row.docstatus = 0
	copy.amended_from = None
	return copy


class TestMDRORule(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		make_organism()
		make_organism("sau", "Staphylococcus aureus", "Staphylococcus")

	def test_permission_matrix(self):
		assert_permission_matrix(self, "MDRO Rule")

	@bru("BRU-MDR-001")
	def test_versions_are_named_and_one_draft_per_code(self):
		first = make_rule("T-VER")
		self.assertEqual(first.name, "MDR-T-VER-V1")
		second = duplicate(first)
		second.insert(ignore_permissions=True)
		self.assertEqual(second.name, "MDR-T-VER-V2")
		with self.assertRaises(frappe.ValidationError):
			duplicate(first).insert(ignore_permissions=True)
		second.submit()
		self.assertEqual(frappe.db.get_value("MDRO Rule", first.name, "superseded_by"), second.name)

	@bru("BRU-MDR-001")
	def test_approved_version_is_locked(self):
		rule = make_rule("T-LOCK")
		rule.reload()
		rule.label = "Other"
		with self.assertRaises(frappe.ValidationError):
			rule.save(ignore_permissions=True)
		rule.reload()
		rule.criteria[0].antibiotic = "ETP"
		with self.assertRaises(frappe.ValidationError):
			rule.save(ignore_permissions=True)

	def test_rule_code_is_fixed_and_amend_is_blocked(self):
		draft = make_rule("T-FIX", submit=False)
		draft.rule_code = "T-OTHER"
		with self.assertRaises(frappe.ValidationError):
			draft.save(ignore_permissions=True)
		amended = duplicate(make_rule("T-AMD"))
		amended.amended_from = "MDR-T-AMD-V1"
		with self.assertRaises(frappe.ValidationError):
			amended.insert(ignore_permissions=True)

	def test_rule_needs_organisms_criteria_and_classes(self):
		with self.assertRaises(frappe.ValidationError):
			make_rule("T-NOORG", organisms=(), submit=False)
		with self.assertRaises(frappe.ValidationError):
			make_rule("T-NOABX", criteria=(), submit=False)
		with self.assertRaises(frappe.ValidationError):
			make_rule("T-CLS", condition=rules.CLASSES, min_classes=3, submit=False)
		with self.assertRaises(frappe.ValidationError):
			make_rule("T-ROLE", alert_roles="No Such Role", submit=False)
		with self.assertRaises(frappe.ValidationError):
			make_rule("bad code!", submit=False)

	def test_conditions_any_all_and_classes(self):
		any_rule = make_rule("T-ANY", submit=False)
		all_rule = make_rule("T-ALL", condition=rules.ALL, submit=False)
		classes = make_rule(
			"T-MDR",
			criteria=(("MEM", "Carbapenems"), ("CIP", "Fluoroquinolones"), ("GEN", "Aminoglycosides")),
			condition=rules.CLASSES,
			min_classes=2,
			submit=False,
		)
		one = {"MEM": "R", "IPM": "S"}
		self.assertTrue(rules.matches(any_rule, "kpn", "Enterobacterales", one))
		self.assertFalse(rules.matches(all_rule, "kpn", "Enterobacterales", one))
		self.assertTrue(rules.matches(all_rule, "kpn", "Enterobacterales", {"MEM": "R", "IPM": "R"}))
		self.assertFalse(rules.matches(classes, "kpn", "Enterobacterales", {"MEM": "R", "CIP": "I"}))
		self.assertTrue(rules.matches(classes, "kpn", "Enterobacterales", {"MEM": "R", "CIP": "R"}))
		self.assertFalse(rules.matches(any_rule, "sau", "Staphylococcus", one))

	def test_intermediate_counts_only_when_configured(self):
		strict = make_rule("T-STRICT", submit=False)
		loose = make_rule("T-LOOSE", count_intermediate=1, submit=False)
		self.assertFalse(rules.matches(strict, "kpn", "Enterobacterales", {"MEM": "I"}))
		self.assertTrue(rules.matches(loose, "kpn", "Enterobacterales", {"MEM": "I"}))

	@bru("BRU-MDR-001")
	def test_active_rules_use_latest_approved_version_effective_at_the_date(self):
		v1 = make_rule("T-ACT", effective_from="2026-01-01")
		draft = duplicate(v1)
		draft.effective_from = "2026-07-01"
		draft.insert(ignore_permissions=True)
		self.assertIn(v1.name, [rule.name for rule in rules.active_rules("2026-08-01")])
		draft.submit()
		self.assertIn(v1.name, [rule.name for rule in rules.active_rules("2026-06-30")])
		self.assertIn(draft.name, [rule.name for rule in rules.active_rules("2026-08-01")])
		self.assertNotIn(v1.name, [rule.name for rule in rules.active_rules("2026-08-01")])
