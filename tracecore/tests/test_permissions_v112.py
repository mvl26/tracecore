"""Ma trận quyền mở rộng v1.12 (FEAT-056, A-113 a, NFR-SEC-09, F-22; plan D3)."""

from frappe.tests.utils import FrappeTestCase

from tracecore.setup.permissions import ROLE_CODES, ROLE_NAMES, load_permission_matrix

NEW_ROLES = ("R11", "R12", "R13")
V112_ROWS = {
	# code: (doctype, {role: symbols}) — vai trò không ghi = không quyền
	# FEAT-057 A-132: R01 RW (FR-M11-01.4 — R01 nhập khoa KSNK và giám sát viên)
	"DT-ICSET": ("IC Program Settings", {"R01": "RW", "R10": "RW", "R11": "R", "R13": "R"}),
	"DT-ICIND": ("IC Indicator", {"R01": "RW", "R10": "RW", "R11": "R", "R12": "R", "R13": "R"}),
	"DT-ICVAL": ("IC Indicator Value", {"R01": "R", "R10": "R", "R11": "R", "R12": "R", "R13": "R"}),
	"DT-IMPMAP": ("Import Mapping Profile", {"R01": "R", "R10": "RW", "R11": "RW"}),
	# FEAT-057 (plan D5, FR-M11-01.4)
	"DT-ICCOM": ("IC Committee", {"R01": "RWSA", "R10": "R", "R11": "R", "R13": "R"}),
	"DT-ICNET": (
		"IC Network Member",
		{"R01": "RW", "R02": "RW", "R10": "R", "R11": "R", "R12": "R", "R13": "R"},
	),
}
# FEAT-067 (A-136, FR-M14-01.3): R13 không đọc chủng có mã người bệnh (ADR-010); Import Batch thêm R11 đọc
V112_ROWS.update(
	{
		"DT-ORG": ("Organism", {"R01": "RW", "R10": "RW", "R11": "R", "R13": "R"}),
		"DT-MICISO": ("Microbiology Isolate", {"R01": "R", "R11": "RW"}),
		"DT-MDRO": ("MDRO Rule", {"R01": "RWS", "R11": "R", "R13": "R"}),
		"DT-IMPBATCH": ("Import Batch", {"R02": "R", "R10": "R", "R11": "R"}),
	}
)


class TestPermissionMatrixV112(FrappeTestCase):
	def test_thirteen_roles(self):
		self.assertEqual(ROLE_CODES, tuple(f"R{n:02d}" for n in range(1, 14)))
		self.assertEqual(ROLE_NAMES["R12"], "TC R12")

	def test_new_doctype_rows_match_plan_d3(self):
		rows = {row.code: row for row in load_permission_matrix()}
		for code, (doctype, grants) in V112_ROWS.items():
			row = rows[code]
			self.assertEqual(row.doctype, doctype)
			for role in ROLE_CODES:
				self.assertEqual(row.permissions[role], grants.get(role, ""), msg=f"{doctype} / {role}")

	def test_indicator_value_written_by_system_only(self):
		row = {r.code: r for r in load_permission_matrix()}["DT-ICVAL"]
		for role in ROLE_CODES:
			self.assertNotIn("W", row.permissions[role], msg=role)

	def test_new_roles_have_no_rights_on_existing_doctypes(self):
		"""R11-R13 không được quyền nào trên 53 DocType có từ trước v1.12 (chỉ thêm, không đổi quyền cũ)."""
		for row in load_permission_matrix():
			if row.code in V112_ROWS:
				continue
			for role in NEW_ROLES:
				self.assertEqual(row.permissions[role], "", msg=f"{row.doctype} / {role}")
