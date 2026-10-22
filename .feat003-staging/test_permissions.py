import json
from pathlib import Path

from frappe.tests.utils import FrappeTestCase

from tracecore.setup.permissions import (
	ROLE_CODES,
	load_permission_matrix,
	build_custom_docperms,
	permission_flags,
)


MATRIX_PATH = Path(__file__).parents[1] / "fixtures" / "permission_matrix.csv"


class TestPermissionMatrix(FrappeTestCase):
	def test_matrix_covers_ten_roles_and_forty_baseline_doctypes(self):
		rows = load_permission_matrix(MATRIX_PATH)
		self.assertEqual(tuple(rows.roles), ROLE_CODES)
		self.assertEqual(len(rows), 40)
		self.assertEqual(len({row.code for row in rows}), 40)
		for row in rows:
			self.assertTrue(row.doctype)
			for role in ROLE_CODES:
				self.assertLessEqual(set(row.permissions[role]), set("RWSA"))

	def test_permission_symbols_map_to_frappe_flags_without_delete(self):
		self.assertEqual(permission_flags(""), {})
		self.assertEqual(permission_flags("R"), {"read": 1, "report": 1, "print": 1, "export": 1})
		self.assertEqual(
			permission_flags("RWSA"),
			{
				"read": 1,
				"report": 1,
				"print": 1,
				"export": 1,
				"write": 1,
				"create": 1,
				"submit": 1,
				"cancel": 1,
				"amend": 1,
			},
		)
		self.assertNotIn("delete", permission_flags("RWSA"))

	def test_feature_amendments_override_ba_baseline(self):
		rows = {row.code: row for row in load_permission_matrix(MATRIX_PATH)}
		zone = rows["DT-ZONE"]
		self.assertEqual(zone.permissions["R10"], "RW")
		self.assertEqual(zone.permissions["R01"], "R")
		self.assertEqual(zone.permissions["R02"], "R")
		self.assertEqual(zone.permissions["R09"], "R")

		for code in ("DT-EQUIP", "DT-PROGRAM"):
			row = rows[code]
			self.assertEqual(row.permissions["R10"], "RW")
			for role in ("R01", "R02", "R03", "R04", "R05", "R06", "R09"):
				self.assertEqual(row.permissions[role], "R")

	def test_audit_is_immutable_and_not_visible_to_r09(self):
		audit = {row.code: row for row in load_permission_matrix(MATRIX_PATH)}["DT-AUDIT"]
		self.assertEqual(audit.permissions["R01"], "R")
		self.assertEqual(audit.permissions["R02"], "R")
		self.assertEqual(audit.permissions["R09"], "")
		self.assertEqual(audit.permissions["R10"], "R")

	def test_custom_docperm_fixture_matches_generator(self):
		fixture_path = MATRIX_PATH.with_name("custom_docperm.json")
		fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
		existing = {record["parent"] for record in fixture}
		self.assertEqual(fixture, build_custom_docperms(existing))
		self.assertTrue(all(record.get("name") for record in fixture))
		self.assertEqual(len({record["name"] for record in fixture}), len(fixture))
		self.assertTrue(all(not record.get("delete") for record in fixture))

	def test_privileged_roles_require_two_factor_auth(self):
		roles_path = MATRIX_PATH.with_name("role.json")
		roles = {row["role_name"]: row for row in json.loads(roles_path.read_text(encoding="utf-8"))}
		for code in ROLE_CODES:
			expected = 1 if code in {"R01", "R02", "R09", "R10"} else 0
			self.assertEqual(roles[f"TC {code}"]["two_factor_auth"], expected)
