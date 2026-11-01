"""A-105: R02 chạy RPC trạm theo ma trận phân quyền; năng lực trạm và quy tắc nghiệp vụ vẫn áp dụng như mọi thẻ."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.core import station_auth
from tracecore.core.errors import BlockedError
from tracecore.setup.permissions import load_permission_matrix
from tracecore.tests.factories import make_employee, make_par_level, make_user
from tracecore.v1 import _common, assembly, issue, lookup, pack, putaway, sync, usage
from tracecore.v1.tests import test_issue_api, test_pack_api, test_putaway_api, test_usage_api
from tracecore.v1.tests.station_fixtures import make_station_employee

R02 = "TC R02"
# Tuple RPC của trạm → DocType mà trạm đó ghi, tra ma trận. Sterile Putaway không có dòng riêng: dùng dòng Pack.
STATION_TUPLES = {
	"RECEIVE_ROLES": (_common.RECEIVE_ROLES, "Dirty Receipt"),
	"WASH_LOAD_ROLES": (_common.WASH_LOAD_ROLES, "Wash Batch"),
	"WASH_UNLOAD_ROLES": (_common.WASH_UNLOAD_ROLES, "Wash Batch"),
	"ASSEMBLY_ROLES": (assembly.ASSEMBLY_ROLES, "Assembly Record"),
	"PACKING_ROLES": (_common.PACKING_ROLES, "Pack"),
	"LOAD_ROLES": (_common.LOAD_ROLES, "Sterilization Load"),
	"RELEASE_ROLES": (_common.RELEASE_ROLES, "Sterilization Load"),
	"STORAGE_ROLES": (_common.STORAGE_ROLES, "Pack"),
	"ISSUE_ROLES": (issue.ISSUE_ROLES, "Issue Note"),
	"USAGE_ROLES": (_common.USAGE_ROLES, "Usage Record"),
	"LINEN_ROLES": (_common.LINEN_ROLES, "Linen Collection"),
	"WASTE_ROLES": (_common.WASTE_ROLES, "Waste Collection"),
}


class TestStationTuplesFollowTheMatrix(FrappeTestCase):
	def test_every_station_tuple_includes_r02_when_the_matrix_lets_it_write(self):
		matrix = {row.doctype: row.permissions["R02"] for row in load_permission_matrix()}
		for name, (roles, doctype) in STATION_TUPLES.items():
			with self.subTest(tuple=name, doctype=doctype):
				self.assertIn("W", matrix[doctype])
				self.assertIn(R02, roles)

	def test_only_r02_was_added(self):
		self.assertEqual(set(_common.PACKING_ROLES), {"TC R04", R02, "System Manager"})
		self.assertEqual(set(_common.STORAGE_ROLES), {"TC R06", R02, "System Manager"})
		self.assertEqual(set(_common.USAGE_ROLES), {"TC R08", R02, "System Manager"})
		self.assertEqual(set(putaway.READ_ROLES), set(_common.STORAGE_ROLES))

	def test_reject_and_release_rules_are_unchanged(self):
		self.assertEqual(set(_common.REJECT_ROLES), {R02, "TC R01", "System Manager"})
		self.assertEqual(set(_common.RELEASE_ROLES), {"TC R05", R02, "TC R01", "System Manager"})

	def test_derived_tuples_follow(self):
		for roles in (
			lookup.STEP_ROLES["T4"],
			lookup.STEP_ROLES["T6"],
			lookup.STEP_ROLES["T7"],
			lookup.STEP_ROLES["T8"],
		):
			self.assertIn(R02, roles)
		self.assertIn(R02, sync.SNAPSHOT_ROLES)


class TestR02AtT4(test_pack_api.PackApiCase):
	def test_r02_opens_a_set_and_generates_a_cycle_id(self):
		ready = test_pack_api.make_t4_ready_set()
		self.as_user("r02-t4@example.com", [R02])
		opened = test_pack_api.call(pack.scan, raw=ready.set_id, station=test_pack_api.STATION)
		self.assertIs(opened["ok"], True)
		done = test_pack_api.call(pack.generate_cycle_id, **test_pack_api.generate_args(ready))
		self.assertIs(done["ok"], True)

	def test_other_role_is_still_refused(self):
		ready = test_pack_api.make_t4_ready_set()
		self.as_user("r03-t4@example.com", ["TC R03"])
		with self.assertRaises(frappe.PermissionError):
			test_pack_api.call(pack.scan, raw=ready.set_id, station=test_pack_api.STATION)


class TestR02AtT6(test_putaway_api.PutawayApiCase):
	def test_r02_stores_a_pack(self):
		self.as_user("r02-t6@example.com", [R02])
		item = test_putaway_api.make_released_pack()
		stored = test_putaway_api.call(
			putaway.scan, raw=self.shelf.name, station=test_putaway_api.STATION, open_pack=item.name
		)
		self.assertIs(stored["ok"], True)
		self.assertEqual(frappe.db.get_value("Pack", item.name, "status"), "In Sterile Stock")


class TestR02AtT7(test_issue_api.IssueApiCase):
	def test_departments_answers_instead_of_403(self):
		self.as_user("r02-t7@example.com", [R02])
		listing = test_issue_api.call(issue.departments, station=test_issue_api.STATION)
		self.assertIn(self.dept, [row["name"] for row in listing["departments"]])

	def test_r02_cannot_skip_the_par_approval_by_being_r02(self):
		test_issue_api.as_administrator(
			make_par_level,
			"Instrument Set Type",
			self.set_type,
			par_kind="Department Stock",
			department=self.dept,
			min_qty=0,
			max_qty=1,
			is_active=1,
		)
		self.as_user("r02-t7@example.com", [R02])
		station = test_issue_api.STATION
		note = self.open_draft()
		for _ in range(2):
			test_issue_api.call(issue.add_pack, issue_note=note, raw=self.stocked().name, station=station)
		test_issue_api.call(issue.sign, issue_note=note, card=self.recipient.tc_card_id, station=station)
		test_issue_api.assert_block(
			self,
			test_issue_api.call(issue.submit, issue_note=note, station=station),
			"PAR_APPROVAL_REQUIRED",
			409,
		)


class TestR02AtT8(test_usage_api.UsageApiCase):
	def as_r02_without_department(self):
		user = self.as_user("r02-t8@example.com", [R02])
		frappe.db.set_value("Employee", {"user_id": user}, "department", None)
		return user

	def test_r02_with_a_department_scans_and_confirms(self):
		self.as_user("r02-t8@example.com", [R02])
		station = test_usage_api.STATION
		card = test_usage_api.call(usage.scan, raw=self.pack.name, station=station)
		self.assertIs(card["ok"], True)

	def test_r02_without_department_gets_a_clear_block(self):
		self.as_r02_without_department()
		station = test_usage_api.STATION
		for fn, args in (
			(usage.overview, {}),
			(usage.scan, {"raw": self.pack.name}),
			(usage.confirm, {"cycle_id": self.pack.name, "surgery_code": "PT-1"}),
		):
			with self.subTest(rpc=fn.__name__):
				result = test_usage_api.call(fn, station=station, **args)
				test_usage_api.assert_block(self, result, "SCANNER_DEPARTMENT_REQUIRED", 409)
				self.assertTrue(result["error"]["reason"])
				self.assertTrue(result["error"]["action"])
		self.assertEqual(frappe.db.get_value("Pack", self.pack.name, "status"), "Issued")


class TestCompetencyStillApplies(FrappeTestCase):
	def test_r02_without_competency_cannot_open_a_session(self):
		frappe.set_user("Administrator")
		user = make_user("r02-chua-nang-luc@example.com", [R02])
		employee = make_station_employee(user)
		with self.assertRaises(BlockedError) as caught:
			station_auth.login(employee.tc_card_id, "TR-007")
		self.assertEqual(caught.exception.block.code, "COMPETENCY_REQUIRED")
		frappe.db.rollback()
