"""Đề nghị - duyệt - tiêu thụ - hết hiệu lực ghi đè cơ số (FEAT-032, UC-31, WF-08, A-18 Q4-Q12)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, getdate, today

from tracecore.core import station_auth, step_gate
from tracecore.core.errors import BlockedError
from tracecore.par import check, override
from tracecore.par.tests.test_check import hook_ctx, make_par_scene
from tracecore.tests.factories import make_cycle, make_user
from tracecore.tests.utils import IsolatedTestCase, bru
from tracecore.v1.tests.station_fixtures import make_station_employee

test_ignore = ["Item", "Batch", "Department", "User", "Employee"]

PIN = "246810"


def make_approver(email="par-r01@test.local", roles=("TC R01",), pin=PIN):
	"""User có role ``roles`` và Employee có PIN (duyệt trên Desk, A-18 Q7)."""
	user = make_user(email, roles=roles)
	employee = make_station_employee(user)
	if pin:
		station_auth.set_pin(employee.name, pin)
	return user


def exceeded_set(used=300, max_cycles=300, **kwargs):
	"""Bộ đã dùng hết cơ số và đã bị T4 chuyển Hết vòng đời."""
	unit, codes = make_par_scene(used=used, max_cycles=max_cycles, **kwargs)
	check.check_pack(hook_ctx(unit))
	return unit, codes


def blocked(testcase, fn, *args, **kwargs):
	with testcase.assertRaises(BlockedError) as raised:
		fn(*args, **kwargs)
	return raised.exception.block


class OverrideCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		frappe.set_user("Administrator")
		self.addCleanup(frappe.set_user, "Administrator")
		self.approver = make_approver()

	def approve(self, name, extra=2, valid_until=None, reason="Bộ thay thế chưa về", pin=PIN, user=None):
		frappe.set_user(user or self.approver)
		try:
			return override.approve(name, extra, valid_until or add_days(today(), 7), reason, pin)
		finally:
			frappe.set_user("Administrator")


class TestRequest(OverrideCase):
	@bru("BRU-PAR-004")
	def test_request_creates_requested_override_with_snapshot(self):
		unit, _codes = exceeded_set(caps={"A": 100, "B": None}, used=300)
		doc = override.request(unit, "  Ca mổ cấp cứu chiều nay  ", station="TR-004")
		self.assertTrue(doc.name.startswith("GD-"))
		self.assertEqual((doc.status, doc.docstatus), ("Requested", 0))
		self.assertEqual((doc.set_unit, doc.cycles_used, doc.max_cycles), (unit, 300, 300))
		self.assertEqual(doc.reason, "Ca mổ cấp cứu chiều nay")
		self.assertEqual((doc.requested_by, doc.station), ("Administrator", "TR-004"))
		self.assertTrue(doc.requested_at)
		self.assertIn("100", doc.exceeded_instruments)
		self.assertEqual(doc.set_type, frappe.db.get_value("Set Unit", unit, "set_type"))
		self.assertTrue(frappe.db.exists("Audit Log", {"ref_doctype": "Par Override", "ref_name": doc.name}))

	def test_request_notifies_r01_and_delegate(self):
		delegate = make_user("par-r02-delegate@test.local", roles=("TC R02",))
		frappe.db.set_single_value("TraceCore Settings", "par_override_delegate", delegate)
		unit, _codes = exceeded_set()
		doc = override.request(unit, "Thiếu bộ")
		recipients = frappe.get_all(
			"Notification Log",
			filters={"document_type": "Par Override", "document_name": doc.name},
			pluck="for_user",
		)
		self.assertIn(self.approver, recipients)
		self.assertIn(delegate, recipients)

	@bru("BRU-PAR-004")
	def test_request_requires_reason(self):
		unit, _codes = exceeded_set()
		for reason in ("", "   ", None):
			self.assertEqual(blocked(self, override.request, unit, reason).code, "REASON_REQUIRED")
		self.assertFalse(frappe.db.exists("Par Override", {"set_unit": unit}))

	def test_request_only_for_exceeded_set(self):
		unit, _codes = make_par_scene(used=10)
		block = blocked(self, override.request, unit, "Không cần")
		self.assertEqual((block.code, block.http_status), ("PAR_NOT_EXCEEDED", 409))

	def test_request_allowed_for_end_of_life_set_even_if_counter_looks_fine(self):
		unit, _codes = make_par_scene(used=10)
		step_gate.end_of_life(unit)  # Hết vòng đời từ nguồn khác (vd từ chối trước)
		self.assertEqual(override.request(unit, "Đề nghị lại").status, "Requested")

	def test_one_open_override_per_set(self):
		unit, _codes = exceeded_set()
		first = override.request(unit, "Lần 1")
		block = blocked(self, override.request, unit, "Lần 2")
		self.assertEqual(block.code, "OVERRIDE_PENDING")
		self.assertIn(first.name, block.reason)
		self.approve(first.name)
		self.assertEqual(
			blocked(self, override.request, unit, "Lần 3").code, "OVERRIDE_PENDING"
		)  # ghi đè đang hiệu lực

	def test_desk_insert_follows_the_same_rules(self):
		unit, _codes = make_par_scene(used=10)
		doc = frappe.get_doc({"doctype": "Par Override", "set_unit": unit, "reason": "Desk"})
		with self.assertRaises(BlockedError):
			doc.insert()
		exceeded, _codes = exceeded_set()
		doc = frappe.get_doc({"doctype": "Par Override", "set_unit": exceeded, "reason": "Desk"}).insert()
		self.assertEqual((doc.status, doc.requested_by, doc.cycles_used), ("Requested", "Administrator", 300))

	def test_pending_request_is_named_when_t4_blocks_again(self):
		unit, _codes = make_par_scene(used=300)
		frappe.db.set_value("Set Unit", unit, "status", "Processing")
		doc = override.request(unit, "Chờ duyệt")
		block = check.check_pack(hook_ctx(unit))
		self.assertEqual(block.code, "PAR_EXCEEDED")
		self.assertIn(doc.name, block.action)


class TestDecision(OverrideCase):
	@bru("BRU-PAR-004")
	def test_approve_opens_set_within_extra_cycles_and_date(self):
		unit, _codes = exceeded_set()
		name = override.request(unit, "Thiếu bộ").name
		doc = self.approve(name, extra=2, valid_until=add_days(today(), 3), reason="  Đồng ý 2 chu trình ")
		self.assertEqual((doc.status, doc.docstatus), ("Approved", 1))
		self.assertEqual((doc.extra_cycles, getdate(doc.valid_until)), (2, getdate(add_days(today(), 3))))
		self.assertEqual(
			(doc.decided_by, doc.decision_reason, doc.pin_verified), (self.approver, "Đồng ý 2 chu trình", 1)
		)
		self.assertTrue(doc.decided_by_employee and doc.decided_at)
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "Processing")
		par = check.evaluate(unit)
		self.assertEqual(par["state"], "override")
		self.assertEqual(par["override"]["name"], name)
		self.assertIsNone(check.check_pack(hook_ctx(unit)))
		self.assertIsNone(step_gate.check(unit, "T4"))

	@bru("BRU-PAR-004")
	def test_only_r01_or_delegated_r02_decides(self):
		unit, _codes = exceeded_set()
		name = override.request(unit, "Thiếu bộ").name
		r04 = make_approver("par-r04@test.local", roles=("TC R04",))
		r02 = make_approver("par-r02@test.local", roles=("TC R02",))
		sysman = make_approver("par-sm@test.local", roles=("System Manager",))
		for user in (r04, r02, sysman):
			block = blocked(self, self.approve, name, user=user)
			self.assertEqual((block.code, block.http_status), ("APPROVER_NOT_ALLOWED", 403), msg=user)
		frappe.db.set_single_value("TraceCore Settings", "par_override_delegate", r02)
		self.assertEqual(self.approve(name, user=r02).status, "Approved")

	@bru("BRU-PAR-004")
	def test_decision_needs_reason_cycles_date_and_pin(self):
		unit, _codes = exceeded_set()
		name = override.request(unit, "Thiếu bộ").name
		cases = [
			({"reason": "  "}, "REASON_REQUIRED"),
			({"extra": 0}, "EXTRA_CYCLES_INVALID"),
			({"extra": "2a"}, "EXTRA_CYCLES_INVALID"),
			({"valid_until": add_days(today(), -1)}, "VALID_UNTIL_INVALID"),
			({"valid_until": "not-a-date"}, "VALID_UNTIL_INVALID"),
			({"pin": "000000"}, "PIN_INVALID"),
		]
		for kwargs, code in cases:
			self.assertEqual(blocked(self, self.approve, name, **kwargs).code, code, msg=kwargs)
			station_auth.clear_pin_rate_limit(frappe.db.get_value("Employee", {"user_id": self.approver}))
		self.assertEqual(frappe.db.get_value("Par Override", name, "status"), "Requested")
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "End of Life")

	def test_approver_without_pin_is_rejected(self):
		unit, _codes = exceeded_set()
		name = override.request(unit, "Thiếu bộ").name
		nopin = make_approver("par-nopin@test.local", pin=None)
		self.assertEqual(blocked(self, self.approve, name, user=nopin).code, "PIN_INVALID")
		nobody = make_user("par-noemp@test.local", roles=("TC R01",))
		self.assertEqual(blocked(self, self.approve, name, user=nobody).code, "PIN_INVALID")

	def test_valid_until_today_is_allowed(self):
		unit, _codes = exceeded_set()
		name = override.request(unit, "Thiếu bộ").name
		self.assertEqual(self.approve(name, valid_until=today()).status, "Approved")
		self.assertEqual(check.evaluate(unit)["state"], "override")

	def test_reject_keeps_set_end_of_life(self):
		unit, _codes = exceeded_set()
		name = override.request(unit, "Thiếu bộ").name
		frappe.set_user(self.approver)
		block = blocked(self, override.reject, name, "", PIN)
		self.assertEqual(block.code, "REASON_REQUIRED")
		doc = override.reject(name, "Bộ đã mòn, thanh lý", PIN)
		frappe.set_user("Administrator")
		self.assertEqual(
			(doc.status, doc.docstatus, doc.decision_reason), ("Rejected", 1, "Bộ đã mòn, thanh lý")
		)
		self.assertEqual(frappe.db.get_value("Set Unit", unit, "status"), "End of Life")
		self.assertEqual(check.evaluate(unit)["state"], "blocked")
		# được đề nghị lại sau khi bị từ chối (A-18 Q5)
		self.assertEqual(override.request(unit, "Đề nghị lại").status, "Requested")

	def test_decide_only_pending(self):
		unit, _codes = exceeded_set()
		name = override.request(unit, "Thiếu bộ").name
		self.approve(name)
		self.assertEqual(blocked(self, self.approve, name).code, "OVERRIDE_NOT_PENDING")
		frappe.set_user(self.approver)
		self.assertEqual(blocked(self, override.reject, name, "x", PIN).code, "OVERRIDE_NOT_PENDING")
		self.assertEqual(
			blocked(self, override.approve, "GD-0000-00000", 1, today(), "x", PIN).code, "OVERRIDE_NOT_FOUND"
		)

	def test_manual_submit_and_status_edit_are_blocked(self):
		unit, _codes = exceeded_set()
		doc = override.request(unit, "Thiếu bộ")
		doc.status = "Approved"
		with self.assertRaises(frappe.ValidationError):
			doc.submit()
		self.approve(doc.name)
		doc = frappe.get_doc("Par Override", doc.name)
		doc.extra_cycles = 99
		with self.assertRaises(frappe.ValidationError):
			doc.save()

	@bru("BRU-PAR-004")
	def test_override_cannot_be_deleted(self):
		unit, _codes = exceeded_set()
		doc = override.request(unit, "Thiếu bộ")
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Par Override", doc.name, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Par Override", doc.name))


class TestConsumeAndExpire(OverrideCase):
	def _approved(self, extra=2, valid_until=None):
		unit, _codes = exceeded_set()
		name = override.request(unit, "Thiếu bộ").name
		self.approve(name, extra=extra, valid_until=valid_until)
		return unit, name

	def _pack(self, unit, cycle_no=None):
		ctx = hook_ctx(unit)
		ctx.update(check.pack_context(ctx))
		pack = frappe._dict(set_unit=unit, cycle_no=cycle_no or ctx["set_unit"]["current_cycle_no"])
		override.consume(pack, ctx)

	@bru("BRU-PAR-004")
	def test_each_cycle_consumes_one_and_last_one_expires(self):
		unit, name = self._approved(extra=2)
		self._pack(unit)
		self._pack(unit)  # void + đóng gói lại cùng chu trình: không trừ thêm
		row = frappe.db.get_value(
			"Par Override", name, ["status", "cycles_consumed", "last_cycle_no"], as_dict=True
		)
		self.assertEqual((row.status, row.cycles_consumed, row.last_cycle_no), ("Approved", 1, 1))

		make_cycle(unit)  # chu trình 2 (T1..T3 Đạt)
		self.assertEqual(check.evaluate(unit)["state"], "override")
		self._pack(unit)
		row = frappe.db.get_value(
			"Par Override", name, ["status", "cycles_consumed", "expiry_cause", "expired_at"], as_dict=True
		)
		self.assertEqual((row.status, row.cycles_consumed, row.expiry_cause), ("Expired", 2, "Cycles Used"))
		self.assertTrue(row.expired_at)
		# cùng chu trình vẫn đóng lại được (void rồi đóng gói lại); chu trình sau bị chặn
		self.assertEqual(check.evaluate(unit)["state"], "override")
		make_cycle(unit)
		self.assertEqual(check.evaluate(unit)["state"], "blocked")
		self.assertEqual(check.check_pack(hook_ctx(unit)).code, "PAR_EXCEEDED")

	def test_consume_ignores_packs_without_override(self):
		unit, _codes = make_par_scene(used=10)
		self._pack(unit)  # không lỗi, không ghi gì
		self.assertFalse(frappe.db.exists("Par Override", {"set_unit": unit}))

	@bru("BRU-PAR-004")
	def test_expire_overdue_after_valid_until(self):
		unit, name = self._approved(valid_until=today())
		override.expire_overdue()  # còn hôm nay
		self.assertEqual(frappe.db.get_value("Par Override", name, "status"), "Approved")
		frappe.db.set_value("Par Override", name, "valid_until", add_days(today(), -1))
		override.expire_overdue()
		row = frappe.db.get_value("Par Override", name, ["status", "expiry_cause"], as_dict=True)
		self.assertEqual((row.status, row.expiry_cause), ("Expired", "Date Passed"))
		self.assertEqual(check.evaluate(unit)["state"], "blocked")
		self.assertTrue(
			frappe.db.exists(
				"Audit Log", {"ref_doctype": "Par Override", "ref_name": name, "action": "Update"}
			)
		)

	def test_date_passed_override_is_not_active_even_before_cron(self):
		unit, name = self._approved()
		frappe.db.set_value("Par Override", name, "valid_until", add_days(today(), -1))
		self.assertEqual(check.evaluate(unit)["state"], "blocked")

	def test_cancel_revokes_approved_override(self):
		unit, name = self._approved()
		doc = frappe.get_doc("Par Override", name)
		doc.cancel()
		self.assertEqual(frappe.db.get_value("Par Override", name, "status"), "Cancelled")
		self.assertEqual(check.evaluate(unit)["state"], "blocked")

	def test_monthly_report_notification_goes_to_r01(self):
		with patch.object(override, "_r01_users", return_value=[self.approver]):
			override.notify_monthly_report()
		logs = frappe.get_all(
			"Notification Log",
			filters={"for_user": self.approver},
			fields=["subject", "link"],
			order_by="creation desc",
		)
		self.assertTrue(logs)
		self.assertIn("Par Override Report", logs[0].link)
