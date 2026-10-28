"""Cost Rate Version: DocType, naming, không xóa, quyền (FEAT-045; FR-M7-03, UC-28; architecture A-48 D2, D5)."""

import frappe

from tracecore.tests.factories import make_cost_rate_version, make_user
from tracecore.tests.utils import IsolatedTestCase

test_ignore = ["Item", "User"]

DOCTYPE = "Cost Rate Version"


class TestCostRateVersionDoc(IsolatedTestCase):
	def test_named_dg(self):  # A-48 D5
		self.assertRegex(make_cost_rate_version().name, r"^DG-\d{4}-\d{5}$")

	def test_is_submittable_and_tracks_changes(self):
		meta = frappe.get_meta(DOCTYPE)
		self.assertEqual((meta.is_submittable, meta.track_changes), (1, 1))

	def test_version_cannot_be_deleted(self):
		doc = make_cost_rate_version()
		with self.assertRaises(frappe.ValidationError):
			doc.delete()
		self.assertTrue(frappe.db.exists(DOCTYPE, doc.name))

	def test_permissions_follow_a48(self):  # A-48 D5: R01 duyệt, R09 lập Nháp
		expected = {
			"TC R01": {"read": 1, "write": 1, "create": 1, "submit": 1, "cancel": 1},
			"TC R09": {"read": 1, "write": 1, "create": 1, "submit": 0, "cancel": 0},
			"TC R02": {"read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R10": {"read": 1, "write": 0, "create": 0, "submit": 0, "cancel": 0},
			"TC R03": {"read": 0, "write": 0, "create": 0, "submit": 0, "cancel": 0},
		}
		for role, flags in expected.items():
			user = make_user(f"crv-{role.split()[-1].lower()}@example.com", [role])
			for ptype, allowed in flags.items():
				self.assertEqual(
					int(bool(frappe.has_permission(DOCTYPE, ptype, user=user))),
					allowed,
					msg=f"{role} {ptype}",
				)
