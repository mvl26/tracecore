"""FEAT-003: Guest station RPCs, bearer authorization, PIN proof and replay boundaries."""

import ast
import hashlib
import uuid
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import frappe
from frappe.auth import validate_auth
from frappe.handler import execute_cmd
from frappe.sessions import Session
from frappe.utils import now_datetime
from werkzeug.test import EnvironBuilder
from werkzeug.wrappers import Request

from tracecore.core import station_auth
from tracecore.core.client_time import ClientTimestampError, parse_client_ts
from tracecore.core.errors import BlockedError
from tracecore.tests.factories import make_t4_ready_set, make_user
from tracecore.tests.utils import IsolatedTestCase, request_headers
from tracecore.v1 import pack as pack_api
from tracecore.v1 import printer as printer_api
from tracecore.v1 import station as station_api
from tracecore.v1._common import BadRequestError, station_session
from tracecore.v1.tests.station_fixtures import make_station_employee, make_station_session

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]
TS = "2026-10-21T09:00:00+07:00"


@contextmanager
def local_context(**values):
	missing = object()
	previous = {field: getattr(frappe.local, field, missing) for field in values}
	try:
		for field, value in values.items():
			setattr(frappe.local, field, value)
		yield
	finally:
		for field, value in previous.items():
			if value is missing:
				if hasattr(frappe.local, field):
					delattr(frappe.local, field)
			else:
				setattr(frappe.local, field, value)


class TestStationSecurity(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		frappe.get_doc("User", "Administrator").add_roles("TC R10")
		self.user = make_user("rpc.operator@example.test", ("TC R04",))
		self.employee = make_station_employee(self.user)
		self.session = make_station_session(self.user)
		station_auth.set_pin(self.employee.name, "123456")
		self.addCleanup(station_auth.clear_pin_rate_limit, self.employee.name)
		self.addCleanup(frappe.set_user, "Administrator")
		self.addCleanup(frappe.local.response.pop, "http_status_code", None)

	def rpc(self, fn, **kwargs):
		frappe.local.response.pop("http_status_code", None)
		kwargs.setdefault("client_ts", datetime.now(timezone.utc).isoformat())
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
			return fn(**kwargs)

	def assert_block(self, result, code, status):
		self.assertFalse(result["ok"])
		self.assertEqual(result["error"]["code"], code)
		self.assertEqual(result["error"]["http_status"], status)
		self.assertEqual(frappe.local.response.get("http_status_code"), status)

	def test_auth_endpoints_are_guest_post_only(self):
		frappe.set_user("Guest")
		for fn in (station_api.login, station_api.logout, station_api.heartbeat, station_api.verify_pin):
			with self.subTest(fn=fn.__name__):
				frappe.is_whitelisted(fn)
				self.assertEqual(frappe.allowed_http_methods_for_whitelisted_func[fn], ["POST"])

	def test_auth_requires_offset_client_timestamp(self):
		calls = (
			(station_api.login, {"card_id": self.employee.tc_card_id, "station": "TR-004"}),
			(station_api.logout, {"token": self.session["token"]}),
			(station_api.heartbeat, {"token": self.session["token"]}),
			(station_api.verify_pin, {"token": self.session["token"], "pin": "123456"}),
		)
		for fn, args in calls:
			for ts in (None, "bad", "2026-10-21T09:00:00"):
				with self.subTest(fn=fn.__name__, ts=ts), self.assertRaises(ClientTimestampError):
					fn(**args, client_ts=ts)

	def test_auth_schema_rejects_nonscalar_credentials_without_echoing_them(self):
		for args in (
			{"card_id": {"secret": "sensitive"}, "station": "TR-004"},
			{"card_id": self.employee.tc_card_id, "station": ["TR-004"]},
		):
			with self.subTest(args=args), self.assertRaises(BadRequestError) as error:
				self.rpc(station_api.login, **args)
			self.assertNotIn("sensitive", str(error.exception))
		with self.assertRaises(BadRequestError):
			self.rpc(station_api.verify_pin, token=self.session["token"], pin={"pin": "sensitive"})

	def test_native_dispatch_controls_every_omitted_auth_field(self):
		frappe.set_user("Guest")
		calls = (
			("login", {"card_id": self.employee.tc_card_id, "station": "TR-004", "client_ts": TS}),
			("logout", {"token": self.session["token"], "client_ts": TS}),
			("heartbeat", {"token": self.session["token"], "client_ts": TS}),
			("verify_pin", {"token": self.session["token"], "pin": "123456", "client_ts": TS}),
		)
		for method, complete in calls:
			for omitted in complete:
				with self.subTest(method=method, omitted=omitted):
					args = frappe._dict({key: value for key, value in complete.items() if key != omitted})
					request = Request(
						EnvironBuilder(
							path=f"/api/method/tracecore.v1.station.{method}", method="POST"
						).get_environ()
					)
					with local_context(request=request, form_dict=args):
						if omitted == "token":
							self.assert_block(
								execute_cmd(f"tracecore.v1.station.{method}"), "SESSION_INVALID", 401
							)
						else:
							with self.assertRaises(
								ClientTimestampError if omitted == "client_ts" else BadRequestError
							) as error:
								execute_cmd(f"tracecore.v1.station.{method}")
							self.assertEqual(error.exception.http_status_code, 400)

	def assert_cookie_context_restored(self, fails):
		"""Exercise the real guard, then native Session.update on the original Desk cookie."""
		sid = "desk-cookie-" + uuid.uuid4().hex
		original = frappe._dict(
			user="Administrator",
			sid=sid,
			data=frappe._dict(user="Administrator", marker={"nested": ["desk"]}),
		)
		form = frappe._dict(cmd="desk-request", marker={"nested": ["original"]})
		cookie = object.__new__(Session)
		cookie.user, cookie.sid, cookie.data = "Administrator", sid, original
		context = {
			"session": original,
			"session_obj": cookie,
			"form_dict": form,
			"cache": {"desk-only": {"nested": [1]}},
			"role_permissions": {"desk-only": {"read": 1}},
			"user_perms": object(),
			"new_doc_templates": {"desk-only": "template"},
			"jenv_restricted": object(),
			"jenv_unrestricted": object(),
		}
		expected_session, expected_form = deepcopy(original), deepcopy(form)
		request = Request(EnvironBuilder(path="/api/method/guarded", method="POST").get_environ())
		context["request"] = request
		self.addCleanup(frappe.cache.hdel, "session", sid)
		self.addCleanup(frappe.cache.hdel, "last_db_session_update", sid)

		@station_session("TC R04")
		def guarded(station, client_ts, token=None):
			self.assertEqual(frappe.session.user, self.user)
			self.assertIsNot(frappe.local.session, original)
			self.assertIsNone(frappe.local.session_obj)
			self.assertNotIn("desk-only", frappe.local.cache)
			self.assertNotIn("desk-only", frappe.local.role_permissions)
			self.assertIsNone(frappe.local.user_perms)
			self.assertEqual(frappe.form_dict.cmd, "desk-request")
			frappe.form_dict.marker["nested"].append("actor")
			frappe.session.data["actor-only"] = True
			frappe.local.cache["actor-only"] = True
			frappe.local.role_permissions["actor-only"] = True
			frappe.local.new_doc_templates["actor-only"] = True
			if fails:
				raise RuntimeError("guarded failure")
			return {"ok": True, "actor": frappe.session.user}

		with local_context(**context):
			cookie.insert_session_record()
			if fails:
				with self.assertRaisesRegex(RuntimeError, "guarded failure"):
					guarded(station="TR-004", client_ts=TS, token=self.session["token"])
			else:
				self.assertEqual(
					guarded(station="TR-004", client_ts=TS, token=self.session["token"]),
					{"ok": True, "actor": self.user},
				)
			for field, value in context.items():
				self.assertIs(getattr(frappe.local, field), value, field)
			self.assertEqual(original, expected_session)
			self.assertEqual(form, expected_form)
			self.assertNotIn("actor-only", frappe.local.cache)
			self.assertNotIn("actor-only", frappe.local.role_permissions)
			self.assertNotIn("actor-only", frappe.local.new_doc_templates)
			with patch("frappe.database.database.Database.commit", return_value=None):
				self.assertTrue(cookie.update(force=True))
			persisted = ast.literal_eval(
				frappe.db.get_value("Sessions", {"sid": sid}, "sessiondata", order_by="sid")
			)
			self.assertEqual(persisted["user"], "Administrator")
			self.assertEqual(persisted["marker"], {"nested": ["desk"]})
			self.assertNotIn("actor-only", persisted)
			cached = frappe.cache.hget("session", sid)
			self.assertEqual((cached.user, cached.sid), ("Administrator", sid))
			self.assertEqual(cached.data["user"], "Administrator")

	def test_guard_success_preserves_cookie_session_request_and_permission_context(self):
		self.assert_cookie_context_restored(fails=False)

	def test_guard_exception_preserves_cookie_session_request_and_permission_context(self):
		self.assert_cookie_context_restored(fails=True)

	def test_login_schema_secrets_and_no_idempotency_token_storage(self):
		frappe.set_user("Guest")
		key = str(uuid.uuid4())
		before = frappe.db.count("Idempotency Key")
		with request_headers({"X-Idempotency-Key": key}):
			result = station_api.login(self.employee.tc_card_id, "TR-004", client_ts=TS)
		self.assertTrue(result["ok"])
		data = result["session"]
		self.assertEqual(data["roles"], ["TC R04"])
		self.assertEqual(data["employee_name"], self.employee.employee_name)
		self.assertEqual(data["station"], "TR-004")
		self.assertTrue(data["expires_at"])
		self.assertEqual(frappe.db.count("Idempotency Key"), before)
		self.assertNotIn("token_hash", data)
		stored = frappe.db.get_value("Station Session", data["session"], "token_hash")
		self.assertEqual(stored, hashlib.sha256(data["token"].encode()).hexdigest())
		audits = frappe.get_all(
			"Audit Log", filters={"ref_name": self.employee.name}, fields=["new_value", "client_ts"]
		)
		self.assertNotIn(data["token"], frappe.as_json(audits))
		self.assertTrue(any(row.client_ts == parse_client_ts(TS) for row in audits))

	def test_guest_heartbeat_logout_and_structured_errors(self):
		frappe.set_user("Guest")
		result = self.rpc(station_api.heartbeat, token=self.session["token"])
		self.assertEqual(result["session"], self.session["session"])
		self.assertNotIn("token", result)
		self.assertEqual(result.get("employee_name"), self.employee.employee_name)
		self.assertEqual(result.get("roles"), ["TC R04"])
		self.assertTrue(self.rpc(station_api.logout, token=self.session["token"])["ok"])
		self.assert_block(
			self.rpc(station_api.heartbeat, token=self.session["token"]), "SESSION_INVALID", 401
		)
		self.assert_block(
			self.rpc(station_api.login, card_id="SECRET-CARD-INVALID", station="TR-004"), "CARD_INVALID", 403
		)

	def test_verify_pin_issues_hashed_120s_single_use_bound_proof(self):
		frappe.set_user("Guest")
		result = self.rpc(station_api.verify_pin, token=self.session["token"], pin="123456")
		self.assertTrue(result["ok"])
		self.assertEqual(result["expires_in"], 120)
		proof = result["proof"]
		self.assertNotIn("123456", frappe.as_json(result))
		key = frappe.cache.make_key(station_auth._proof_key(proof))
		self.addCleanup(frappe.cache.delete, key)
		self.assertNotIn(proof.encode(), key)
		self.assertLessEqual(frappe.cache.ttl(key), 120)
		self.assertGreater(frappe.cache.ttl(key), 0)
		self.assertNotIn(proof.encode(), frappe.cache.get(key))
		doc = station_auth.consume_pin_proof(self.session["token"], proof)
		self.assertEqual(doc.user, self.user)
		with self.assertRaises(BlockedError):
			station_auth.consume_pin_proof(self.session["token"], proof)

	def test_proof_rejects_other_live_session_expiry_and_revocation(self):
		other_user = make_user("rpc.other@example.test", ("TC R04",))
		other = make_station_session(other_user)
		for mode in ("wrong-session", "expired", "idle", "disabled"):
			with self.subTest(mode=mode):
				proof = self.rpc(station_api.verify_pin, token=self.session["token"], pin="123456")["proof"]
				key = frappe.cache.make_key(station_auth._proof_key(proof))
				self.addCleanup(frappe.cache.delete, key)
				if mode == "expired":
					frappe.cache.delete(key)
				elif mode == "idle":
					frappe.db.set_value(
						"Station Session",
						self.session["session"],
						"last_activity_at",
						now_datetime() - timedelta(minutes=11),
					)
				elif mode == "disabled":
					frappe.db.set_value("Employee", self.employee.name, "tc_card_enabled", 0)
				with self.assertRaises(BlockedError):
					station_auth.consume_pin_proof(
						other["token"] if mode == "wrong-session" else self.session["token"], proof
					)
				frappe.db.set_value("Employee", self.employee.name, "tc_card_enabled", 1)
				frappe.db.set_value(
					"Station Session",
					self.session["session"],
					{"is_open": 1, "ended_at": None, "last_activity_at": now_datetime()},
				)

	def test_pin_errors_and_forced_change_are_structured(self):
		for attempt in range(3):
			result = self.rpc(station_api.verify_pin, token=self.session["token"], pin="000000")
			self.assert_block(
				result, "PIN_LOCKED" if attempt == 2 else "PIN_INVALID", 429 if attempt == 2 else 403
			)
		station_auth.clear_pin_rate_limit(self.employee.name)
		frappe.db.set_value("Employee", self.employee.name, "tc_pin_reset_required", 1)
		self.assert_block(
			self.rpc(station_api.verify_pin, token=self.session["token"], pin="123456"),
			"PIN_CHANGE_REQUIRED",
			409,
		)

	def test_pin_proof_uses_locked_reset_state_after_waiting_on_employee(self):
		proof = self.rpc(station_api.verify_pin, token=self.session["token"], pin="123456")["proof"]
		frappe.db.set_value("Employee", self.employee.name, "tc_pin_reset_required", 1)
		get_value = frappe.db.get_value

		def earlier_snapshot(*args, **kwargs):
			doctype = args[0] if args else kwargs.get("doctype")
			fieldname = args[2] if len(args) > 2 else kwargs.get("fieldname")
			if doctype == "Employee" and fieldname == "tc_pin_reset_required":
				return 0
			return get_value(*args, **kwargs)

		with patch.object(frappe.db, "get_value", side_effect=earlier_snapshot):
			self.assert_block(
				self.rpc(station_api.verify_pin, token=self.session["token"], pin="123456"),
				"PIN_CHANGE_REQUIRED",
				409,
			)
			with self.assertRaises(BlockedError) as error:
				station_auth.consume_pin_proof(self.session["token"], proof)
			self.assertEqual(error.exception.block.code, "PIN_CHANGE_REQUIRED")

	def test_all_pack_rpcs_require_live_session_even_for_frappe_admin(self):
		for fn, args in (
			(pack_api.scan, {"raw": "CY-991231-9999"}),
			(pack_api.resolve_ci, {"raw": "lot", "open_set": "missing"}),
			(
				pack_api.generate_cycle_id,
				{"set_id": "missing", "confirmed_lines": [], "ci_batch": "missing", "pack_type": "missing"},
			),
			(pack_api.reprint_label, {"cycle_id": "missing", "reason": "faded"}),
			(pack_api.void, {"cycle_id": "missing", "reason": "Torn"}),
		):
			with self.subTest(fn=fn.__name__):
				self.assert_block(self.rpc(fn, station="TR-004", **args), "SESSION_INVALID", 401)
		self.assert_block(
			self.rpc(printer_api.set_roll, station="TR-004", roll_code="CN-99999"), "SESSION_INVALID", 401
		)

	def test_second_station_login_rejects_old_kiosk_heartbeat(self):
		make_station_session(self.user, "TR-005")  # valid competency at the second physical station
		frappe.set_user("Guest")
		first = self.rpc(station_api.login, card_id=self.employee.tc_card_id, station="TR-004")
		second = self.rpc(station_api.login, card_id=self.employee.tc_card_id, station="TR-005")
		self.assertTrue(first["ok"] and second["ok"])
		self.assert_block(
			self.rpc(station_api.heartbeat, token=first["session"]["token"]), "SESSION_INVALID", 401
		)
		live = self.rpc(station_api.heartbeat, token=second["session"]["token"])
		self.assertTrue(live["ok"])
		self.assertEqual(live["station"], "TR-005")

	def test_guest_pack_actor_and_idempotent_replay_recheck_live_session(self):
		ready = make_t4_ready_set()
		frappe.set_user("Guest")
		key = str(uuid.uuid4())
		args = {
			"set_id": ready.set_id,
			"station": "TR-004",
			"confirmed_lines": ready.instruments,
			"ci_batch": ready.ci_batch,
			"pack_type": ready.pack_type,
			"client_ts": datetime.now(timezone.utc).isoformat(),
			"token": self.session["token"],
		}
		with request_headers({"X-Idempotency-Key": key}):
			frappe.is_whitelisted(pack_api.generate_cycle_id)
			first = frappe.call(
				pack_api.generate_cycle_id,
				**args,
				packed_by_user="Administrator",
				employee="spoofed",
				user="Administrator",
			)
			self.assertTrue(first["ok"])
			second = pack_api.generate_cycle_id(**args)
			self.assertEqual(first, second)
			self.assertEqual(frappe.session.user, "Guest")
			self.assertEqual(
				frappe.db.get_value("Pack", first["pack"]["cycle_id"], "packed_by_user"), self.user
			)
			station_auth.logout(self.session["token"])
			self.assert_block(pack_api.generate_cycle_id(**args), "SESSION_INVALID", 401)

	def test_guest_native_dispatch_accepts_body_token_without_web_login(self):
		frappe.set_user("Guest")
		request = Request(
			EnvironBuilder(
				path="/api/method/tracecore.v1.pack.scan",
				method="POST",
				headers={"X-Idempotency-Key": str(uuid.uuid4())},
			).get_environ()
		)
		with (
			patch.object(frappe.local, "request", request, create=True),
			patch.object(
				frappe.local,
				"form_dict",
				frappe._dict(
					raw="CY-991231-9999", station="TR-004", token=self.session["token"], client_ts=TS
				),
				create=True,
			),
		):
			validate_auth()
			result = execute_cmd("tracecore.v1.pack.scan")
			self.assert_block(result, "PACK_NOT_FOUND", 404)
			self.assertEqual(frappe.session.user, "Guest")

	def test_guard_preserves_positional_python_call_contract(self):
		with request_headers({"X-Idempotency-Key": str(uuid.uuid4())}):
			result = pack_api.scan("CY-991231-9999", "TR-004", client_ts=TS, token=self.session["token"])
			self.assert_block(result, "PACK_NOT_FOUND", 404)

	def test_bearer_cannot_select_other_station_or_gain_actor_roles(self):
		frappe.set_user("Guest")
		self.assert_block(
			self.rpc(pack_api.scan, token=self.session["token"], station="TR-003", raw="missing"),
			"SESSION_STATION_MISMATCH",
			403,
		)
		frappe.set_user("Administrator")
		frappe.get_doc("User", self.user).remove_roles("TC R04")
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			self.rpc(pack_api.scan, token=self.session["token"], station="TR-004", raw="missing")
		self.assertEqual(frappe.session.user, "Guest")
