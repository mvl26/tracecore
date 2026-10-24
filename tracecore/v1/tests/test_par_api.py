"""RPC tracecore.v1.par.* (FEAT-032, UC-31): kiểm cơ số, đề nghị từ T4, duyệt/từ chối từ Desk bằng PIN."""

import uuid

import frappe
from frappe.utils import add_days, today

from tracecore.par import override
from tracecore.par.tests.test_override import PIN, make_approver
from tracecore.tests.factories import make_set_unit, make_t4_ready_set
from tracecore.tests.utils import bru, request_headers
from tracecore.v1 import par as par_api
from tracecore.v1._common import BadRequestError
from tracecore.v1.par import override as override_api
from tracecore.v1.tests.test_pack_api import (
	SESSION_TOKENS,
	STATION,
	PackApiCase,
	assert_rejection,
	http_status,
	now_ts,
	reject_count,
	rejects_since,
)

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

STATION_RPCS = (override_api.request,)


def call(fn, key=None, **kwargs):
	"""Gọi RPC như kiosk (phiên trạm + khóa idempotent) hoặc như người dùng Desk (không token)."""
	frappe.local.response.pop("http_status_code", None)
	if fn in STATION_RPCS:
		kwargs.setdefault("client_ts", now_ts())
		kwargs.setdefault("token", SESSION_TOKENS.get(frappe.session.user))
	with request_headers({"X-Idempotency-Key": key or str(uuid.uuid4()), "X-TC-Station": STATION}):
		return fn(**kwargs)


def exhausted(max_cycles=5):
	ready = make_t4_ready_set(max_cycles=max_cycles)
	frappe.db.set_value("Set Unit", ready.set_id, "cycles_used", max_cycles)
	return ready


class TestCheckRpc(PackApiCase):
	@bru("BRU-PAR-003")
	def test_single_set_returns_evaluation(self):
		ready = make_t4_ready_set(max_cycles=10)
		frappe.db.set_value("Set Unit", ready.set_id, "cycles_used", 6)
		result = call(par_api.check, set_id=ready.set_id)
		self.assertTrue(result["ok"])
		par = result["par"]
		self.assertEqual((par["state"], par["remaining"], par["warn_at"]), ("warn", 4, 5))
		self.assertEqual(par["set_unit"], ready.set_id)

	def test_unknown_set_is_404(self):
		with self.assertRaises(frappe.DoesNotExistError):
			call(par_api.check, set_id="NO-SUCH-SET")

	@bru("BRU-PAR-003")
	def test_list_mode_returns_only_sets_needing_attention(self):
		fine = make_t4_ready_set(max_cycles=300)
		warn = make_t4_ready_set(max_cycles=10)
		full = exhausted()
		frappe.db.set_value("Set Unit", warn.set_id, "cycles_used", 7)
		result = call(par_api.check)
		by_set = {row["set_unit"]: row for row in result["sets"]}
		self.assertNotIn(fine.set_id, by_set)
		self.assertEqual(by_set[warn.set_id]["state"], "warn")
		self.assertEqual(by_set[full.set_id]["state"], "blocked")
		for row in by_set.values():
			self.assertTrue(row["set_name"])
			self.assertIn("status", row)

	def test_list_mode_filters_by_states_and_limit(self):
		ready = make_t4_ready_set(max_cycles=300)
		everything = call(par_api.check, states=["ok", "warn", "blocked", "override", "undefined"])
		self.assertIn(ready.set_id, [row["set_unit"] for row in everything["sets"]])
		limited = call(par_api.check, states='["ok"]', limit=1)
		self.assertEqual(len(limited["sets"]), 1)
		for bad in ("[]", '["nope"]', {"a": 1}):
			with self.assertRaises(BadRequestError):
				call(par_api.check, states=bad)


class TestRequestRpc(PackApiCase):
	@bru("BRU-PAR-004")
	def test_request_from_t4_creates_requested_override_and_replays(self):
		ready = exhausted()
		key, ts = str(uuid.uuid4()), now_ts()
		args = dict(set_id=ready.set_id, reason="Ca mổ cấp cứu", station=STATION, client_ts=ts)
		result = call(override_api.request, key=key, **args)
		self.assertTrue(result["ok"])
		summary = result["override"]
		self.assertEqual(
			(summary["status"], summary["set_unit"], summary["reason"]),
			("Requested", ready.set_id, "Ca mổ cấp cứu"),
		)
		self.assertEqual(frappe.db.get_value("Par Override", summary["name"], "station"), STATION)
		# gửi lại cùng khóa: cùng kết quả, không thêm chứng từ
		self.assertEqual(call(override_api.request, key=key, **args), result)
		self.assertEqual(frappe.db.count("Par Override", {"set_unit": ready.set_id}), 1)

	def test_request_rejections_carry_http_status_and_audit(self):
		ready = exhausted()
		fine = make_t4_ready_set(max_cycles=300)
		cases = [
			({"set_id": ready.set_id, "reason": "  "}, "REASON_REQUIRED", 422),
			({"set_id": fine.set_id, "reason": "Không cần"}, "PAR_NOT_EXCEEDED", 409),
			({"set_id": "abc", "reason": "x"}, "SCAN_INVALID", 422),
		]
		for args, code, status in cases:
			before = reject_count()
			result = call(override_api.request, station=STATION, **args)
			assert_rejection(self, result, code, status)
			[row] = rejects_since(before)
			self.assertEqual((row.reason, row.station), (code, STATION), msg=code)
		override.request(ready.set_id, "Lần đầu")
		assert_rejection(
			self,
			call(override_api.request, set_id=ready.set_id, reason="Lần hai", station=STATION),
			"OVERRIDE_PENDING",
			409,
		)

	def test_request_needs_packing_or_r02_role(self):
		ready = exhausted()
		self.as_user("par-api-r03@test.local", roles=("TC R03",))
		with self.assertRaises(frappe.PermissionError):
			call(override_api.request, set_id=ready.set_id, reason="x", station=STATION)
		self.assertEqual(frappe.db.count("Par Override", {"set_unit": ready.set_id}), 0)


class TestDecideRpc(PackApiCase):
	def _pending(self):
		ready = exhausted()
		return ready, override.request(ready.set_id, "Thiếu bộ").name

	def _as(self, user):
		frappe.set_user(user)
		self.addCleanup(frappe.set_user, "Administrator")

	@bru("BRU-PAR-004")
	def test_approve_over_rpc_opens_the_set(self):
		ready, name = self._pending()
		self._as(make_approver("par-api-r01@test.local"))
		result = call(
			override_api.approve,
			override=name,
			extra_cycles=2,
			valid_until=str(add_days(today(), 3)),
			reason="Đồng ý",
			pin=PIN,
		)
		self.assertTrue(result["ok"], result)
		self.assertEqual(result["override"]["status"], "Approved")
		self.assertEqual(result["override"]["extra_cycles"], "2")
		self.assertEqual(frappe.db.get_value("Set Unit", ready.set_id, "status"), "Processing")

	def test_wrong_pin_is_rejected_with_403_and_changes_nothing(self):
		ready, name = self._pending()
		self._as(make_approver("par-api-r01b@test.local"))
		before = reject_count()
		result = call(
			override_api.approve,
			override=name,
			extra_cycles=1,
			valid_until=str(today()),
			reason="x",
			pin="000000",
		)
		assert_rejection(self, result, "PIN_INVALID", 403)
		self.assertGreater(reject_count(), before)
		self.assertEqual(frappe.db.get_value("Par Override", name, "status"), "Requested")
		self.assertEqual(frappe.db.get_value("Set Unit", ready.set_id, "status"), "End of Life")

	def test_validation_errors_over_rpc(self):
		_ready, name = self._pending()
		self._as(make_approver("par-api-r01c@test.local"))
		base = dict(override=name, extra_cycles=1, valid_until=str(today()), reason="x", pin=PIN)
		cases = [
			({"reason": ""}, "REASON_REQUIRED", 422),
			({"extra_cycles": 0}, "EXTRA_CYCLES_INVALID", 422),
			({"valid_until": str(add_days(today(), -1))}, "VALID_UNTIL_INVALID", 422),
			({"override": "GD-0000-00000"}, "OVERRIDE_NOT_FOUND", 404),
		]
		for change, code, status in cases:
			assert_rejection(self, call(override_api.approve, **{**base, **change}), code, status)

	def test_roles_over_rpc(self):
		_ready, name = self._pending()
		r04 = make_approver("par-api-r04@test.local", roles=("TC R04",))
		r02 = make_approver("par-api-r02@test.local", roles=("TC R02",))
		self._as(r04)
		with self.assertRaises(frappe.PermissionError):
			call(
				override_api.approve,
				override=name,
				extra_cycles=1,
				valid_until=str(today()),
				reason="x",
				pin=PIN,
			)
		self._as(r02)  # chưa được ủy quyền
		result = call(override_api.reject, override=name, reason="x", pin=PIN)
		assert_rejection(self, result, "APPROVER_NOT_ALLOWED", 403)
		self.assertEqual(frappe.db.get_value("Par Override", name, "status"), "Requested")

	@bru("BRU-PAR-004")
	def test_reject_over_rpc_keeps_end_of_life(self):
		ready, name = self._pending()
		self._as(make_approver("par-api-r01d@test.local"))
		result = call(override_api.reject, override=name, reason="Bộ đã mòn", pin=PIN)
		self.assertTrue(result["ok"])
		self.assertEqual(result["override"]["status"], "Rejected")
		self.assertEqual(frappe.db.get_value("Set Unit", ready.set_id, "status"), "End of Life")
		self.assertIsNone(http_status())

	def test_request_desk_follows_the_same_rules(self):
		unit = make_set_unit(max_cycles=5).name
		frappe.db.set_value("Set Unit", unit, "cycles_used", 5)
		result = call(override_api.request_desk, set_unit=unit, reason="Desk")
		self.assertTrue(result["ok"])
		self.assertEqual(result["override"]["status"], "Requested")
		again = call(override_api.request_desk, set_unit=unit, reason="Desk")
		assert_rejection(self, again, "OVERRIDE_PENDING", 409)
		self.as_user("par-api-r03b@test.local", roles=("TC R03",))
		with self.assertRaises(frappe.PermissionError):
			call(override_api.request_desk, set_unit=unit, reason="x")
