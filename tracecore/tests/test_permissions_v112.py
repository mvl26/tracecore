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
# FEAT-058 (plan D6, A-133; FR-M11-01.4): R13 ghi sổ kế hoạch năm, R01 lập và lập bản sửa đổi
V112_ROWS.update(
	{
		"DT-ICPLAN": ("IC Annual Plan", {"R01": "RWA", "R10": "R", "R11": "R", "R13": "RS"}),
		"DT-ICDOC": (
			"IC Procedure Document",
			{"R01": "RW", "R10": "R", "R11": "R", "R12": "R", "R13": "R"},
		),
		"DT-ICMEET": ("IC Committee Meeting", {"R01": "RWSA", "R10": "R", "R11": "R", "R13": "R"}),
	}
)
# FEAT-060 plan D1 (engine phiếu giám sát M12)
V112_ROWS.update(
	{
		"DT-AUDTPL": (
			"Audit Template",
			{"R01": "RWS", "R02": "R", "R08": "R", "R10": "R", "R11": "RW", "R12": "R", "R13": "R"},
		),
		"DT-AUDSCH": ("Audit Schedule", {"R01": "RW", "R02": "RW", "R10": "R", "R11": "R", "R13": "R"}),
		"DT-AUDSES": ("Audit Session", {"R01": "RWSA", "R02": "R", "R08": "RWS", "R11": "RWS", "R12": "RWS"}),
	}
)
# FEAT-067 (A-136, FR-M14-01.3): R13 không đọc chủng có mã người bệnh (ADR-010); Import Batch thêm R11 đọc
V112_ROWS.update(
	{
		"DT-ORG": ("Organism", {"R01": "RW", "R10": "RW", "R11": "R", "R13": "R"}),
		"DT-MICISO": ("Microbiology Isolate", {"R01": "R", "R11": "RW"}),
		"DT-MDRO": ("MDRO Rule", {"R01": "RWS", "R11": "R", "R13": "R"}),
		"DT-IMPBATCH": ("Import Batch", {"R02": "R", "R10": "R", "R11": "R"}),
	}
)
# FEAT-059 (plan D6, A-135): sinh viên thực tập
V112_ROWS.update(
	{
		"DT-ICTRN": (
			"Trainee Induction",
			{"R01": "RW", "R02": "RW", "R10": "R", "R11": "R", "R12": "R", "R13": "R"},
		),
	}
)


# FEAT-071 (A-137 j, FR-M16-05/05.1/05.2, BRU-OCC-003): hồ sơ phơi nhiễm chỉ R01, R11; R02 ghi tiêm chủng
V112_ROWS.update(
	{
		"DT-OCCEXP": ("Occupational Exposure", {"R01": "RW", "R11": "RW"}),
		"DT-EXPTPL": ("Exposure Follow-up Template", {"R01": "RW", "R11": "R"}),
		"DT-IMMREQ": ("Immunization Requirement", {"R01": "RW", "R02": "R", "R11": "R"}),
		"DT-STFIMM": ("Staff Immunization", {"R01": "RW", "R02": "RW", "R11": "R"}),
	}
)
# FEAT-062 (A-141 g, NFR-SEC-09): mẫu số ngày, đợt thiết bị — R13 không đọc đợt (có mã BN)
V112_ROWS.update(
	{
		"DT-WDCEN": ("Ward Daily Census", {"R01": "RW", "R08": "RW", "R10": "R", "R11": "RW", "R12": "RW"}),
		"DT-DEVEP": ("Device Episode", {"R01": "RW", "R08": "RW", "R11": "RW", "R12": "RW"}),
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
