from datetime import timedelta
from unittest.mock import patch

import frappe
from frappe.utils import add_to_date, now_datetime, today

from tracecore.core import notification, station_auth, zones
from tracecore.core.errors import BlockedError
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1 import notification as notification_api
from tracecore.v1 import station as station_api

test_dependencies = ["Company"]


def setup_operator(case):
	"""Người giữ phiên NV-AUTH-001 (R04, PIN 123456) có năng lực tại TR-004."""
	case.user = make_user("station.operator@example.test", ("TC R04",))
	case.employee = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": "Station",
			"last_name": "Operator",
			"gender": "Male",
			"date_of_birth": "1990-01-01",
			"date_of_joining": today(),
			"company": "_Test Company",
			"status": "Active",
			"user_id": case.user,
			"tc_card_id": "NV-AUTH-001",
			"tc_card_enabled": 1,
		}
	).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
	start = now_datetime()
	case.competency = frappe.get_doc(
		{
			"doctype": "Station Competency",
			"employee": case.employee.name,
			"station": "TR-004",
			"valid_from": add_to_date(start, hours=-1),
			"valid_until": add_to_date(start, hours=8),
			"is_active": 1,
		}
	).insert(ignore_permissions=True)
	station_auth.set_pin(case.employee.name, "123456")
	station_auth.clear_pin_rate_limit(case.employee.name)


class TestStationAuth(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.get_doc("User", "Administrator").add_roles("TC R10")
		setup_operator(self)

	@bru("BRU-HR-001")
	def test_login_requires_active_competency_and_returns_one_time_token(self):
		result = station_auth.login(" nv-auth-001 ", "TR-004")
		self.assertTrue(result["token"])
		self.assertEqual(result["employee"], self.employee.name)
		session = frappe.get_doc("Station Session", result["session"])
		self.assertNotEqual(session.token_hash, result["token"])
		self.assertEqual(session.station, "TR-004")
		self.assertEqual(session.is_open, 1)

		self.competency.is_active = 0
		self.competency.save(ignore_permissions=True)
		with self.assertRaises(BlockedError) as caught:
			station_auth.login("NV-AUTH-001", "TR-004")
		# A-71 (g): thẻ hợp lệ thấy NS-003; thẻ lạ vẫn CARD_INVALID nên quét không dò được thẻ.
		self.assertEqual(caught.exception.block.as_dict()["error_code"], "NS-003")
		with self.assertRaises(BlockedError) as unknown:
			station_auth.login("NV-NO-SUCH-CARD", "TR-004")
		self.assertEqual(unknown.exception.block.code, "CARD_INVALID")
		self.assertNotIn("error_code", unknown.exception.block.as_dict())
		reasons = frappe.get_all(
			"Audit Log", filters={"ref_name": self.employee.name, "action": "Reject"}, pluck="new_value"
		)
		self.assertTrue(any("COMPETENCY_REQUIRED" in (value or "") for value in reasons))

	def test_rejected_card_scans_are_throttled_per_client(self):
		self.addCleanup(station_auth.clear_login_throttle)
		station_auth.clear_login_throttle()
		with patch.object(station_auth, "LOGIN_FAILURE_LIMIT", 3):
			for _ in range(3):
				with self.assertRaises(BlockedError) as caught:
					station_auth.login("NV-NO-SUCH-CARD", "TR-004")
				self.assertEqual(caught.exception.block.code, "CARD_INVALID")
			with self.assertRaises(BlockedError) as throttled:
				station_auth.login("NV-AUTH-001", "TR-004")
		self.assertEqual(throttled.exception.block.code, "LOGIN_THROTTLED")
		self.assertEqual(throttled.exception.block.http_status, 429)

	def test_second_login_closes_previous_session(self):
		first = station_auth.login("NV-AUTH-001", "TR-004")
		second = station_auth.login("NV-AUTH-001", "TR-004")
		self.assertNotEqual(first["session"], second["session"])
		old = frappe.get_doc("Station Session", first["session"])
		self.assertEqual(old.is_open, 0)
		self.assertEqual(old.end_reason, "Replaced")
		self.assertEqual(
			frappe.db.count("Station Session", {"employee": self.employee.name, "is_open": 1}), 1
		)

	def test_absolute_and_idle_expiry_are_enforced_server_side(self):
		result = station_auth.login("NV-AUTH-001", "TR-004")
		frappe.db.set_value(
			"Station Session", result["session"], "absolute_expires_at", now_datetime() - timedelta(seconds=1)
		)
		with self.assertRaises(BlockedError) as caught:
			station_auth.authenticate_session(result["token"])
		self.assertEqual(caught.exception.block.code, "SESSION_EXPIRED")

		result = station_auth.login("NV-AUTH-001", "TR-004")
		frappe.db.set_value(
			"Station Session", result["session"], "last_activity_at", now_datetime() - timedelta(minutes=11)
		)
		with self.assertRaises(BlockedError) as caught:
			station_auth.authenticate_session(result["token"])
		self.assertEqual(caught.exception.block.code, "SESSION_IDLE")

	def test_pin_is_bcrypt_and_three_failures_lock_for_five_minutes(self):
		stored = frappe.utils.password.get_decrypted_password(
			"Employee", self.employee.name, "tc_pin_hash", raise_exception=False
		)
		self.assertTrue(stored.startswith("$2"))
		for attempt in range(3):
			with self.assertRaises(BlockedError) as caught:
				station_auth.verify_pin(self.employee.name, "000000")
			expected = "PIN_LOCKED" if attempt == 2 else "PIN_INVALID"
			self.assertEqual(caught.exception.block.code, expected)
		with self.assertRaises(BlockedError) as caught:
			station_auth.verify_pin(self.employee.name, "123456")
		self.assertEqual(caught.exception.block.code, "PIN_LOCKED")

	def test_pin_failure_counter_is_atomic_not_read_modify_write(self):
		# Parallel guesses can all read a stale counter; the limit must use an atomic increment.
		original = type(frappe.cache).get_value

		def stale(cache, key, *args, **kwargs):
			if str(key).startswith("tracecore:pin"):
				return 0
			return original(cache, key, *args, **kwargs)

		with patch.object(type(frappe.cache), "get_value", stale):
			codes = []
			for _ in range(3):
				with self.assertRaises(BlockedError) as caught:
					station_auth.verify_pin(self.employee.name, "000000")
				codes.append(caught.exception.block.code)
		self.assertEqual(codes, ["PIN_INVALID", "PIN_INVALID", "PIN_LOCKED"])

	def test_logout_and_heartbeat_require_the_token(self):
		result = station_auth.login("NV-AUTH-001", "TR-004")
		session = station_auth.heartbeat(result["token"])
		self.assertEqual(session.name, result["session"])
		station_auth.logout(result["token"])
		with self.assertRaises(BlockedError) as caught:
			station_auth.heartbeat(result["token"])
		self.assertEqual(caught.exception.block.code, "SESSION_INVALID")

	def test_v1_station_session_endpoints_return_stable_bodies(self):
		ts = "2026-10-21T09:00:00+07:00"
		login = station_api.login(card_id="NV-AUTH-001", station="TR-004", client_ts=ts)
		self.assertTrue(login["ok"])
		self.assertTrue(login["session"]["token"])
		heartbeat = station_api.heartbeat(token=login["session"]["token"], client_ts=ts)
		self.assertEqual(heartbeat["session"], login["session"]["session"])
		verified = station_api.verify_pin(token=login["session"]["token"], pin="123456", client_ts=ts)
		self.assertTrue(verified["proof"])
		self.assertTrue(station_api.logout(token=login["session"]["token"], client_ts=ts)["ok"])
		failed = station_api.heartbeat(token=login["session"]["token"], client_ts=ts)
		self.assertFalse(failed["ok"])
		self.assertEqual(failed["error"]["code"], "SESSION_INVALID")


class TestSwitchStation(IsolatedTestCase):
	"""Admin chuyển trạm trong màn có cột trạm (ux-foundations NAV-03): giữ người đã quét thẻ, vẫn kiểm năng lực."""

	def setUp(self):
		super().setUp()
		setup_operator(self)
		self.login = station_auth.login("NV-AUTH-001", "TR-004")
		self.ts = now_datetime().isoformat() + "+07:00"

	def _allow_station(self, station):
		start = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": self.employee.name,
				"station": station,
				"valid_from": add_to_date(start, hours=-1),
				"valid_until": add_to_date(start, hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	def test_switch_replaces_session_and_keeps_person_and_expiry(self):
		self._allow_station("TR-003")
		old = frappe.get_doc("Station Session", self.login["session"])
		result = station_auth.switch_station(self.login["token"], "TR-003")
		self.assertEqual(result["station"], "TR-003")
		self.assertEqual(result["employee"], self.employee.name)
		self.assertNotEqual(result["token"], self.login["token"])
		self.assertEqual(
			frappe.get_doc("Station Session", result["session"]).absolute_expires_at,
			old.absolute_expires_at,
		)
		old.reload()
		self.assertEqual(old.is_open, 0)
		self.assertEqual(old.end_reason, "Replaced")
		with self.assertRaises(BlockedError):
			station_auth.authenticate_session(self.login["token"])

	def test_switch_without_competency_is_blocked_and_keeps_current_session(self):
		with self.assertRaises(BlockedError) as caught:
			station_auth.switch_station(self.login["token"], "TR-003")
		self.assertEqual(caught.exception.block.as_dict()["error_code"], "NS-003")
		self.assertEqual(station_auth.authenticate_session(self.login["token"]).station, "TR-004")

	def test_switch_without_competency_tells_another_person_to_scan(self):
		"""#1822: cùng khu, thiếu năng lực thì báo rõ và yêu cầu người khác quét thẻ; giữ phiên hiện tại."""
		with self.assertRaises(BlockedError) as caught:
			station_auth.switch_station(self.login["token"], "TR-003")
		self.assertEqual(caught.exception.block.code, "COMPETENCY_REQUIRED")
		self.assertEqual(
			caught.exception.block.action,
			frappe._("Ask a person assigned to that station to scan their card there."),
		)

	def test_switch_to_another_zone_needs_a_new_card_scan(self):
		"""#1822, D2: khác khu luôn phải quét lại thẻ, kể cả có năng lực và kể cả admin; phiên cũ đóng ngay."""
		self._allow_station("TR-006")
		with self.assertRaises(BlockedError) as caught:
			station_auth.switch_station(self.login["token"], "TR-006")
		self.assertEqual(caught.exception.block.code, "STATION_ZONE_RESCAN")
		self.assertEqual(
			frappe.db.get_value("Station Session", self.login["session"], "is_open"), 0, "phiên cũ phải đóng"
		)
		with self.assertRaises(BlockedError) as again:
			station_auth.authenticate_session(self.login["token"])
		self.assertEqual(again.exception.block.code, "SESSION_INVALID")

	def test_api_another_zone_returns_the_block_for_admin_and_for_a_role_without_that_station(self):
		"""Khác khu trả khối để máy trạm về màn quét thẻ, không phải 403 như thiếu role cùng khu."""
		self._allow_station("TR-006")
		blocked = station_api.switch_station(token=self.login["token"], station="TR-006", client_ts=self.ts)
		self.assertFalse(blocked["ok"])
		self.assertEqual(blocked["error"]["code"], "STATION_ZONE_RESCAN")
		other = station_auth.login("NV-AUTH-001", "TR-004")
		frappe.set_user(self.user)
		try:
			blocked = station_api.switch_station(token=other["token"], station="TR-006", client_ts=self.ts)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(blocked["error"]["code"], "STATION_ZONE_RESCAN")

	def test_reload_rechecks_competency(self):
		"""#1822: tải lại trang và bấm nút cùng một luật; heartbeat khi khôi phục phiên kiểm lại năng lực."""
		frappe.db.set_value(
			"Station Competency", {"employee": self.employee.name, "station": "TR-004"}, "is_active", 0
		)
		plain = station_api.heartbeat(token=self.login["token"], client_ts=self.ts)
		self.assertTrue(plain["ok"], "heartbeat định kỳ không kiểm lại")
		restored = station_api.heartbeat(token=self.login["token"], client_ts=self.ts, recheck=1)
		self.assertFalse(restored["ok"])
		self.assertEqual(restored["error"]["code"], "COMPETENCY_REQUIRED")
		self.assertEqual(frappe.db.get_value("Station Session", self.login["session"], "is_open"), 0)

	def test_reload_with_valid_competency_keeps_the_session(self):
		restored = station_api.heartbeat(token=self.login["token"], client_ts=self.ts, recheck=1)
		self.assertTrue(restored["ok"])

	def test_switch_rejects_invalid_token(self):
		with self.assertRaises(BlockedError) as caught:
			station_auth.switch_station("no-such-token", "TR-003")
		self.assertEqual(caught.exception.block.code, "SESSION_INVALID")

	def test_api_rejects_a_station_outside_the_desk_role(self):
		# R04 không có chức năng nào ở T5: có năng lực trên thẻ cũng không được chuyển
		self._allow_station("TR-005")
		frappe.set_user(self.user)
		try:
			with self.assertRaises(frappe.PermissionError):
				station_api.switch_station(token=self.login["token"], station="TR-005", client_ts=self.ts)
		finally:
			frappe.set_user("Administrator")
		self.assertEqual(station_auth.authenticate_session(self.login["token"]).station, "TR-004")

	def test_api_allows_a_station_of_the_desk_role(self):
		self._allow_station("TR-003")
		frappe.set_user(self.user)
		try:
			switched = station_api.switch_station(
				token=self.login["token"], station="TR-003", client_ts=self.ts
			)
		finally:
			frappe.set_user("Administrator")
		self.assertTrue(switched["ok"])

	def test_api_returns_new_session_or_block_for_admin(self):
		blocked = station_api.switch_station(token=self.login["token"], station="TR-003", client_ts=self.ts)
		self.assertFalse(blocked["ok"])
		self._allow_station("TR-003")
		switched = station_api.switch_station(token=self.login["token"], station="TR-003", client_ts=self.ts)
		self.assertTrue(switched["ok"])
		self.assertEqual(switched["session"]["station"], "TR-003")


class TestGateStations(IsolatedTestCase):
	def test_gate_station_points_to_assembly_station(self):
		"""A-93: nút Mở trạm của lỗi Sai thứ tự trạm cần trạm của cổng."""
		self.assertEqual(zones.gate_stations()["T3"]["name"], "TR-003")

	def test_station_info_carries_gate_stations(self):
		self.assertIn("T3", station_api._station_row("TR-004")["gate_stations"])


class TestStationNavigation(IsolatedTestCase):
	"""Hàng nút trạm theo thẻ đã quét (#1831 S-01, A-91), vai trò chính (S-02), banner khẩn (S-06)."""

	def setUp(self):
		super().setUp()
		setup_operator(self)
		self.login = station_auth.login("NV-AUTH-001", "TR-004")

	def _allow_station(self, station):
		start = now_datetime()
		frappe.get_doc(
			{
				"doctype": "Station Competency",
				"employee": self.employee.name,
				"station": station,
				"valid_from": add_to_date(start, hours=-1),
				"valid_until": add_to_date(start, hours=8),
				"is_active": 1,
			}
		).insert(ignore_permissions=True)

	def _names(self):
		result = station_api.stations(token=self.login["token"])
		self.assertTrue(result["ok"])
		return [row["name"] for row in result["stations"]]

	def test_technician_sees_only_competent_stations_of_own_zone(self):
		self.assertEqual(self._names(), ["TR-004"])
		self._allow_station("TR-003")
		self._allow_station("TR-006")  # có năng lực nhưng khác khu: không hiện
		self.assertEqual(self._names(), ["TR-003", "TR-004"])

	def test_supervisor_card_sees_all_stations(self):
		frappe.get_doc("User", self.user).add_roles("TC R02")
		names = self._names()
		self.assertIn("TR-001", names)
		self.assertIn("TR-006", names)

	def test_invalid_token_gets_a_block(self):
		result = station_api.stations(token="no-such-token")
		self.assertEqual(result["error"]["code"], "SESSION_INVALID")

	def test_session_reports_main_role_at_station(self):
		frappe.get_doc("User", self.user).add_roles("TC R02", "TC R05", "TC R10")
		ts = now_datetime().isoformat() + "+07:00"
		login = station_api.login(card_id="NV-AUTH-001", station="TR-004", client_ts=ts)
		self.assertEqual(login["session"]["station_role"], "TC R04")
		restored = station_api.heartbeat(token=login["session"]["token"], client_ts=ts)
		self.assertEqual(restored["station_role"], "TC R04")

	def _urgent(self, subject, ref_name=None, event="RECALL_ORDER"):
		return frappe.get_doc(
			{
				"doctype": "Notification Delivery",
				"recipient": self.user,
				"event_code": event,
				"channel": "In App",
				"status": "Sent",
				"urgency": "Urgent",
				"subject": subject,
				"ref_doctype": "Station Session" if ref_name else None,
				"ref_name": ref_name,
				"link": "/app/station-session/x",
				"sent_at": now_datetime(),
			}
		).insert(ignore_permissions=True)

	def test_urgent_banner_skips_documents_of_another_zone(self):
		other = station_auth.login("NV-AUTH-001", "TR-004")["session"]
		frappe.db.set_value("Station Session", other, "station", "TR-001", update_modified=False)
		self.login = station_auth.login("NV-AUTH-001", "TR-004")
		self._urgent("Khu khác", other)
		self.assertIsNone(notification_api.station_summary(token=self.login["token"])["urgent"])

	def test_urgent_banner_shows_same_zone_and_unknown_with_handler(self):
		self._urgent("Không rõ khu")
		urgent = notification_api.station_summary(token=self.login["token"])["urgent"]
		self.assertEqual(urgent["subject"], "Không rõ khu")
		self.assertEqual(urgent["link"], "/app/station-session/x")
		self.assertIn("handled_by", urgent)

	def test_relevance_by_equipment_zone(self):
		self.assertTrue(notification.relevant_to_station(frappe._dict(), "TR-004"))

	def test_department_card_sees_only_the_department_station(self):
		from unittest.mock import patch

		from tracecore.v1 import station as station_rpc

		session = frappe._dict(user="r08@test", employee="HR-EMP-X", station="TR-008")
		with (
			patch("frappe.get_roles", return_value=["TC R08"]),
			patch.object(station_rpc.station_auth, "can_work_at", return_value=True),
			patch.object(station_rpc.navigation, "can_open_station", return_value=True),
		):
			visible = station_rpc._visible_stations(session)
		self.assertEqual([row["name"] for row in visible], ["TR-008"])

	def test_session_says_which_department_the_card_belongs_to(self):
		from tracecore.tests.factories import make_department, make_employee
		from tracecore.v1 import station as station_rpc

		department = make_department("Khoa phiên T8")
		employee = make_employee(first_name="Điều dưỡng phiên", department=department).name
		session = station_rpc._with_station_role({"station": "TR-008", "employee": employee, "roles": []})
		self.assertEqual(session["department"], department)
		self.assertTrue(session["department_name"])

	def test_department_station_hides_notices_meant_only_for_cssd(self):
		from unittest.mock import patch

		row = frappe._dict(event_code="CONSUMPTION_FAILED")
		with patch.object(notification, "_rule_roles", return_value=["TC R09"]):
			self.assertFalse(notification.relevant_to_station(row, "TR-008"))
			self.assertTrue(notification.relevant_to_station(row, "TR-002"))
		with patch.object(notification, "_rule_roles", return_value=["TC R08", "TC R09"]):
			self.assertTrue(notification.relevant_to_station(row, "TR-008"))
		with patch.object(notification, "_rule_roles", return_value=[]):
			self.assertTrue(notification.relevant_to_station(row, "TR-008"))


class TestApproverProof(IsolatedTestCase):
	"""R02 quét thẻ + PIN trên kiosk của người khác (architecture C6, UC-12 A1): proof dùng một lần gắn với phiên đó."""

	def setUp(self):
		super().setUp()
		frappe.get_doc("User", "Administrator").add_roles("TC R10")
		setup_operator(self)

	def make_approver(self, card="NV-R02-001", roles=("TC R02",), pin="654321"):
		user = make_user(card.lower() + "@example.test", roles)
		employee = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": "Giám sát",
				"last_name": card,
				"gender": "Female",
				"date_of_birth": "1990-01-01",
				"date_of_joining": today(),
				"company": "_Test Company",
				"status": "Active",
				"user_id": user,
				"tc_card_id": card,
				"tc_card_enabled": 1,
			}
		).insert(ignore_permissions=True, ignore_mandatory=True, ignore_links=True)
		station_auth.set_pin(employee.name, pin)
		station_auth.clear_pin_rate_limit(employee.name)
		return employee

	def assert_block(self, code, fn, *args, **kwargs):
		with self.assertRaises(BlockedError) as caught:
			fn(*args, **kwargs)
		self.assertEqual(caught.exception.block.code, code)

	@bru("BRU-PAR-005")
	def test_proof_is_one_time_and_bound_to_operator_session(self):
		approver = self.make_approver()
		login = station_auth.login("NV-AUTH-001", "TR-004")
		result = station_auth.create_approver_proof(login["token"], " nv-r02-001 ", "654321")
		self.assertTrue(result["proof"])
		self.assertEqual(result["expires_in"], station_auth.PROOF_SECONDS)
		self.assertEqual(result["employee_name"], approver.employee_name)

		got = station_auth.consume_approver_proof(login["session"], result["proof"])
		self.assertEqual((got.employee, got.user), (approver.name, approver.user_id))
		# dùng một lần
		self.assert_block(
			"PIN_PROOF_INVALID", station_auth.consume_approver_proof, login["session"], result["proof"]
		)
		# phiên khác, hoặc role khác role đã duyệt → không nhận
		other = station_auth.create_approver_proof(login["token"], "NV-R02-001", "654321")["proof"]
		self.assert_block("PIN_PROOF_INVALID", station_auth.consume_approver_proof, "SES-OTHER", other)
		other = station_auth.create_approver_proof(login["token"], "NV-R02-001", "654321")["proof"]
		self.assert_block(
			"PIN_PROOF_INVALID", station_auth.consume_approver_proof, login["session"], other, role="TC R01"
		)
		# proof không phải proof duyệt (PIN của chính người giữ phiên) → không nhận
		own = station_auth.create_pin_proof(login["token"], "123456")["proof"]
		self.assert_block("PIN_PROOF_INVALID", station_auth.consume_approver_proof, login["session"], own)

	@bru("BRU-PAR-005")
	def test_proof_rejected_after_logout_or_approver_loses_role(self):
		approver = self.make_approver()
		login = station_auth.login("NV-AUTH-001", "TR-004")
		proof = station_auth.create_approver_proof(login["token"], "NV-R02-001", "654321")["proof"]
		frappe.get_doc("User", approver.user_id).remove_roles("TC R02")
		self.assert_block(
			"APPROVER_NOT_ALLOWED", station_auth.consume_approver_proof, login["session"], proof
		)

		frappe.get_doc("User", approver.user_id).add_roles("TC R02")
		proof = station_auth.create_approver_proof(login["token"], "NV-R02-001", "654321")["proof"]
		station_auth.logout(login["token"])
		self.assert_block("PIN_PROOF_INVALID", station_auth.consume_approver_proof, login["session"], proof)

	def test_create_rejects_wrong_pin_card_role_and_session(self):
		self.make_approver()
		self.make_approver(card="NV-R06-009", roles=("TC R06",))
		token = station_auth.login("NV-AUTH-001", "TR-004")["token"]
		self.assert_block("PIN_INVALID", station_auth.create_approver_proof, token, "NV-R02-001", "000000")
		self.assert_block("CARD_INVALID", station_auth.create_approver_proof, token, "NV-KHONG-CO", "654321")
		# người không có role duyệt: chặn trước khi thử PIN (không đốt lượt PIN)
		self.assert_block(
			"APPROVER_NOT_ALLOWED", station_auth.create_approver_proof, token, "NV-R06-009", "654321"
		)
		# role xin duyệt phải là role được ủy quyền duyệt
		self.assert_block(
			"APPROVER_NOT_ALLOWED",
			station_auth.create_approver_proof,
			token,
			"NV-R02-001",
			"654321",
			role="TC R06",
		)
		self.assert_block(
			"SESSION_INVALID", station_auth.create_approver_proof, "sai", "NV-R02-001", "654321"
		)

	def test_create_requires_changed_pin(self):
		approver = self.make_approver()
		frappe.db.set_value("Employee", approver.name, "tc_pin_reset_required", 1)
		token = station_auth.login("NV-AUTH-001", "TR-004")["token"]
		self.assert_block(
			"PIN_CHANGE_REQUIRED", station_auth.create_approver_proof, token, "NV-R02-001", "654321"
		)

	def test_v1_verify_approver_returns_proof_or_stable_error(self):
		self.make_approver()
		ts = "2026-10-26T09:00:00+07:00"
		token = station_api.login(card_id="NV-AUTH-001", station="TR-004", client_ts=ts)["session"]["token"]
		ok = station_api.verify_approver(
			token=token, card_id="NV-R02-001", pin="654321", role="TC R02", client_ts=ts
		)
		self.assertTrue(ok["ok"])
		self.assertTrue(ok["proof"])
		wrong = station_api.verify_approver(token=token, card_id="NV-R02-001", pin="000000", client_ts=ts)
		self.assertFalse(wrong["ok"])
		self.assertEqual(wrong["error"]["code"], "PIN_INVALID")
