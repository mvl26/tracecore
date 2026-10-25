"""KTV workspace access and queue semantics; no new lifecycle write authority."""

from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase


class TestKtvUI(FrappeTestCase):
	def test_unrelated_role_cannot_open_ktv(self):
		from tracecore.v1.ktv import require_workspace

		with (
			patch("frappe.session", frappe._dict(user="r08@example.test")),
			patch("frappe.get_roles", return_value=["TC R08"]),
		):
			with self.assertRaises(frappe.PermissionError):
				require_workspace("R04", "T3")

	def test_only_t3_t4_are_accepted(self):
		from tracecore.v1.ktv import require_workspace

		with patch("frappe.session", frappe._dict(user="Administrator")):
			with self.assertRaises(frappe.PermissionError):
				require_workspace("R04", "T1")

	def test_queue_uses_current_cycle_not_old_pass(self):
		from tracecore.v1.ktv import queue_candidates

		units = [frappe._dict(name="A", status="Processing", current_cycle_no=2, active_cycle_id=None)]
		old = [frappe._dict(set_unit="A", cycle_no=1, step="T2", result="Pass")]
		self.assertEqual(queue_candidates(units, old, "T3"), [])
		current = [frappe._dict(set_unit="A", cycle_no=2, step="T2", result="Pass")]
		self.assertEqual([row.name for row in queue_candidates(units, current, "T3")], ["A"])

	def test_packed_or_completed_sets_do_not_reenter_queue(self):
		from tracecore.v1.ktv import queue_candidates

		units = [frappe._dict(name="A", status="Processing", current_cycle_no=2, active_cycle_id="CY-1")]
		gates = [frappe._dict(set_unit="A", cycle_no=2, step="T3", result="Pass")]
		self.assertEqual(queue_candidates(units, gates, "T4"), [])
		units[0].active_cycle_id = None
		gates.append(frappe._dict(set_unit="A", cycle_no=2, step="T4", result="Pass"))
		self.assertEqual(queue_candidates(units, gates, "T4"), [])

	def test_personal_requests_use_actual_actor_not_selected_role(self):
		from tracecore.v1.ktv import personal_requests

		with (
			patch("frappe.session", frappe._dict(user="ktv@example.test")),
			patch("frappe.get_roles", return_value=["TC R04"]),
			patch("frappe.has_permission", return_value=True),
			patch("frappe.db.exists", return_value=True),
			patch("frappe.get_list", return_value=[]) as query,
		):
			personal_requests()
		self.assertEqual(query.call_args.kwargs["filters"]["owner"], "ktv@example.test")

	def test_missing_override_service_is_explicit(self):
		from tracecore.v1.ktv import personal_requests

		with patch("tracecore.v1.ktv.require_workspace"), patch("frappe.db.exists", return_value=False):
			self.assertEqual(personal_requests(), {"available": False, "rows": []})

	def test_internal_gates_are_bound_to_readable_parents(self):
		from tracecore.v1.ktv import workspace

		unit = frappe._dict(name="ALLOWED", status="Processing", current_cycle_no=2, active_cycle_id=None)
		with (
			patch("tracecore.v1.ktv.require_workspace"),
			patch("frappe.get_list", side_effect=[[unit], []]),
			patch("frappe.get_all", return_value=[]) as internal,
			patch("frappe.db.has_column", return_value=False),
			patch("frappe.get_meta") as meta,
		):
			meta.return_value.has_field.return_value = False
			workspace()
		self.assertEqual(internal.call_args_list[0].kwargs["filters"]["set_unit"], ["in", ["ALLOWED"]])
		self.assertEqual(
			set(internal.call_args_list[0].kwargs["fields"]), {"set_unit", "cycle_no", "step", "result"}
		)

	def test_context_does_not_read_bom_or_gates_for_inaccessible_unit(self):
		from tracecore.v1.ktv import context

		with (
			patch("tracecore.v1.ktv.require_workspace"),
			patch("tracecore.core.gs1.parse_scan", return_value={"type": "set", "id": "DENIED"}),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.get_all") as internal,
		):
			with patch("tracecore.v1.set_type.bom") as bom:
				with self.assertRaises(frappe.PermissionError):
					context("DENIED")
		# frappe.throw tự tra bản dịch (get_all Translation): chỉ cấm đọc trạng thái cổng và BOM của bộ bị từ chối
		self.assertFalse([call for call in internal.call_args_list if call.args[:1] == ("Step Gate Result",)])
		bom.assert_not_called()

	def test_history_is_scoped_to_current_actor(self):
		from tracecore.v1.ktv import history

		with (
			patch("tracecore.v1.ktv.require_workspace"),
			patch("frappe.session", frappe._dict(user="self@example.test")),
			patch("frappe.has_permission", return_value=True),
			patch("frappe.get_list", return_value=[]) as query,
		):
			history()
		self.assertEqual(len(query.call_args_list), 2)
		for call in query.call_args_list:
			self.assertEqual(call.kwargs["filters"], {"owner": "self@example.test"})

	def test_context_uses_server_instrument_limits_and_current_bom(self):
		from tracecore.v1.ktv import context

		unit = frappe._dict(name="ALLOWED", set_type="TYPE", cycle_bom_version=3, current_cycle_no=2)
		with (
			patch("tracecore.v1.ktv.require_workspace"),
			patch("tracecore.core.gs1.parse_scan", return_value={"type": "set", "id": "ALLOWED"}),
			patch("frappe.get_list", return_value=[unit]),
			patch("frappe.get_all", return_value=[]) as gates,
			patch("tracecore.v1.set_type.bom", return_value={"lines": []}) as bom,
			patch("tracecore.par.check.evaluate", return_value={"state": "blocked"}, create=True),
		):
			payload = context("ALLOWED")
		self.assertEqual(payload["par"]["state"], "blocked")
		bom.assert_called_once_with("TYPE", 3)
		self.assertEqual(gates.call_args.kwargs["filters"], {"set_unit": "ALLOWED", "cycle_no": 2})
