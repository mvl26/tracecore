"""Mẫu môi trường: so ngưỡng tại ngày lấy mẫu, Không đạt → cờ vùng, việc lấy mẫu lại, thông báo, đề nghị NC
(FEAT-070; FR-M15-03, .1, FR-M15-04, .1; BRU-ENV-002, BRU-ENV-003; UC-54 E2, E5; A-148 d)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, today

from tracecore.core.errors import BlockedError
from tracecore.environmental_hygiene import limits, samples, zones
from tracecore.environmental_hygiene.tests import factories as ef
from tracecore.tests.utils import IsolatedTestCase, bru


class SampleCase(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.ward = ef.make_department("XN Khoa Gây mê")
		frappe.db.delete(zones.DOCTYPE, {"department": self.ward})
		self.zone = ef.make_zone(self.ward, area="Phòng mổ XN").name
		self.limit = ef.make_limit("T-PM-KK", value=10)


class TestCompareWithLimit(SampleCase):
	@bru("BRU-ENV-002")
	def test_result_uses_limit_in_effect_on_sampling_date_and_keeps_snapshot(self):
		sample = ef.make_sample(self.zone, 8, sampled_on="2026-10-30")
		self.assertEqual(sample.result, "Pass")
		self.assertEqual(sample.environmental_limit, self.limit.name)
		self.assertIn("NG-T-PM-KK-V1", sample.limit_applied)
		self.assertIn("10", sample.limit_applied)
		self.assertEqual(sample.unit, "CFU/m3")

	@bru("BRU-ENV-002")
	def test_new_limit_after_sampling_does_not_change_old_result(self):
		"""FR-M15-03.1 / UC-54 E2."""
		old = ef.make_sample(self.zone, 8, sampled_on="2026-10-30")
		draft = limits.new_version(self.limit.name)
		draft.limit_value = 5
		draft.effective_from = "2026-11-01"
		draft.save()
		draft.submit()
		old.reload()
		self.assertEqual((old.result, old.environmental_limit), ("Pass", self.limit.name))
		new = ef.make_sample(self.zone, 8, sampled_on="2026-11-02")
		self.assertEqual((new.result, new.environmental_limit), ("Fail", draft.name))

	def test_limit_is_picked_when_only_one_matches(self):
		sample = ef.make_sample(self.zone, 3, code="")
		self.assertEqual(sample.limit_code, "T-PM-KK")

	def test_missing_or_ambiguous_limit_blocks(self):
		with self.assertRaises(BlockedError) as raised:
			ef.make_sample(self.zone, 3, code="", sample_type="Surface")
		self.assertEqual(raised.exception.block.code, "ENV_LIMIT_MISSING")
		ef.make_limit("T-PM-KK2", value=20)
		with self.assertRaises(BlockedError) as raised:
			ef.make_sample(self.zone, 3, code="")
		self.assertEqual(raised.exception.block.code, "ENV_LIMIT_AMBIGUOUS")
		with self.assertRaises(BlockedError) as raised:
			ef.make_sample(self.zone, 3, sampled_on="2025-12-01")
		self.assertEqual(raised.exception.block.code, "ENV_LIMIT_MISSING")

	def test_limit_of_other_risk_level_is_not_used(self):
		other = ef.make_level("T Thấp", minimum=1, high=0, order=10)
		ef.make_limit("T-BM-THAP", value=50, sample_type="Surface", applies_to_risk_level=other)
		with self.assertRaises(BlockedError) as raised:
			ef.make_sample(self.zone, 3, code="", sample_type="Surface")
		self.assertEqual(raised.exception.block.code, "ENV_LIMIT_MISSING")
		with self.assertRaises(BlockedError) as raised:
			ef.make_sample(self.zone, 3, code="T-BM-THAP", sample_type="Surface")
		self.assertEqual(raised.exception.block.code, "ENV_LIMIT_MISSING")

	def test_sampling_date_cannot_be_in_the_future(self):
		with self.assertRaises(BlockedError) as raised:
			ef.make_sample(self.zone, 3, sampled_on=add_days(today(), 1))
		self.assertEqual(raised.exception.block.code, "ENV_SAMPLE_DATE_INVALID")


class TestFailedSample(SampleCase):
	@bru("BRU-ENV-003")
	def test_failed_sample_flags_zone_creates_resample_task_notifies_and_suggests_nc(self):
		with patch("tracecore.core.notification.emit") as emit:
			sample = ef.make_sample(self.zone, 24)
		self.assertEqual((sample.result, sample.nc_status), ("Fail", "Suggested"))
		zone = frappe.get_doc(zones.DOCTYPE, self.zone)
		self.assertEqual((zone.awaiting_resample, zone.flag_sample), (1, sample.name))
		self.assertTrue(
			frappe.db.exists(
				"ToDo",
				{"reference_type": samples.DOCTYPE, "reference_name": sample.name, "status": "Open"},
			)
		)
		self.assertEqual(emit.call_args.args[0], samples.FAILED_EVENT)

	@bru("BRU-ENV-003")
	def test_passing_resample_clears_flag_and_closes_task(self):
		failed = ef.make_sample(self.zone, 24)
		resample = ef.make_sample(self.zone, 4, is_resample_of=failed.name)
		self.assertEqual(resample.result, "Pass")
		self.assertFalse(frappe.db.get_value(zones.DOCTYPE, self.zone, "awaiting_resample"))
		self.assertFalse(
			frappe.db.exists(
				"ToDo", {"reference_type": samples.DOCTYPE, "reference_name": failed.name, "status": "Open"}
			)
		)

	@bru("BRU-ENV-003")
	def test_failing_resample_keeps_flag_and_nc_and_opens_new_task(self):
		"""UC-54 E5: mẫu lại vẫn Không đạt → NC giữ mở, tạo tiếp việc lấy mẫu lại, cờ vùng giữ nguyên."""
		failed = ef.make_sample(self.zone, 24)
		incident = samples.open_nc(failed.name)
		again = ef.make_sample(self.zone, 30, is_resample_of=failed.name)
		self.assertEqual((again.nc_status, again.nc_name), ("Opened", incident))
		self.assertEqual(frappe.db.get_value(zones.DOCTYPE, self.zone, "flag_sample"), again.name)
		self.assertTrue(
			frappe.db.exists(
				"ToDo", {"reference_type": samples.DOCTYPE, "reference_name": again.name, "status": "Open"}
			)
		)
		ef.make_sample(self.zone, 2, is_resample_of=again.name)
		self.assertFalse(frappe.db.get_value(zones.DOCTYPE, self.zone, "awaiting_resample"))

	def test_resample_must_point_to_failed_sample_of_same_zone(self):
		passed = ef.make_sample(self.zone, 3)
		with self.assertRaises(BlockedError) as raised:
			ef.make_sample(self.zone, 3, is_resample_of=passed.name)
		self.assertEqual(raised.exception.block.code, "ENV_RESAMPLE_INVALID")

	def test_cancel_failed_sample_clears_flag(self):
		failed = ef.make_sample(self.zone, 24)
		failed.cancel()
		self.assertFalse(frappe.db.get_value(zones.DOCTYPE, self.zone, "awaiting_resample"))

	def test_open_nc_creates_environment_incident_once(self):
		failed = ef.make_sample(self.zone, 24)
		first = samples.open_nc(failed.name)
		self.assertEqual(samples.open_nc(failed.name), first)
		incident = frappe.get_doc("Incident CAPA", first)
		self.assertEqual(
			(incident.incident_type, incident.incident_category, incident.department),
			("Environment Nonconformity", "Environment", self.ward),
		)
		self.assertEqual(frappe.db.get_value(samples.DOCTYPE, failed.name, "nc_status"), "Opened")

	def test_dismiss_nc_needs_reason(self):
		failed = ef.make_sample(self.zone, 24)
		with self.assertRaises(BlockedError):
			samples.dismiss_nc(failed.name, "")
		samples.dismiss_nc(failed.name, "Lỗi lấy mẫu, đã lấy lại")
		self.assertEqual(frappe.db.get_value(samples.DOCTYPE, failed.name, "nc_status"), "Dismissed")
		with self.assertRaises(BlockedError):
			samples.open_nc(failed.name)

	def test_only_r01_r11_decide_nc(self):
		from tracecore.tests.factories import make_user

		failed = ef.make_sample(self.zone, 24)
		frappe.set_user(make_user("xn-r02@example.com", [ef.R02]))
		with self.assertRaises(frappe.PermissionError):
			samples.open_nc(failed.name)

	def test_notify_reaches_department_network_and_vendor_portal_users(self):
		from tracecore.compliance_audit.tests.factories import make_dept_user

		member = make_dept_user("xn-r12@example.com", ef.R12, self.ward)
		zone = frappe.get_doc(zones.DOCTYPE, self.zone)
		self.assertIn(member, samples.responsible_users(zone))

	def test_badges_count_pending_nc_and_flagged_zones(self):
		ef.make_sample(self.zone, 24)
		self.assertGreaterEqual(samples.badges("Administrator")[samples.BADGE_SLUG], 1)
		from tracecore.tests.factories import make_user

		self.assertEqual(samples.badges(make_user("xn-r13@example.com", [ef.R13])), {})
