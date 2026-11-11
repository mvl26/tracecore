"""Chỉ số đào tạo KSNK trên HRMS Training (FEAT-059 AC-1..AC-4, AC-6, AC-7; FR-M11-09, FR-M11-10; UC-42; A-135)."""

from unittest.mock import patch

import frappe
from frappe.utils import add_days, add_years, today

from tracecore.core import indicators
from tracecore.infection_program import training
from tracecore.infection_program.tests import ic_fixtures as fx
from tracecore.infection_program.tests import training_fixtures as tf
from tracecore.tests import factories
from tracecore.tests.utils import IsolatedTestCase, bru

BASIC = training.BASIC
CORE = training.CORE_STAFF
NETWORK = training.COMMITTEE_NETWORK


def _period():
	return today()[:7]


def _year():
	return int(today()[:4])


def _row(rows, department):
	return next(row for row in rows if row["department"] == department)


class TestTrainingBasic(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.local.lang = "en"
		self.dept = factories.make_department("KSNK Đào tạo Ngoại")

	def _staff(self, count, prefix="NV"):
		return [fx.employee(f"{prefix} {index}", self.dept) for index in range(count)]

	def test_meta_custom_fields(self):
		category = frappe.get_meta("Training Program").get_field("tc_ic_category")
		self.assertEqual(category.fieldtype, "Select")
		self.assertEqual(category.options.split("\n"), ["", *training.CATEGORIES])
		passed = frappe.get_meta("Training Result Employee").get_field("tc_ic_passed")
		self.assertEqual((passed.fieldtype, passed.default), ("Check", "1"))
		self.assertEqual(
			frappe.get_meta("IC Program Settings").get_field("ic_certificate_types").fieldtype, "Small Text"
		)

	def test_38_of_40_is_95_percent(self):
		staff = self._staff(40)
		tf.trained(staff[:38], BASIC)
		row = _row(training.basic_rows(_year(), self.dept)["departments"], self.dept)
		self.assertEqual((row["employees"], row["trained"]), (40, 38))
		self.assertEqual(row["rate"], 95.0)
		self.assertEqual(row["rate_label"], "95,0 %")
		self.assertEqual(len(row["untrained"]), 2)
		self.assertEqual(training.basic_rate(_period(), self.dept), (38, 40, 40))

	def test_inactive_employee_not_in_denominator(self):
		staff = self._staff(2)
		left = factories.make_employee(
			first_name="NV nghỉ", department=self.dept, status="Left", relieving_date=today()
		).name
		tf.trained([staff[0], left], BASIC)
		self.assertEqual(training.basic_rate(_period(), self.dept), (1, 2, 2))

	def test_results_not_counted(self):
		staff = self._staff(6)
		tf.trained([staff[0]], BASIC, submit=False)  # Training Result chưa ghi sổ
		tf.trained([staff[1]], BASIC, passed=0)  # không đạt
		tf.trained([staff[2]], CORE)  # loại khác KSNK cơ bản
		tf.trained([staff[3]], None)  # chương trình chưa gắn loại (UC-42 E2)
		tf.trained([staff[4]], BASIC, on=add_years(today(), -1))  # lớp năm trước
		data = training.basic_rows(_year(), self.dept)
		self.assertEqual(_row(data["departments"], self.dept)["trained"], 0)
		self.assertGreaterEqual(data["untagged_events"], 1)

	def test_event_without_program_is_untagged(self):
		tf.event(None, employees=self._staff(1))
		self.assertGreaterEqual(training.basic_rows(_year(), self.dept)["untagged_events"], 1)

	@bru("BRU-RPT-001")
	def test_department_without_staff_is_not_calculated(self):
		empty = factories.make_department("KSNK Đào tạo Trống")
		self.assertEqual(training.basic_rate(_period(), empty), (0, 0, 0))
		(row,) = training.basic_rows(_year(), empty)[
			"departments"
		]  # khoa (tc_is_ward) vẫn hiện, "Không tính"
		self.assertEqual((row["employees"], row["rate"], row["status"]), (0, None, "na"))
		self.assertEqual(row["rate_label"], "—")
		status, label = training.rate_status(None, 80)
		self.assertEqual((status, label), ("na", "Not calculated"))

	def test_rate_status_against_target(self):
		self.assertEqual(training.rate_status(85.0, 80)[0], "ok")
		self.assertEqual(training.rate_status(79.9, 80), ("below", "Below target"))
		self.assertEqual(training.rate_status(50.0, None), ("none", "No target"))

	def test_target_from_indicator_catalog(self):
		self.assertIsNone(training.basic_target())
		frappe.get_doc(
			{
				"doctype": "IC Indicator",
				"code": "KSNK-DT-TEST",
				"indicator_name": "Đào tạo KSNK cơ bản",
				"measure_group": frappe.get_meta("IC Indicator")
				.get_field("measure_group")
				.options.split("\n")[0],
				"kind": "Percentage",
				"source_method": training.KEY_BASIC,
				"frequency": "Yearly",
				"national_target": 80,
				"target_direction": "Higher is better",
				"is_active": 1,
			}
		).insert(ignore_permissions=True)
		self.assertEqual(training.basic_target(), 80)

	def test_indicator_registry_has_training_keys(self):
		registry = indicators.registry()
		for key in (training.KEY_BASIC, training.KEY_CORE, training.KEY_TRAINEE):
			self.assertIn(key, registry)
		self.assertIs(registry[training.KEY_BASIC], training.basic_rate)


class TestTrainingCore(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		frappe.local.lang = "en"
		fx.clear_required_departments()
		frappe.db.delete("IC Network Member")
		fx.settings(staff=())
		tf.accept_certificates("Chứng chỉ KSNK cơ bản")
		self.dept = factories.make_department("KSNK Đào tạo Mạng lưới")

	def _people(self, rows):
		return {row["employee"]: row for row in rows}

	@bru("BRU-ICP-001")
	def test_network_member_without_training_or_certificate_fails(self):
		emp = fx.employee("ML chưa học", self.dept)
		fx.network_member(emp, self.dept, "Nurse")
		people = self._people(training.core_rows(_year(), self.dept)["people"])
		self.assertFalse(people[emp]["passed"])
		self.assertEqual(training.core_rate(_period(), self.dept), (0, 1, 1))

	def test_network_member_trained_with_right_category_passes(self):
		emp = fx.employee("ML đã học", self.dept)
		fx.network_member(emp, self.dept, "Doctor")
		tf.trained([emp], NETWORK)
		people = self._people(training.core_rows(_year(), self.dept)["people"])
		self.assertTrue(people[emp]["passed"])
		self.assertEqual(people[emp]["basis"], "training")

	@bru("BRU-ICP-001")
	def test_full_time_staff_needs_full_time_category(self):
		emp = fx.employee("GSV chuyên trách", self.dept)
		fx.settings(staff=[(emp, 1, 1)])
		tf.trained([emp], NETWORK)
		self.assertFalse(self._people(training.core_rows(_year(), self.dept)["people"])[emp]["passed"])
		tf.trained([emp], CORE)
		self.assertTrue(self._people(training.core_rows(_year(), self.dept)["people"])[emp]["passed"])

	def test_part_time_staff_is_not_a_target(self):
		emp = fx.employee("GSV kiêm nhiệm", self.dept)
		fx.settings(staff=[(emp, 0, 1)])
		self.assertNotIn(emp, self._people(training.core_rows(_year(), self.dept)["people"]))

	def test_valid_accepted_certificate_counts_for_core_not_basic(self):
		emp = fx.employee("ML có chứng chỉ", self.dept)
		fx.network_member(emp, self.dept, "Nurse")
		tf.certificate(emp, "chứng chỉ ksnk cơ bản")  # so khớp không phân biệt hoa thường
		person = self._people(training.core_rows(_year(), self.dept)["people"])[emp]
		self.assertTrue(person["passed"])
		self.assertEqual(person["basis"], "certificate")
		self.assertEqual(training.basic_rate(_period(), self.dept)[0], 0)

	def test_certificate_not_accepted_or_expired_does_not_count(self):
		other = fx.employee("ML chứng chỉ khác", self.dept)
		expired = fx.employee("ML chứng chỉ hết hạn", self.dept)
		for emp in (other, expired):
			fx.network_member(emp, self.dept, "Nurse")
		tf.certificate(other, "Vận hành lò hấp")
		tf.certificate(expired, "Chứng chỉ KSNK cơ bản", expires_on=add_days(today(), -1))
		people = self._people(training.core_rows(_year(), self.dept)["people"])
		self.assertFalse(people[other]["passed"])
		self.assertFalse(people[expired]["passed"])

	def test_person_in_committee_and_network_counted_once(self):
		members = fx.full_committee_members("DT")
		chair = members[0][0]
		frappe.db.set_value("Employee", chair, "department", self.dept)
		fx.committee(members, submit=True)
		fx.network_member(chair, self.dept, "Doctor")
		people = training.core_rows(_year(), self.dept)["people"]
		mine = [row for row in people if row["employee"] == chair]
		self.assertEqual(len(mine), 1)
		self.assertEqual(set(mine[0]["groups"]), {"committee", "network"})


class TestTrainingReminder(IsolatedTestCase):
	def setUp(self):
		super().setUp()
		self.addCleanup(frappe.set_user, "Administrator")
		self.dept = factories.make_department("KSNK Đào tạo Nhắc")

	def test_reminds_only_untrained_users(self):
		learner = factories.make_user("ksnk-train-learner@example.com")
		done = factories.make_user("ksnk-train-done@example.com")
		untrained = fx.employee("Chưa học", self.dept, user=learner)
		trained = fx.employee("Đã học", self.dept, user=done)
		fx.employee("Không tài khoản", self.dept)
		tf.trained([trained], BASIC)
		with patch.object(training.notification, "emit", return_value=[learner]) as emit:
			result = training.remind(self.dept, _year())
		emit.assert_called_once()
		self.assertEqual(emit.call_args.args[0], "IC_TRAINING_REMINDER")
		self.assertEqual(list(emit.call_args.kwargs["users"]), [learner])
		self.assertNotIn(untrained, str(emit.call_args.kwargs.get("message")))  # không lộ mã nhân viên khác
		self.assertEqual(result, {"untrained": 2, "sent": 1, "without_account": 1})

	def test_nothing_to_remind(self):
		with patch.object(training.notification, "emit") as emit:
			result = training.remind(self.dept, _year())
		emit.assert_not_called()
		self.assertEqual(result["untrained"], 0)
