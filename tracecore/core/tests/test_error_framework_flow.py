"""Hành vi khung mã lỗi trên nghiệp vụ thật (FEAT-052, A-71): mức độ, lô hóa chất theo máy, đăng nhập và cho phép tạm."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_to_date, get_datetime, now_datetime, today

from tracecore.core import error_codes, station_auth
from tracecore.core.errors import Block, BlockedError
from tracecore.core.tests.test_error_codes import ErrorCodeCase
from tracecore.equipment import chemical_lots, daily_test, maintenance
from tracecore.tests.utils import bru


def _block(code="EQUIPMENT_CALIBRATION_EXPIRED"):
	return Block(code, "t", "r", "a", object_type="Equipment", object_name="M-1")


class TestSeverity(ErrorCodeCase):
	def test_block_severity_returns_block(self):
		self.assertIsNotNone(error_codes.check(_block()))

	@bru("BRU-EQP-002")
	def test_warning_returns_none_logs_and_collects(self):
		self.set_rule("TB-002", severity="Warning")
		before = frappe.db.count("TraceCore Error Log", {"error_code": "TB-002"})
		self.assertIsNone(error_codes.check(_block()))
		self.assertEqual(frappe.db.count("TraceCore Error Log", {"error_code": "TB-002"}), before + 1)
		warnings = error_codes.pop_warnings()
		self.assertEqual(warnings[0]["error_code"], "TB-002")
		self.assertEqual(error_codes.pop_warnings(), [])

	def test_disabled_returns_none_without_log(self):
		self.set_rule("TB-002", enabled=0)
		before = frappe.db.count("TraceCore Error Log", {"error_code": "TB-002"})
		self.assertIsNone(error_codes.check(_block()))
		self.assertEqual(frappe.db.count("TraceCore Error Log", {"error_code": "TB-002"}), before)
		self.assertEqual(error_codes.pop_warnings(), [])

	def test_attach_warnings_keeps_ok_true(self):
		self.set_rule("TB-002", severity="Warning")
		error_codes.check(_block())
		result = error_codes.attach_warnings({"ok": True})
		self.assertTrue(result["ok"])
		self.assertEqual(result["warnings"][0]["error_code"], "TB-002")

	def _machine(self, equipment_type, **fields):
		row = dict(status="Ready", inspection_due=None, calibration_due=None, unlock_until=None)
		row.update(fields, equipment_type=equipment_type)
		return frappe._dict(row)

	def _equipment_block(self, row):
		with (
			patch.object(daily_test, "_machine_row", return_value=row),
			patch.object(daily_test, "missing_tests", return_value=[]),
			patch.object(daily_test.chemical_lots, "chemical_block", return_value=None),
		):
			return daily_test.equipment_block("M-1")

	@bru("BRU-EQP-002")
	def test_tb002_warning_allows_machine(self):
		self.set_rule("TB-002", severity="Warning")
		row = self._machine("Washer-Disinfector", calibration_due="2020-01-01")
		self.assertIsNone(self._equipment_block(row))

	@bru("BRU-EQP-002")
	def test_tb002_block_stops_machine(self):
		row = self._machine("Washer-Disinfector", calibration_due="2020-01-01")
		self.assertEqual(self._equipment_block(row).code, "EQUIPMENT_CALIBRATION_EXPIRED")

	@bru("BRU-EQP-002")
	def test_pressure_inspection_always_blocked(self):
		self.set_rule("TB-002", severity="Warning")
		row = self._machine("Steam Sterilizer", inspection_due="2020-01-01")
		block = self._equipment_block(row)
		self.assertEqual(block.error_code, "TB-004")

	@bru("BRU-EQP-002")
	def test_unlock_cannot_bypass_tb004(self):
		row = self._machine(
			"Steam Sterilizer", inspection_due="2020-01-01", unlock_until=add_days(now_datetime(), 1)
		)
		self.assertEqual(self._equipment_block(row).error_code, "TB-004")

	def _overdue_rows(self):
		return [
			frappe._dict(
				name="M-1",
				equipment_type="Washer-Disinfector",
				inspection_due=None,
				calibration_due="2020-01-01",
				unlock_until=None,
			),
			frappe._dict(
				name="M-2",
				equipment_type="Steam Sterilizer",
				inspection_due="2020-01-01",
				calibration_due=None,
				unlock_until=None,
			),
		]

	@bru("BRU-EQP-002")
	def test_lock_overdue_skips_when_warning(self):
		self.set_rule("TB-002", severity="Warning")
		with (
			patch.object(maintenance.frappe, "get_all", return_value=self._overdue_rows()),
			patch.object(maintenance, "_save_machine") as save,
			patch.object(maintenance, "_notify"),
			patch.object(maintenance, "_recipients", return_value=[]),
		):
			locked = maintenance.lock_overdue()
		self.assertEqual(locked, ["M-2"])
		self.assertEqual(save.call_count, 1)

	@bru("BRU-EQP-002")
	def test_lock_overdue_locks_when_block(self):
		with (
			patch.object(maintenance.frappe, "get_all", return_value=self._overdue_rows()),
			patch.object(maintenance, "_save_machine"),
			patch.object(maintenance, "_notify"),
			patch.object(maintenance, "_recipients", return_value=[]),
		):
			self.assertEqual(maintenance.lock_overdue(), ["M-1", "M-2"])

	@bru("BRU-EQP-002")
	def test_release_when_downgraded_keeps_pressure_locked(self):
		rows = [
			frappe._dict(name="M-1", equipment_type="Washer-Disinfector", lock_reason="Calibration Expired"),
			frappe._dict(name="M-2", equipment_type="Steam Sterilizer", lock_reason="Inspection Expired"),
		]
		self.set_rule("TB-002", severity="Warning")
		with (
			patch.object(maintenance.frappe, "get_all", return_value=rows),
			patch.object(maintenance, "_save_machine") as save,
		):
			self.assertEqual(maintenance.release_downgraded(), ["M-1"])
		save.assert_called_once_with("M-1", status="Ready", lock_reason=None)


class TestChemicalLots(ErrorCodeCase):
	def setUp(self):
		super().setUp()
		self.type_name = "Washer-Disinfector"
		if not frappe.db.exists("Equipment Type Norm", self.type_name):
			frappe.get_doc({"doctype": "Equipment Type Norm", "equipment_type": self.type_name}).insert(
				ignore_permissions=True
			)
		frappe.db.set_value("Equipment Type Norm", self.type_name, "requires_chemical_lot", 1)

	def _patched_lots(self, lots, expiry):
		return (
			patch.object(chemical_lots, "declared_lots", return_value=lots),
			patch.object(chemical_lots, "_expiry", return_value=get_datetime(expiry).date()),
		)

	@bru("BRU-INV-001")
	def test_no_declared_lot_blocks_when_flagged(self):
		with patch.object(chemical_lots, "declared_lots", return_value=[]):
			block = chemical_lots.chemical_block("M-1", self.type_name)
		self.assertEqual(block.as_dict()["error_code"], "HC-003")
		self.assertEqual(block.object_name, "M-1")

	@bru("BRU-INV-001")
	def test_type_not_flagged_unaffected(self):
		frappe.db.set_value("Equipment Type Norm", self.type_name, "requires_chemical_lot", 0)
		self.assertIsNone(chemical_lots.chemical_block("M-1", self.type_name))

	@bru("BRU-INV-001")
	def test_expired_lot_blocks_with_machine_and_lot(self):
		lots, expiry = self._patched_lots([frappe._dict(item="HC", lot="LOT-1")], "2020-01-01")
		with lots, expiry:
			data = chemical_lots.chemical_block("M-1", self.type_name).as_dict()
		self.assertEqual(data["error_code"], "HC-001")
		self.assertIn("M-1", data["object_label"])
		self.assertIn("LOT-1", data["object_label"])

	@bru("BRU-INV-001")
	def test_unlock_temp_does_not_bypass_hc001(self):
		row = frappe._dict(
			equipment_type=self.type_name,
			status="Ready",
			inspection_due=None,
			calibration_due=None,
			unlock_until=add_days(now_datetime(), 1),
		)
		expired = _block("CHEMICAL_LOT_EXPIRED")
		with (
			patch.object(daily_test, "_machine_row", return_value=row),
			patch.object(daily_test.chemical_lots, "chemical_block", return_value=expired),
		):
			self.assertIs(daily_test.equipment_block("M-1"), expired)

	@bru("BRU-INV-001")
	def test_near_expiry_warns_with_n_days(self):
		soon = add_days(today(), 5)
		lots, expiry = self._patched_lots([frappe._dict(item="HC", lot="LOT-1")], soon)
		with lots, expiry:
			self.assertIsNone(chemical_lots.chemical_block("M-1", self.type_name))
		self.assertEqual(error_codes.pop_warnings()[0]["error_code"], "HC-002")

	def test_far_expiry_no_warning(self):
		lots, expiry = self._patched_lots([frappe._dict(item="HC", lot="LOT-1")], add_days(today(), 200))
		with lots, expiry:
			self.assertIsNone(chemical_lots.chemical_block("M-1", self.type_name))
		self.assertEqual(error_codes.pop_warnings(), [])

	@bru("BRU-INV-001")
	def test_replace_lot_resolves_open_log(self):
		name = error_codes.record("HC-001", "Equipment", "M-1")
		lots, expiry = self._patched_lots([frappe._dict(item="HC", lot="LOT-2")], add_days(today(), 200))
		with lots, expiry:
			self.assertIsNone(chemical_lots.chemical_block("M-1", self.type_name))
		self.assertEqual(frappe.db.get_value("TraceCore Error Log", name, "status"), "Resolved")

	def test_declare_rejects_unknown_lot(self):
		with self.assertRaises(BlockedError) as caught:
			chemical_lots.declare("M-1", "NO-SUCH-LOT")
		self.assertEqual(caught.exception.block.code, "CHEMICAL_LOT_INVALID")

	def test_batch_prefilled_from_machine_lot(self):
		with patch.object(
			chemical_lots, "declared_lots", return_value=[frappe._dict(item="HC", lot="LOT-1")]
		):
			self.assertEqual(chemical_lots.default_rows("M-1", "HC")[0]["lot"], "LOT-1")
			self.assertEqual(chemical_lots.default_rows("M-1", "OTHER"), [])


class TestTemporaryAccess(ErrorCodeCase):
	def setUp(self):
		super().setUp()
		self.log = error_codes.record("NS-001", "Employee", "EMP-X", user="Guest")

	def _grant(self, user="Administrator", hours=4, reason="ca mổ", employee_user=None):
		with patch.object(error_codes.frappe, "get_roles", return_value=["TC R02"]):
			frappe.set_user(user)
			self.addCleanup(frappe.set_user, "Administrator")
			return error_codes.grant_permit(self.log, hours, reason)

	@bru("BRU-HR-002")
	def test_grant_records_approver_and_until(self):
		result = self._grant()
		row = frappe.get_doc("TraceCore Error Log", self.log)
		self.assertEqual(row.status, "Temporarily Allowed")
		self.assertEqual(row.approved_by, "Administrator")
		self.assertEqual(row.approval_reason, "ca mổ")
		self.assertEqual(get_datetime(row.valid_until), get_datetime(result["valid_until"]))

	@bru("BRU-HR-002")
	def test_active_permit_found_until_expiry(self):
		self._grant()
		self.assertIsNotNone(error_codes.active_permit("NS-001", "Employee", "EMP-X"))
		frappe.db.set_value(
			"TraceCore Error Log", self.log, "valid_until", add_to_date(now_datetime(), hours=-1)
		)
		self.assertIsNone(error_codes.active_permit("NS-001", "Employee", "EMP-X"))

	@bru("BRU-HR-002")
	def test_over_24h_rejected(self):
		for hours in (25, 0, "x"):
			with self.assertRaises(BlockedError) as caught:
				self._grant(hours=hours)
			self.assertEqual(caught.exception.block.code, "PERMIT_INVALID")

	@bru("BRU-HR-002")
	def test_reason_required(self):
		with self.assertRaises(BlockedError):
			self._grant(reason="  ")

	@bru("BRU-HR-002")
	def test_role_from_settings_respected(self):
		self.set_rule("NS-001", approver_roles="TC R01")
		with self.assertRaises(BlockedError) as caught:
			self._grant()
		self.assertEqual(caught.exception.block.code, "APPROVER_NOT_ALLOWED")

	@bru("BRU-HR-002")
	def test_self_approval_rejected(self):
		with patch.object(error_codes, "_employee_user", return_value="Administrator"):
			with self.assertRaises(BlockedError) as caught:
				self._grant()
		self.assertEqual(caught.exception.block.code, "SELF_APPROVAL_NOT_ALLOWED")

	@bru("BRU-HR-002")
	def test_permit_only_for_ns001(self):
		self.log = error_codes.record("CT-001", "Pack", "P-1")
		with self.assertRaises(BlockedError) as caught:
			self._grant()
		self.assertEqual(caught.exception.block.code, "PERMIT_INVALID")


class TestStationLogin(ErrorCodeCase):
	def _competency(self, names, missing):
		return (
			patch.object(station_auth, "_active_competencies", return_value=names),
			patch.object(station_auth, "_missing_certificates", return_value=missing),
			patch.object(station_auth, "_audit"),
			patch.object(station_auth, "_expiring_warnings"),
		)

	@bru("BRU-HR-001")
	def test_no_competency_shows_ns003(self):
		a, b, c, d = self._competency([], [])
		with a, b, c, d, self.assertRaises(BlockedError) as caught:
			station_auth._require_competency("EMP-X", "ST-1")
		self.assertEqual(caught.exception.block.as_dict()["error_code"], "NS-003")
		self.assertEqual(caught.exception.block.object_name, "EMP-X")

	@bru("BRU-HR-001")
	def test_expired_cert_shows_ns001_with_cert_type(self):
		a, b, c, d = self._competency(["C-1"], ["BLS"])
		with a, b, c, d, self.assertRaises(BlockedError) as caught:
			station_auth._require_competency("EMP-X", "ST-1")
		data = caught.exception.block.as_dict()
		self.assertEqual(data["error_code"], "NS-001")
		self.assertEqual(data["items"], ["BLS"])

	@bru("BRU-HR-002")
	def test_permit_lets_login_pass_and_caps_session(self):
		until = add_to_date(now_datetime(), hours=2)
		a, b, c, d = self._competency(["C-1"], ["BLS"])
		with a, b, c, d, patch.object(error_codes, "active_permit", return_value={"valid_until": until}):
			self.assertEqual(station_auth._require_competency("EMP-X", "ST-1"), until)

	@bru("BRU-HR-002")
	def test_login_rejected_after_permit_expiry(self):
		a, b, c, d = self._competency(["C-1"], ["BLS"])
		with a, b, c, d, patch.object(error_codes, "active_permit", return_value=None):
			with self.assertRaises(BlockedError):
				station_auth._require_competency("EMP-X", "ST-1")

	@bru("BRU-HR-001")
	def test_ok_login_resolves_open_logs(self):
		name = error_codes.record("NS-001", "Employee", "EMP-X", user="Guest")
		a, b, c, d = self._competency(["C-1"], [])
		with a, b, c, d:
			self.assertIsNone(station_auth._require_competency("EMP-X", "ST-1"))
		self.assertEqual(frappe.db.get_value("TraceCore Error Log", name, "status"), "Resolved")

	@bru("BRU-HR-002")
	def test_near_expiry_warns(self):
		with patch.object(
			station_auth.extension, "run", return_value=[[{"certificate_type": "BLS", "expires_on": today()}]]
		):
			station_auth._expiring_warnings("EMP-X", "C-1")
		self.assertEqual(error_codes.pop_warnings()[0]["error_code"], "NS-002")

	def test_login_rejection_is_logged(self):
		from tracecore.v1.station import _session_response

		def refuse():
			raise BlockedError(
				Block("COMPETENCY_REQUIRED", "t", "r", "a", object_type="Employee", object_name="EMP-X")
			)

		before = frappe.db.count("TraceCore Error Log", {"error_code": "NS-003"})
		body = _session_response(refuse)
		self.assertFalse(body["ok"])
		self.assertEqual(frappe.db.count("TraceCore Error Log", {"error_code": "NS-003"}), before + 1)
