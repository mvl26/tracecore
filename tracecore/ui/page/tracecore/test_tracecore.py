from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.v1.navigation import context as get_context


def fake_screen_tabs(functions):
	"""Chức năng có màn thì có tab; Rửa thủ công không có màn."""
	return [{"key": "screen", "label": "screen"}] if set(functions) - {"MANUAL_WASH"} else []


class TestLauncher(FrappeTestCase):
	def test_management_menu_contains_tracecore_operations_not_sample_erp(self):
		with (
			patch("frappe.session", frappe._dict(user="manager@example.test")),
			patch("frappe.get_roles", return_value=["TC R01"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", return_value=True),
		):
			doctypes = {link["doctype"] for link in get_context()["management"]}
		self.assertTrue({"Wash Batch", "Sterile Putaway", "Employee", "Zone Station"} <= doctypes)
		self.assertFalse(doctypes & {"Sales Invoice", "Customer", "Lead", "Opportunity"})

	def test_setup_links_include_department_user_and_catalog_import(self):
		# Thiết lập ban đầu: khoa, tài khoản và import danh mục phải mở được từ trang chủ TraceCore
		with (
			patch("frappe.session", frappe._dict(user="admin@example.test")),
			patch("frappe.get_roles", return_value=["TC R10"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", return_value=True),
		):
			links = get_context()["management"]
		routes = {link["route"] for link in links}
		self.assertTrue({"/app/department", "/app/user", "/app/tc-import"} <= routes)
		# FEAT-006: dashboard vận hành đứng đầu, sau đó mới đến thiết lập tổ chức và người
		self.assertEqual(links[0]["route"], "/app/tc-dashboard")
		self.assertEqual(links[1]["group"], "Organization and staff")
		self.assertTrue(all(link["label"] and link["group"] for link in links))
		# nhóm liền nhau, không lặp lại sau khi đã sang nhóm khác
		groups = [link["group"] for link in links]
		self.assertEqual(groups, sorted(groups, key=groups.index))

	def test_dashboard_link_follows_the_page_roles(self):
		for roles, expected in ((["TC R09"], True), (["TC R04"], False)):
			with (
				patch("frappe.session", frappe._dict(user="dash@example.test")),
				patch("frappe.get_roles", return_value=roles),
				patch("frappe.get_list", return_value=[]),
				patch("frappe.has_permission", return_value=True),
			):
				routes = {link["route"] for link in get_context()["management"]}
			self.assertEqual("/app/tc-dashboard" in routes, expected, roles)

	def test_notification_center_and_rules_are_reachable_from_the_launcher(self):
		with (
			patch("frappe.session", frappe._dict(user="admin@example.test")),
			patch("frappe.get_roles", return_value=["TC R10"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", return_value=True),
		):
			routes = {link["route"] for link in get_context()["management"]}
		self.assertTrue({"/app/notifications", "/app/notification-rule"} <= routes)

	def test_competency_matrix_shift_and_report_links_for_r02(self):
		with (
			patch("frappe.session", frappe._dict(user="r02@example.test")),
			patch("frappe.get_roles", return_value=["TC R02"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", return_value=True),
		):
			routes = {link["route"] for link in get_context()["management"]}
		self.assertTrue(
			{
				"/app/competency-matrix",
				"/app/shift-assignment",
				"/app/query-report/Shift Schedule",
				"/app/query-report/Station Output",
			}
			<= routes
		)

	def test_costs_and_maintenance_records_are_reachable_for_r09(self):
		# FEAT-039/044/045: hồ sơ bảo trì, khoản chi phí, bảng giá, khoản mục, cài đặt và báo cáo chi phí phải mở từ trang chủ
		with (
			patch("frappe.session", frappe._dict(user="r09@example.test")),
			patch("frappe.get_roles", return_value=["TC R09"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", return_value=True),
			patch("tracecore.v1.navigation._roles_permit", return_value=True),
		):
			links = get_context()["management"]
		routes = {link["route"] for link in links}
		self.assertTrue(
			{
				"/app/maintenance-record",
				"/app/cost-entry",
				"/app/cost-rate-version",
				"/app/cost-category",
				"/app/cost-settings",
				"/app/query-report/Cost by Target",
			}
			<= routes
		)
		cost_routes = [link["route"] for link in links if link["group"] == "Costs"]
		self.assertEqual(cost_routes[0], "/app/cost-entry")

	def test_every_group_and_label_has_a_vietnamese_translation(self):
		from tracecore.tests.test_station_page import other_app_translations, vi_translations
		from tracecore.v1 import navigation

		ours, others = vi_translations(), other_app_translations()
		texts = []
		for group, targets in navigation.MANAGEMENT_GROUPS:
			texts.append(group)
			for target in targets:
				if target.startswith(navigation.REPORT_PREFIX):
					texts.append(target[len(navigation.REPORT_PREFIX) :])
				else:
					texts.append(navigation.MANAGEMENT_PAGES.get(target, target))
		missing = [
			text
			for text in texts
			if not (ours.get(f"{text}:TraceCore Launcher") or ours.get(text) or others.get(text))
		]
		self.assertFalse(missing, f"thiếu dòng vi.csv {missing}")

	def test_processing_quality_and_audit_records_are_reachable(self):
		# chứng từ xử lý, truy xuất/chất lượng, báo cáo và thiết lập còn thiếu trên trang chủ (rà soát 28/10/2026)
		with (
			patch("frappe.session", frappe._dict(user="admin@example.test")),
			patch("frappe.get_roles", return_value=["TC R01"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", return_value=True),
			patch("tracecore.v1.navigation._roles_permit", return_value=True),
		):
			links = get_context()["management"]
		routes = {link["route"] for link in links}
		expected = {
			"/app/dirty-receipt",
			"/app/assembly-record",
			"/app/sterilization-load",
			"/app/issue-note",
			"/app/usage-record",
			"/app/incident-capa",
			"/app/recall-order",
			"/app/query-report/Pack Trace",
			"/app/daily-test",
			"/app/equipment-type-norm",
			"/app/instrument-group",
			"/app/instrument-maintenance",
			"/app/loaner-set",
			"/app/query-report/Instrument Data Gaps",
			"/app/par-override",
			"/app/query-report/Par Override Report",
			"/app/stock-reconciliation",
			"/app/material-request",
			"/app/query-report/Stock Alerts",
			"/app/query-report/Audit Trail",
			"/app/sync-conflict",
			"/app/code-range",
			"/app/tracecore-settings",
		}
		self.assertFalse(expected - routes, sorted(expected - routes))
		quality = [link["route"] for link in links if link["group"] == "Quality and traceability"]
		self.assertEqual(quality[0], "/app/query-report/Pack Trace")

	def test_sterilization_reports_and_environment_log_are_reachable(self):
		# FEAT-007 (sổ tiệt khuẩn, báo cáo KSNK, dự báo) và FEAT-008 (nhật ký môi trường) mở được từ trang chủ
		with (
			patch("frappe.session", frappe._dict(user="r01@example.test")),
			patch("frappe.get_roles", return_value=["TC R01"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", return_value=True),
			patch("tracecore.v1.navigation._roles_permit", return_value=True),
		):
			links = get_context()["management"]
		routes = {link["route"] for link in links}
		expected = {
			"/app/query-report/Sterilization Log",
			"/app/query-report/KSNK Summary Report",
			"/app/query-report/Instrument Life Forecast",
			"/app/environment-log",
			"/app/query-report/Environment Monthly Report",
			"/app/archive-export",  # FEAT-012
		}
		self.assertFalse(expected - routes, sorted(expected - routes))

	def test_catalog_import_follows_page_roles(self):
		# Page tc-import chỉ cho R02 / R10 / System Manager; R01 quản lý nhưng không thấy link import
		with (
			patch("frappe.session", frappe._dict(user="manager@example.test")),
			patch("frappe.get_roles", return_value=["TC R01"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", return_value=True),
		):
			routes = {link["route"] for link in get_context()["management"]}
		self.assertNotIn("/app/tc-import", routes)
		self.assertIn("/app/department", routes)

	def test_guest_cannot_read_launcher(self):
		with patch("frappe.session", frappe._dict(user="Guest")):
			with self.assertRaises(frappe.PermissionError):
				get_context()

	def test_operator_sees_only_its_steps(self):
		functions = {"TR-123": ["WASH_LOAD"], "TR-456": ["PACK"]}
		with (
			patch("tracecore.core.zones.station_functions", side_effect=lambda name: functions[name]),
			patch("tracecore.core.zones.station_screen_tabs", side_effect=fake_screen_tabs),
			patch("frappe.session", frappe._dict(user="operator@example.test")),
			patch("frappe.get_roles", return_value=["TC R03"]),
			patch(
				"frappe.get_list",
				return_value=[
					frappe._dict(name="TR-123", station_no=0, zone_station_name="Washer"),
					frappe._dict(name="TR-456", station_no=0, zone_station_name="Packing"),
				],
			),
		):
			context = get_context()
		self.assertEqual(context["management"], [])
		self.assertFalse(context["department"])
		self.assertEqual([s["name"] for s in context["stations"]], ["TR-123"])
		self.assertTrue(context["stations"][0]["implemented"])

	def test_pending_station_and_active_filter(self):
		# chức năng không có màn (Rửa thủ công) mở tra cứu chung: launcher báo chưa có màn riêng
		with (
			patch("tracecore.core.zones.station_functions", side_effect=lambda name: ["MANUAL_WASH"]),
			patch("tracecore.core.zones.station_screen_tabs", side_effect=fake_screen_tabs),
			patch("frappe.session", frappe._dict(user="Administrator")),
			patch("frappe.get_roles", return_value=["System Manager"]),
			patch(
				"frappe.get_list",
				return_value=[
					frappe._dict(name="TR-999", station_no=0, zone_station_name="Unloading"),
				],
			) as query,
			patch("frappe.has_permission", return_value=False),
		):
			context = get_context()
		self.assertFalse(context["stations"][0]["implemented"])
		self.assertEqual(query.call_args.kwargs["filters"], {"is_zone": 0, "is_active": 1})

	def test_every_station_screen_t1_to_t8_is_implemented(self):
		# Mọi màn đều đã có trên Page station (FEAT-019..027); launcher không được khóa trạm nào
		functions_by_station = {
			"TR-001": ["RECEIVE"],
			"TR-002": ["WASH_LOAD", "WASH_UNLOAD"],
			"TR-003": ["ASSEMBLE"],
			"TR-004": ["PACK"],
			"TR-005": ["STERI_LOAD", "STERI_UNLOAD"],
			"TR-006": ["PUTAWAY"],
			"TR-007": ["ISSUE"],
			"TR-008": ["USE"],
		}
		with (
			patch(
				"tracecore.core.zones.station_functions", side_effect=lambda name: functions_by_station[name]
			),
			patch("tracecore.core.zones.station_screen_tabs", side_effect=fake_screen_tabs),
			patch("frappe.session", frappe._dict(user="Administrator")),
			patch("frappe.get_roles", return_value=["System Manager"]),
			patch(
				"frappe.get_list",
				return_value=[
					frappe._dict(name=name, station_no=0, zone_station_name=name)
					for name in functions_by_station
				],
			),
			patch("frappe.has_permission", return_value=False),
		):
			context = get_context()
		self.assertEqual(
			{station["name"]: station["implemented"] for station in context["stations"]},
			dict.fromkeys(functions_by_station, True),
		)

	def test_sterile_storage_operator_sees_t6_and_t7(self):
		# R06 là KTV kho vô khuẩn / cấp phát (SRS FR-M2-13, FR-M2-15; ISSUE_ROLES = STORAGE_ROLES), R07 là đồ vải
		stations = [
			frappe._dict(name="TR-006", station_no=0, zone_station_name="Storage"),
			frappe._dict(name="TR-007", station_no=0, zone_station_name="Issuing"),
		]
		for roles, expected in ((["TC R06"], ["TR-006", "TR-007"]), (["TC R07"], [])):
			with (
				patch(
					"tracecore.core.zones.station_functions",
					side_effect=lambda name: {"TR-006": ["PUTAWAY"], "TR-007": ["ISSUE"]}[name],
				),
				patch("tracecore.core.zones.station_screen_tabs", side_effect=fake_screen_tabs),
				patch("frappe.session", frappe._dict(user="operator@example.test")),
				patch("frappe.get_roles", return_value=roles),
				patch("frappe.get_list", return_value=stations),
			):
				context = get_context()
			self.assertEqual([s["name"] for s in context["stations"]], expected)

	def test_unrelated_account_has_no_operational_choices(self):
		with (
			patch("frappe.session", frappe._dict(user="employee@example.test")),
			patch("frappe.get_roles", return_value=["Employee"]),
			patch("frappe.get_list") as query,
		):
			context = get_context()
		self.assertEqual(context["stations"], [])
		self.assertEqual(context["management"], [])
		query.assert_not_called()

	def test_manager_links_require_doctype_permission(self):
		with (
			patch("frappe.session", frappe._dict(user="manager@example.test")),
			patch("frappe.get_roles", return_value=["TC R01"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", side_effect=lambda dt, **kw: dt == "Pack"),
		):
			context = get_context()
		# link DocType theo quyền DocType; link Page (Trung tâm thông báo) theo role của Page
		self.assertEqual([link["doctype"] for link in context["management"] if link["doctype"]], ["Pack"])
