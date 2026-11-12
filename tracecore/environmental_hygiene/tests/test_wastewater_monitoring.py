"""Đợt quan trắc nước thải: nạp thông số theo GPMT tại ngày lấy mẫu, so giới hạn, KPH, phiếu kết quả, VIMCERTS; Không
đạt → cờ điểm, quan trắc lại, thông báo, NC (FEAT-095; FR-M15-10, .1, FR-M15-11, FR-M15-13, .1; BRU-ENV-003..005;
AC-095-07..11, 13; A-153 W4, W5)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from tracecore.core.errors import BlockedError
from tracecore.environmental_hygiene import wastewater
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.factories import make_user
from tracecore.tests.utils import IsolatedTestCase, bru

PASSING = {"pH": 7.1, "COD": 48, "Coliforms": 3000, "Salmonella": "KPH"}


class MonitoringCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.owner = make_user("ww-owner@example.com", ["TC R11"])
		self.r01 = make_user("ww-r01@example.com", ["TC R01"])
		frappe.db.set_single_value("IC Program Settings", "ic_department", ef.make_department("T Khoa KSNK"))
		self.point = ef.make_point(user=self.owner).name
		self.permit = ef.make_permit("T-QT", rows=ef.rows_for(self.point))
		self.lab = ef.make_lab()


class TestCompareWithPermit(MonitoringCase):
	@bru("BRU-ENV-004")
	def test_parameters_are_loaded_from_permit_in_effect_without_auto_rows(self):
		doc = frappe.new_doc("Wastewater Monitoring")
		doc.update({"wastewater_point": self.point, "sampled_on": "2026-10-20"})
		wastewater.load_parameters(doc)
		self.assertEqual([row.parameter for row in doc.results], ["pH", "COD", "Coliforms", "Salmonella"])
		self.assertEqual(doc.wastewater_permit, self.permit.name)

	@bru("BRU-ENV-005")
	def test_ph_out_of_range_fails_and_kph_passes(self):
		"""AC-095-07."""
		doc = ef.make_monitoring(self.point, {**PASSING, "pH": 9.2, "COD": "KPH"})
		results = {row.parameter: row for row in doc.results}
		self.assertEqual(results["pH"].result, "Fail")
		self.assertEqual(results["COD"].result, "Pass")
		self.assertIn("GPMT-T-QT-V1", results["pH"].limit_applied)
		self.assertIn("6 - 9", results["pH"].limit_applied)
		self.assertEqual(doc.overall_result, "Fail")
		self.assertEqual(doc.standard_applied, "QCVN 28:2010/BTNMT · B")

	@bru("BRU-ENV-005")
	def test_detect_only_parameter_with_a_value_fails(self):
		doc = ef.make_monitoring(self.point, {**PASSING, "Salmonella": 2})
		self.assertEqual({r.parameter: r.result for r in doc.results}["Salmonella"], "Fail")
		self.assertEqual(doc.overall_result, "Fail")

	@bru("BRU-ENV-005")
	def test_kph_below_a_lower_limit_fails(self):
		doc = ef.make_monitoring(self.point, {**PASSING, "pH": "KPH"})
		self.assertEqual({r.parameter: r.result for r in doc.results}["pH"], "Fail")

	@bru("BRU-ENV-006")
	def test_missing_parameter_makes_the_round_incomplete(self):
		doc = ef.make_monitoring(self.point, {"pH": 7, "COD": 40, "Salmonella": "KPH"})
		self.assertEqual({r.parameter: r.result for r in doc.results}["Coliforms"], None)
		self.assertEqual(doc.overall_result, "Incomplete")

	def test_all_within_limits_passes_and_period_label_is_set(self):
		doc = ef.make_monitoring(self.point, PASSING)
		self.assertEqual(doc.overall_result, "Pass")
		self.assertTrue(doc.period_label.endswith("4/2026"))
		self.assertEqual(doc.vimcerts_no, "VIMCERTS 112")

	@bru("BRU-ENV-004")
	def test_new_permit_version_after_sampling_does_not_change_old_result(self):
		"""AC-095-08."""
		old = ef.make_monitoring(self.point, {**PASSING, "COD": 90}, sampled_on="2026-06-10")
		draft = wastewater.new_version(self.permit.name)
		for row in draft.parameters:
			if row.parameter == "COD":
				row.max_value = 50
		draft.effective_from = "2026-07-01"
		draft.save()
		draft.submit()
		old.reload()
		self.assertEqual((old.overall_result, old.wastewater_permit), ("Pass", self.permit.name))
		new = ef.make_monitoring(self.point, {**PASSING, "COD": 90}, sampled_on="2026-07-10")
		self.assertEqual((new.overall_result, new.wastewater_permit), ("Fail", draft.name))

	def test_inlet_point_values_are_reference_only(self):
		inlet = ef.make_point("T Đầu vào HTXLNT", "Inlet").name
		ef.make_permit("T-IN", rows=ef.rows_for(inlet))
		doc = ef.make_monitoring(inlet, {"pH": 7.4, "COD": 310, "Coliforms": 460000, "Salmonella": 5})
		self.assertEqual(doc.overall_result, "Reference Only")
		self.assertTrue(all(not row.result for row in doc.results))
		self.assertFalse(frappe.db.get_value("Wastewater Point", inlet, "awaiting_remonitor"))

	def test_parameter_not_in_permit_is_kept_without_result(self):
		doc = frappe.get_doc(
			{
				"doctype": "Wastewater Monitoring",
				"wastewater_point": self.point,
				"sampled_on": "2026-10-20",
				"supplier": self.lab,
				"report_no": "X",
				"attachment": ef.ATTACHMENT,
				"results": [{"parameter": "Nitrat", "value": 6}],
			}
		).insert(ignore_permissions=True)
		row = {r.parameter: r for r in doc.results}["Nitrat"]
		self.assertEqual((row.result, row.limit_applied), (None, "—"))
		self.assertEqual(doc.overall_result, "Incomplete")


class TestMonitoringGuards(MonitoringCase):
	def _code(self, fn):
		with self.assertRaises(BlockedError) as raised:
			fn()
		return raised.exception.block.code

	def test_attachment_is_required_to_post(self):
		"""AC-095-09, FR-M15-10.1."""
		doc = ef.make_monitoring(self.point, PASSING, submit=False, attach=False)
		self.assertEqual(self._code(doc.submit), "WW_REPORT_FILE_REQUIRED")

	def test_lab_without_or_with_expired_vimcerts_is_blocked(self):
		"""AC-095-13, FR-M15-13."""
		expired = ef.make_lab("T Công ty Phân tích B", "VIMCERTS 087", "2026-10-01")
		code = self._code(
			lambda: ef.make_monitoring(self.point, PASSING, sampled_on="2026-10-05", lab=expired)
		)
		self.assertEqual(code, "WW_VIMCERTS_EXPIRED")
		ef.make_monitoring(self.point, PASSING, sampled_on="2026-09-30", lab=expired)
		missing = ef.make_lab("T Phòng XN không chứng nhận", None, None)
		self.assertEqual(
			self._code(lambda: ef.make_monitoring(self.point, PASSING, lab=missing)), "WW_VIMCERTS_MISSING"
		)

	def test_no_permit_in_effect_blocks(self):
		self.assertEqual(
			self._code(lambda: ef.make_monitoring(self.point, PASSING, sampled_on="2025-12-01")),
			"WW_PERMIT_MISSING",
		)

	def test_sampling_date_cannot_be_in_the_future(self):
		self.assertEqual(
			self._code(lambda: ef.make_monitoring(self.point, PASSING, sampled_on=add_days(today(), 1))),
			"WW_SAMPLE_DATE_INVALID",
		)


class TestFailedRound(MonitoringCase):
	@bru("BRU-ENV-003")
	def test_failed_round_flags_point_creates_task_notifies_and_suggests_nc(self):
		"""AC-095-10, FR-M15-11."""
		with patch("tracecore.core.notification.emit") as emit:
			doc = ef.make_monitoring(self.point, {**PASSING, "Coliforms": 9300})
		self.assertEqual((doc.overall_result, doc.nc_status), ("Fail", "Suggested"))
		point = frappe.get_doc("Wastewater Point", self.point)
		self.assertEqual((point.awaiting_remonitor, point.flag_monitoring), (1, doc.name))
		todo = frappe.get_all(
			"ToDo",
			filters={"reference_type": "Wastewater Monitoring", "reference_name": doc.name, "status": "Open"},
			pluck="allocated_to",
		)
		self.assertEqual(todo, [self.owner])
		self.assertEqual(emit.call_args.args[0], wastewater.FAILED_EVENT)
		self.assertIn(self.owner, emit.call_args.kwargs["users"])

	@bru("BRU-ENV-003")
	def test_passing_remonitor_clears_flag_and_closes_task(self):
		failed = ef.make_monitoring(self.point, {**PASSING, "Coliforms": 9300})
		again = ef.make_monitoring(self.point, PASSING, is_remonitor_of=failed.name, sampled_on="2026-11-01")
		self.assertEqual(again.overall_result, "Pass")
		self.assertFalse(frappe.db.get_value("Wastewater Point", self.point, "awaiting_remonitor"))
		self.assertFalse(
			frappe.db.exists(
				"ToDo",
				{"reference_type": "Wastewater Monitoring", "reference_name": failed.name, "status": "Open"},
			)
		)

	def test_failing_remonitor_keeps_flag_and_opened_nc(self):
		failed = ef.make_monitoring(self.point, {**PASSING, "Coliforms": 9300})
		incident = wastewater.open_nc(failed.name)
		again = ef.make_monitoring(
			self.point, {**PASSING, "Coliforms": 8000}, is_remonitor_of=failed.name, sampled_on="2026-11-01"
		)
		self.assertEqual((again.nc_status, again.nc_name), ("Opened", incident))
		self.assertEqual(frappe.db.get_value("Wastewater Point", self.point, "flag_monitoring"), again.name)

	def test_remonitor_must_point_to_failed_round_of_same_point(self):
		passed = ef.make_monitoring(self.point, PASSING)
		with self.assertRaises(BlockedError) as raised:
			ef.make_monitoring(self.point, PASSING, is_remonitor_of=passed.name)
		self.assertEqual(raised.exception.block.code, "WW_REMONITOR_INVALID")

	def test_cancel_failed_round_clears_flag(self):
		failed = ef.make_monitoring(self.point, {**PASSING, "Coliforms": 9300})
		failed.cancel()
		self.assertFalse(frappe.db.get_value("Wastewater Point", self.point, "awaiting_remonitor"))


class TestNcDecision(MonitoringCase):
	def test_open_nc_creates_one_environment_incident_from_the_round(self):
		"""AC-095-11."""
		failed = ef.make_monitoring(self.point, {**PASSING, "Coliforms": 9300})
		first = wastewater.open_nc(failed.name)
		self.assertEqual(wastewater.open_nc(failed.name), first)
		incident = frappe.get_doc("Incident CAPA", first)
		self.assertEqual(
			(
				incident.incident_type,
				incident.incident_category,
				incident.source_doctype,
				incident.source_name,
			),
			("Environment Nonconformity", "Environment", "Wastewater Monitoring", failed.name),
		)

	def test_dismiss_needs_reason_and_only_r01_decides(self):
		failed = ef.make_monitoring(self.point, {**PASSING, "Coliforms": 9300})
		with self.assertRaises(BlockedError):
			wastewater.dismiss_nc(failed.name, " ")
		frappe.set_user(self.owner)
		with self.assertRaises(frappe.PermissionError):
			wastewater.dismiss_nc(failed.name, "Lỗi lấy mẫu")
		frappe.set_user(self.r01)
		wastewater.dismiss_nc(failed.name, "Lỗi lấy mẫu")
		self.assertEqual(frappe.db.get_value("Wastewater Monitoring", failed.name, "nc_status"), "Dismissed")
		self.assertTrue(
			frappe.db.exists("Audit Log", {"ref_doctype": "Wastewater Monitoring", "ref_name": failed.name})
		)
