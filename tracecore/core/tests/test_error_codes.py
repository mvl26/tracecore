"""Khung mã lỗi (FEAT-052, A-71): danh mục, cấu hình theo viện, Nhật ký lỗi, gán mã vào Block."""

import re
from pathlib import Path

import frappe
from frappe.utils import now_datetime

from tracecore.core import error_codes
from tracecore.core.client_time import to_system_time
from tracecore.core.errors import HTTP_STATUS, Block
from tracecore.setup.error_codes import DEFAULT_CODES, ensure_error_codes
from tracecore.tests.utils import IsolatedTestCase

REQUIRED = (
	"HC-001",
	"HC-002",
	"HC-003",
	"NS-001",
	"NS-002",
	"NS-003",
	"TB-001",
	"TB-002",
	"TB-003",
	"TB-004",
	"CT-001",
	"DC-001",
	"DC-002",
	"QT-001",
)
CHANGEABLE = ("TB-002", "DC-001", "HC-002", "NS-002")


class ErrorCodeCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		ensure_error_codes()
		frappe.clear_document_cache("TraceCore Settings", "TraceCore Settings")
		self.addCleanup(error_codes.clear_cache)
		error_codes.pop_warnings()

	def set_rule(self, code, **values):
		settings = frappe.get_doc("TraceCore Settings")
		row = next(row for row in settings.error_rules if row.error_code == code)
		row.update(values)
		settings.save(ignore_permissions=True)


class TestCatalog(ErrorCodeCase):
	def test_seed_has_all_required_codes(self):
		for code in REQUIRED:
			self.assertTrue(frappe.db.exists("TraceCore Error Code", code), code)

	def test_every_code_has_handbook_fields(self):
		for code in frappe.get_all("TraceCore Error Code", pluck="name"):
			doc = frappe.get_doc("TraceCore Error Code", code)
			for field in ("error_name", "description", "trigger_condition", "system_action", "guide"):
				self.assertTrue(doc.get(field), f"{code}.{field}")
			self.assertTrue(doc.stations, code)

	def test_code_format_rejected(self):
		for code in ("XX-001", "HC-1", "hc-001", "HC-0011"):
			doc = frappe.get_doc(
				{
					"doctype": "TraceCore Error Code",
					"code": code,
					"error_name": "x",
					"default_severity": "Block",
				}
			)
			with self.assertRaises(frappe.ValidationError, msg=code):
				doc.insert(ignore_permissions=True)

	def test_station_key_must_exist(self):
		doc = frappe.get_doc("TraceCore Error Code", "QT-001")
		doc.append("stations", {"station_key": "NOT_A_FUNCTION"})
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)

	def test_seed_keeps_hospital_edits(self):
		frappe.db.set_value("TraceCore Error Code", "QT-001", "guide", "<p>hospital</p>")
		ensure_error_codes()
		self.assertEqual(frappe.db.get_value("TraceCore Error Code", "QT-001", "guide"), "<p>hospital</p>")

	def test_seed_adds_missing_code(self):
		frappe.delete_doc("TraceCore Error Code", "QT-001", force=True, ignore_permissions=True)
		ensure_error_codes()
		self.assertTrue(frappe.db.exists("TraceCore Error Code", "QT-001"))

	def test_delete_forbidden_for_r10(self):
		perms = frappe.get_meta("TraceCore Error Code").permissions
		self.assertFalse([row.role for row in perms if row.delete])


class TestRules(ErrorCodeCase):
	def test_only_agreed_codes_are_changeable(self):
		changeable = {row["code"] for row in DEFAULT_CODES if not row.get("severity_locked")}
		self.assertEqual(changeable, set(CHANGEABLE))

	def test_locked_code_rejects_severity_change(self):
		with self.assertRaises(frappe.ValidationError):
			self.set_rule("CT-001", severity="Warning")

	def test_locked_code_rejects_disable(self):
		with self.assertRaises(frappe.ValidationError):
			self.set_rule("DC-002", enabled=0)

	def test_change_effective_without_restart(self):
		self.assertEqual(error_codes.rule_of("TB-002")["severity"], "Block")
		self.set_rule("TB-002", severity="Warning")
		self.assertEqual(error_codes.rule_of("TB-002")["severity"], "Warning")

	def test_invalid_role_rejected(self):
		with self.assertRaises(frappe.ValidationError):
			self.set_rule("NS-001", approver_roles="Not A Role")

	def test_default_approvers_are_r01_r02(self):
		self.assertEqual(set(error_codes.rule_of("NS-001")["approver_roles"]), {"TC R01", "TC R02"})

	def test_warn_days_default(self):
		self.assertEqual(error_codes.rule_of("HC-002")["warn_days"], 30)
		self.assertEqual(error_codes.rule_of("NS-002")["warn_days"], 30)

	def test_unknown_code_has_no_rule(self):
		self.assertIsNone(error_codes.rule_of("ZZ-999"))


class TestErrorLog(ErrorCodeCase):
	def test_record_stores_fields(self):
		name = error_codes.record("TB-003", "Equipment", "TB-X", station=None)
		row = frappe.get_doc("TraceCore Error Log", name)
		self.assertEqual(
			(row.error_code, row.object_type, row.object_name, row.status),
			("TB-003", "Equipment", "TB-X", "Open"),
		)
		self.assertEqual(row.user, frappe.session.user)
		self.assertTrue(row.occurred_at)

	def test_record_uses_client_ts(self):
		moment = now_datetime().replace(microsecond=0)
		name = error_codes.record("TB-003", "Equipment", "TB-X", client_ts=moment)
		self.assertEqual(
			frappe.db.get_value("TraceCore Error Log", name, "client_ts"), to_system_time(moment)
		)

	def test_mark_resolved_closes_open_rows(self):
		first = error_codes.record("TB-003", "Equipment", "TB-X")
		other = error_codes.record("TB-003", "Equipment", "TB-Y")
		self.assertEqual(error_codes.mark_resolved("TB-003", "Equipment", "TB-X"), 1)
		self.assertEqual(frappe.db.get_value("TraceCore Error Log", first, "status"), "Resolved")
		self.assertEqual(frappe.db.get_value("TraceCore Error Log", other, "status"), "Open")

	def test_delete_forbidden(self):
		name = error_codes.record("TB-003", "Equipment", "TB-X")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("TraceCore Error Log", name, force=True, ignore_permissions=True)

	def test_block_body_writes_log(self):
		from tracecore.v1._common import _block_body

		before = frappe.db.count("TraceCore Error Log", {"error_code": "DC-002"})
		_block_body(Block("PACK_EXPIRED", "t", "r", "a", object_type="Pack", object_name="P-1"))
		self.assertEqual(frappe.db.count("TraceCore Error Log", {"error_code": "DC-002"}), before + 1)

	def test_reject_block_writes_log_once(self):
		from tracecore.v1._common import run_at_step

		before = frappe.db.count("TraceCore Error Log", {"error_code": "QT-001"})
		run_at_step("T1", "NOT_A_STATION", None, lambda: None)
		self.assertEqual(frappe.db.count("TraceCore Error Log", {"error_code": "QT-001"}), before + 1)

	def test_input_error_not_logged(self):
		from tracecore.v1._common import _block_body

		before = frappe.db.count("TraceCore Error Log")
		_block_body(Block("SCAN_INVALID", "t", "r", "a"))
		self.assertEqual(frappe.db.count("TraceCore Error Log"), before)

	def test_log_failure_does_not_hide_block(self):
		from unittest.mock import patch

		from tracecore.v1._common import _block_body

		with patch.object(error_codes, "record", side_effect=RuntimeError("db")):
			body = _block_body(Block("PACK_EXPIRED", "t", "r", "a"))
		self.assertEqual(body["error"]["error_code"], "DC-002")

	def test_disabled_code_not_logged(self):
		from tracecore.v1._common import _block_body

		self.set_rule("TB-002", enabled=0)
		before = frappe.db.count("TraceCore Error Log", {"error_code": "TB-002"})
		_block_body(Block("EQUIPMENT_CALIBRATION_EXPIRED", "t", "r", "a"))
		self.assertEqual(frappe.db.count("TraceCore Error Log", {"error_code": "TB-002"}), before)


class TestBlockMapping(ErrorCodeCase):
	def test_as_dict_keeps_old_keys(self):
		data = Block("PACK_EXPIRED", "T", "R", "A", items=["x"]).as_dict()
		self.assertEqual(data["code"], "PACK_EXPIRED")
		self.assertEqual((data["title"], data["reason"], data["action"]), ("T", "R", "A"))
		self.assertEqual(data["items"], ["x"])

	def test_mapped_block_has_error_code(self):
		data = Block("PACK_EXPIRED", "T", "R", "A", object_name="P-1").as_dict()
		self.assertEqual(data["error_code"], "DC-002")
		self.assertTrue(data["error_name"])
		self.assertEqual(data["object_label"], "P-1")
		self.assertTrue(data["has_guide"])

	def test_unmapped_block_has_no_error_code(self):
		self.assertNotIn("error_code", Block("SCAN_INVALID", "T", "R", "A").as_dict())

	def test_daily_test_block_is_tb001(self):
		data = Block("DAILY_TEST_REQUIRED", "T", "R", "A", object_name="M-1").as_dict()
		self.assertEqual((data["error_code"], data["object_label"]), ("TB-001", "M-1"))

	def test_explicit_error_code_wins(self):
		data = Block("EQUIPMENT_INSPECTION_EXPIRED", "T", "R", "A", error_code="TB-004").as_dict()
		self.assertEqual(data["error_code"], "TB-004")

	def test_every_block_code_mapped_or_excluded(self):
		"""Thêm mã `Block` mới phải quyết định gán mã hay loại trừ (nghiệm thu: mọi kiểm tra đã gán mã)."""
		mapped = {code for row in DEFAULT_CODES for code in row.get("block_codes", ())}
		self.assertFalse(mapped & error_codes.UNMAPPED_BLOCK_CODES)
		used = set(HTTP_STATUS) | _codes_in_source()
		self.assertEqual(sorted(used - mapped - error_codes.UNMAPPED_BLOCK_CODES), [])

	def test_ct001_only_when_indicator_failed(self):
		cases = {
			("Quarantine", None): "CT-001",
			("Recalled", None): "CT-001",
			("Void", "Load Failed"): "CT-001",
			("Void", "Expired"): None,
			("Issued", None): None,
		}
		for (status, reason), expected in cases.items():
			pack = frappe._dict(status=status, void_reason=reason)
			self.assertEqual(error_codes.pack_error_code(pack), expected, status)

	def test_pressure_inspection_is_tb004_other_tb002(self):
		from unittest.mock import patch

		from tracecore.equipment import daily_test

		row = dict(status="Ready", inspection_due="2020-01-01", calibration_due=None, unlock_until=None)
		for equipment_type, expected in (("Steam Sterilizer", "TB-004"), ("Washer-Disinfector", "TB-002")):
			with (
				patch.object(
					daily_test, "_machine_row", return_value=frappe._dict(row, equipment_type=equipment_type)
				),
				patch.object(daily_test.chemical_lots, "chemical_block", return_value=None),
			):
				block = daily_test.equipment_block("M-1")
			self.assertEqual(error_codes.error_code_of(block.code, block.error_code), expected)
			self.assertEqual(block.object_name, "M-1")


class TestGuideAndReports(ErrorCodeCase):
	def test_guide_html_sanitized(self):
		from tracecore.v1.error_code import guide

		frappe.db.set_value("TraceCore Error Code", "QT-001", "guide", "<p>ok</p><script>alert(1)</script>")
		html = guide("QT-001")["guide_html"]
		self.assertIn("ok", html)
		self.assertNotIn("<script", html)

	def test_unknown_code_rejected(self):
		from tracecore.v1.error_code import guide

		self.assertEqual(guide("ZZ-999")["error"]["code"], "ERROR_CODE_NOT_FOUND")
		self.assertFalse(guide(None)["ok"])

	def _catalog(self, **filters):
		from tracecore.admin_reports.report.error_code_catalog.error_code_catalog import execute

		return {row["code"]: row for row in execute(filters)[1]}

	def test_catalog_filter_by_station(self):
		rows = self._catalog(station="USE")
		self.assertIn("DC-002", rows)
		self.assertNotIn("TB-004", rows)

	def test_catalog_filter_by_code(self):
		self.assertEqual(list(self._catalog(code="TB-004")), ["TB-004"])

	def test_catalog_includes_guide(self):
		self.assertIn("<ol>", self._catalog(code="TB-004")["TB-004"]["guide"])

	def test_catalog_print_template_has_guide(self):
		path = (
			Path(frappe.get_app_path("tracecore"))
			/ "admin_reports/report/error_code_catalog/error_code_catalog.html"
		)
		self.assertIn("row.guide", path.read_text(encoding="utf8"))

	def test_statistics_group_by_code_station(self):
		from tracecore.admin_reports.report.error_log_statistics.error_log_statistics import execute

		error_codes.record("TB-003", "Equipment", "M")
		error_codes.mark_resolved("TB-003", "Equipment", "M")
		error_codes.record("TB-003", "Equipment", "M")
		today = frappe.utils.today()
		rows = execute({"error_code": "TB-003", "from_date": today, "to_date": today})[1]
		self.assertGreaterEqual(rows[0]["total"], 2)
		self.assertGreaterEqual(rows[0]["resolved"], 1)
		self.assertGreaterEqual(rows[0]["open"], 1)

	def test_statistics_date_filter(self):
		from tracecore.admin_reports.report.error_log_statistics.error_log_statistics import execute

		error_codes.record("TB-003", "Equipment", "M")
		rows = execute({"error_code": "TB-003", "from_date": "2000-01-01", "to_date": "2000-01-02"})[1]
		self.assertEqual(rows, [])

	def test_statistics_only_managers_can_read(self):
		roles = {row.role for row in frappe.get_doc("Report", "Error Log Statistics").roles}
		self.assertEqual(roles, {"System Manager", "TC R01", "TC R02", "TC R10"})

	def test_every_station_screen_uses_shared_title(self):
		root = Path(frappe.get_app_path("tracecore")) / "public/js"
		for path in root.glob("station_*.js"):
			self.assertNotIn("${esc(notice.title)}</p>", path.read_text(encoding="utf8"), path.name)


def _codes_in_source():
	root = Path(frappe.get_app_path("tracecore"))
	pattern = re.compile(r"(?:\bBlock|_blocked|_block|rejection|reject)\(\s*\"([A-Z][A-Z0-9_]+)\"")
	found = set()
	for path in root.rglob("*.py"):
		if "tests" in path.parts or path.name.startswith("test_"):
			continue
		found |= set(pattern.findall(path.read_text(encoding="utf8")))
	return found
