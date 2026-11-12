from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js
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
				elif target in navigation.FILTERED_LISTS:
					texts.append(navigation.FILTERED_LISTS[target][0])
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
		# R07, R08 không có quyền đọc Zone Station mà vẫn phải thấy trạm của mình
		self.assertTrue(query.call_args.kwargs["ignore_permissions"])

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


class TestStationNavigation(FrappeTestCase):
	def _source(self, *path):
		with open(frappe.get_app_path("tracecore", *path), encoding="utf-8") as handle:
			return handle.read()

	def test_stations_menu_opens_the_first_station_directly(self):
		# không có màn chọn trạm: bấm Trạm vào thẳng trạm đầu, đổi trạm bằng cột trạm trên trang trạm
		source = self._source("ui", "page", "tracecore", "tracecore.js")
		self.assertIn("data.stations.find((item) => item.implemented)", source)
		self.assertNotIn("tc-admin-zone-", source)

	def test_admin_station_tile_reloads_to_keep_station_code(self):
		# router Desk bỏ ?station= khi bấm <a>, Page station đọc mã từ URL lúc nạp nên phải nạp lại trang
		source = self._source("ui", "page", "tracecore", "tracecore.js")
		self.assertIn("window.location.assign(route)", source)

	def test_leaving_station_page_restores_desk_chrome(self):
		# Frappe v15 không gọi on_page_hide của Page, chỉ phát sự kiện "hide"; thiếu thì body.tc-kiosk còn mãi
		source = self._source("ui", "page", "station", "station.js")
		self.assertIn('$(wrapper).on("hide"', source)

	def test_station_page_and_desk_navbar_show_the_wordmark(self):
		self.assertIn('class="tc-brand"', self._source("ui", "page", "station", "station.html"))
		self.assertIn("tc-navbar-brand", self._source("public", "js", "tc_launcher.js"))


class TestR10ReadsSetupRecords(FrappeTestCase):
	"""R10 đọc được Khoa và Lệnh in để hai link trong menu của R10 hiện ra (NAV-04)."""

	def test_r10_reads_but_cannot_change_department_and_print_job(self):
		from tracecore.tests.factories import make_user
		from tracecore.ui import permissions

		permissions.ensure_permissions()
		admin = make_user("r10.setup@example.test", ("TC R10",))
		other = make_user("r03.setup@example.test", ("TC R03",))
		self.addCleanup(frappe.set_user, "Administrator")
		for doctype in ("Department", "Print Job"):
			frappe.set_user(admin)
			self.assertTrue(frappe.has_permission(doctype, "read"), doctype)
			self.assertFalse(frappe.has_permission(doctype, "write"), doctype)
			self.assertFalse(frappe.has_permission(doctype, "create"), doctype)
			self.assertFalse(frappe.has_permission(doctype, "delete"), doctype)
			frappe.set_user(other)
			self.assertFalse(frappe.has_permission(doctype, "read"), doctype)
			frappe.set_user("Administrator")

	def test_standard_rights_are_kept(self):
		from tracecore.ui import permissions

		permissions.ensure_permissions()
		self.assertTrue(
			frappe.db.exists("Custom DocPerm", {"parent": "Print Job", "role": "TC Agent", "read": 1})
		)
		self.assertTrue(
			frappe.db.exists("Custom DocPerm", {"parent": "Print Job", "role": "System Manager", "write": 1})
		)
		self.assertGreater(
			frappe.db.count(
				"Custom DocPerm", {"parent": "Department", "role": ["not like", "TC %"], "read": 1}
			),
			0,
		)


class TestRoleModules(FrappeTestCase):
	def _context(self, roles, rows=None, functions=None):
		with (
			patch("frappe.session", frappe._dict(user="role@example.test")),
			patch("frappe.get_roles", return_value=roles),
			patch("frappe.get_list", return_value=rows or []),
			patch("frappe.has_permission", return_value=True),
			patch("tracecore.v1.navigation._roles_permit", return_value=True),
			patch(
				"tracecore.core.zones.station_functions",
				side_effect=lambda name: (functions or {}).get(name, []),
			),
			patch("tracecore.core.zones.station_screen_tabs", return_value=[{"key": "s"}]),
		):
			return get_context()

	def _keys(self, roles):
		return [module["key"] for module in self._context(roles)["role_modules"]]

	def test_each_office_role_gets_its_own_flows(self):
		self.assertEqual(self._keys(["TC R01"])[:2], ["overview", "approvals"])
		self.assertIn("staff", self._keys(["TC R02"]))
		self.assertIn("unit_costs", self._keys(["TC R09"]))
		self.assertIn("organization", self._keys(["TC R10"]))
		self.assertNotIn("approvals", self._keys(["TC R09"]))
		self.assertNotIn("unit_costs", self._keys(["TC R10"]))

	def test_equipment_flow_of_r02_and_r10_has_program_consumable_gaps(self):
		for role in ("TC R02", "TC R10"):
			equipment = next(
				module for module in self._context([role])["role_modules"] if module["key"] == "equipment"
			)
			routes = {link["route"] for section in equipment["sections"] for link in section["links"]}
			self.assertIn("/app/query-report/Program Consumable Gaps", routes, role)

	def test_station_roles_have_no_flows(self):
		for number in range(3, 9):
			self.assertEqual(self._keys([f"TC R{number:02d}"]), [])

	def test_admin_keeps_full_menu_instead_of_flows(self):
		with (
			patch("frappe.session", frappe._dict(user="Administrator")),
			patch("frappe.get_roles", return_value=["System Manager"]),
			patch("frappe.get_list", return_value=[]),
			patch("frappe.has_permission", return_value=True),
			patch("tracecore.v1.navigation._roles_permit", return_value=True),
		):
			context = get_context()
		self.assertEqual(context["role_modules"], [])
		self.assertTrue(context["admin_modules"])

	def test_user_with_two_roles_sees_merged_flows_without_duplicates(self):
		modules = self._context(["TC R01", "TC R02"])["role_modules"]
		keys = [module["key"] for module in modules]
		self.assertEqual(len(keys), len(set(keys)))
		overview = next(module for module in modules if module["key"] == "overview")
		routes = [link["route"] for section in overview["sections"] for link in section["links"]]
		self.assertEqual(len(routes), len(set(routes)))
		self.assertTrue({"approvals", "staff"} <= set(keys))

	def test_flows_only_use_existing_screens(self):
		from tracecore.v1 import navigation

		known = {target for _group, targets in navigation.MANAGEMENT_GROUPS for target in targets}
		for role, flows in navigation.ROLE_FLOWS.items():
			for key, sections in flows:
				self.assertIn(key, navigation.FLOWS, role)
				for kind, targets in sections:
					self.assertIn(kind, navigation.ADMIN_SECTION_LABELS)
					self.assertFalse(set(targets) - known, (role, key))

	def test_flow_texts_are_translated(self):
		from tracecore.tests.test_station_page import other_app_translations, vi_translations
		from tracecore.v1 import navigation

		ours, others = vi_translations(), other_app_translations()
		texts = [text for flow in navigation.FLOWS.values() for text in (flow["label"], flow["description"])]
		missing = [
			text
			for text in texts
			if not (ours.get(f"{text}:TraceCore Launcher") or ours.get(text) or others.get(text))
		]
		self.assertFalse(missing, f"thiếu dòng vi.csv {missing}")

	def test_stations_follow_the_role_not_management_rights(self):
		rows = [
			frappe._dict(name="TR-001", station_no=1, zone_station_name="T1"),
			frappe._dict(name="TR-005", station_no=5, zone_station_name="T5"),
		]
		functions = {"TR-001": ["RECEIVE"], "TR-005": ["STERI_LOAD", "STERI_UNLOAD"]}
		for roles, expected in (
			(["TC R01"], []),
			(["TC R09"], []),
			(["TC R10"], []),
			(["TC R02"], ["TR-005"]),
			(["TC R03"], ["TR-001"]),
			(["TC R05"], ["TR-005"]),
		):
			context = self._context(roles, rows, functions)
			self.assertEqual([s["name"] for s in context["stations"]], expected, roles)


class TestDeskStartup(FrappeTestCase):
	def test_launcher_survives_a_null_route_at_app_ready(self):
		# get_route() trả null lúc khởi động làm frappe.Application dừng giữa chừng, mất cả Ctrl+S (CI PR 28)
		with open(
			frappe.get_app_path("tracecore", "public", "js", "tc_launcher.js"), encoding="utf-8"
		) as handle:
			self.assertIn("(frappe.get_route() || [])[0]", handle.read())


class TestAdminModules(FrappeTestCase):
	def _context(self, user, roles, **patches):
		with (
			patch("frappe.session", frappe._dict(user=user)),
			patch("frappe.get_roles", return_value=roles),
			patch("frappe.get_list", return_value=patches.get("rows", [])),
			patch("frappe.has_permission", side_effect=patches.get("allow", lambda dt, **kw: True)),
			patch("tracecore.v1.navigation._roles_permit", return_value=True),
		):
			return get_context()

	def test_every_management_target_sits_in_exactly_one_module(self):
		from tracecore.v1 import navigation

		placed = [
			target
			for module in navigation.ADMIN_MODULES
			for _kind, targets in module["sections"]
			for target in targets
		]
		expected = [target for _group, targets in navigation.MANAGEMENT_GROUPS for target in targets]
		self.assertEqual(len(placed), len(set(placed)), "có link lặp ở hai phân hệ")
		self.assertEqual(set(placed), set(expected))

	def test_only_administrator_and_system_manager_get_modules(self):
		for user, roles, expected in (
			("Administrator", [], True),
			("sm@example.test", ["System Manager"], True),
			("r10@example.test", ["TC R10"], False),
			("r01@example.test", ["TC R01"], False),
			("r03@example.test", ["TC R03"], False),
		):
			modules = self._context(user, roles)["admin_modules"]
			self.assertEqual(bool(modules), expected, roles or user)

	def test_module_groups_links_by_kind(self):
		modules = self._context("Administrator", [])["admin_modules"]
		reprocessing = next(module for module in modules if module["key"] == "reprocessing")
		self.assertEqual(reprocessing["cluster"], "business")
		self.assertTrue(reprocessing["icon"] and reprocessing["description"])
		self.assertEqual([section["kind"] for section in reprocessing["sections"]], ["document", "report"])
		routes = {link["route"] for link in reprocessing["sections"][0]["links"]}
		self.assertIn("/app/dirty-receipt", routes)

	def test_equipment_module_lists_program_consumable_gaps_report(self):
		# FEAT-054 có báo cáo chương trình thiếu vật tư nhưng trang Thiết bị chưa có ô dẫn tới
		modules = self._context("Administrator", [])["admin_modules"]
		equipment = next(module for module in modules if module["key"] == "equipment")
		self.assertEqual(
			[section["kind"] for section in equipment["sections"]], ["catalog", "document", "report"]
		)
		routes = {link["route"] for link in equipment["sections"][2]["links"]}
		self.assertEqual(routes, {"/app/query-report/Program Consumable Gaps"})

	def test_links_without_permission_drop_empty_sections_and_modules(self):
		modules = self._context(
			"sm@example.test",
			["System Manager"],
			allow=lambda dt, **kw: dt == "Pack",
		)["admin_modules"]
		reprocessing = next(module for module in modules if module["key"] == "reprocessing")
		links = [link["doctype"] for link in reprocessing["sections"][0]["links"]]
		self.assertEqual(links, ["Pack"])
		for module in modules:
			self.assertTrue(module["sections"], module["key"])
			for section in module["sections"]:
				self.assertTrue(section["links"], (module["key"], section["kind"]))

	def test_module_texts_have_vietnamese_translation(self):
		from tracecore.tests.test_station_page import other_app_translations, vi_translations
		from tracecore.v1 import navigation

		ours, others = vi_translations(), other_app_translations()
		texts = list(navigation.ADMIN_SECTION_LABELS.values())
		for module in navigation.ADMIN_MODULES:
			texts += [module["label"], module["description"]]
		missing = [
			text
			for text in texts
			if not (ours.get(f"{text}:TraceCore Launcher") or ours.get(text) or others.get(text))
		]
		self.assertFalse(missing, f"thiếu dòng vi.csv {missing}")


class TestHomeTitle(FrappeTestCase):
	"""Trang chủ: tiêu đề Home và nút ba gạch thu gọn sidebar."""

	def _source(self):
		with open(
			frappe.get_app_path("tracecore", "ui", "page", "tracecore", "tracecore.js"), encoding="utf-8"
		) as handle:
			return handle.read()

	def test_page_title_is_home(self):
		source = self._source()
		self.assertIn('title: __("Home", null, "TraceCore Launcher")', source)
		self.assertNotIn('title: "TraceCore"', source)

	def test_toggle_collapses_the_sidebar_and_remembers_it(self):
		source = self._source()
		self.assertIn("tc-admin-toggle", source)
		self.assertIn("aria-expanded", source)
		self.assertIn("NAV_COLLAPSED_KEY", source)
		self.assertIn('toggleClass("is-collapsed"', source)
		with open(
			frappe.get_app_path("tracecore", "ui", "page", "tracecore", "tracecore.css"), encoding="utf-8"
		) as handle:
			self.assertIn(".tc-admin.is-collapsed .tc-admin-nav", handle.read())


QUICK_NAV = "public/js/tc_quick_nav.js"


class TestNavbarQuickAccess(FrappeTestCase):
	"""NAV-05: thanh truy cập nhanh trên navbar Desk — chỉ role TC, chỉ ô tài khoản mở được."""

	def _keys(self, roles, user="role@example.test"):
		from tracecore.v1.navigation import quick_nav_keys

		with (
			patch("frappe.session", frappe._dict(user=user)),
			patch("frappe.get_roles", return_value=roles),
			# link trong phân hệ coi như mở được; quyền Page tc-ksnk đọc thật từ Has Role
			patch(
				"tracecore.v1.navigation._link",
				side_effect=lambda target: {"label": target, "doctype": None, "route": "/app/x"},
			),
		):
			return quick_nav_keys()

	def test_system_manager_without_tc_role_sees_no_quick_nav(self):
		# site dùng chung với app khác: quản trị không làm TraceCore thì không thấy thanh
		self.assertEqual(self._keys(["System Manager"]), [])

	def test_system_manager_with_tc_role_sees_all_four(self):
		self.assertEqual(self._keys(["System Manager", "TC R10"]), ["instruments", "linen", "waste", "ksnk"])

	def test_office_roles_only_see_modules_of_their_flows(self):
		self.assertEqual(self._keys(["TC R02"]), ["instruments", "waste", "ksnk"])
		self.assertEqual(self._keys(["TC R01"]), ["waste", "ksnk"])
		self.assertEqual(self._keys(["TC R10"]), ["ksnk"])
		self.assertEqual(self._keys(["TC R11"]), ["ksnk"])

	def test_station_roles_see_nothing(self):
		# R03-R08 không có phân hệ trên trang chủ và không mở được Page tc-ksnk
		for role in ("TC R03", "TC R05", "TC R08"):
			self.assertEqual(self._keys([role]), [], role)

	def test_bootinfo_carries_the_keys(self):
		from tracecore.ui import quick_nav

		boot = frappe._dict()
		with patch("tracecore.v1.navigation.quick_nav_keys", return_value=["waste"]):
			quick_nav.extend_bootinfo(boot)
		self.assertEqual(boot.tc_quick_nav, ["waste"])
		self.assertIn("tracecore.ui.quick_nav.extend_bootinfo", frappe.get_hooks("extend_bootinfo"))

	def test_boot_never_breaks_on_error(self):
		from tracecore.ui import quick_nav

		boot = frappe._dict()
		with patch("tracecore.v1.navigation.quick_nav_keys", side_effect=RuntimeError("db")):
			quick_nav.extend_bootinfo(boot)
		self.assertEqual(boot.tc_quick_nav, [])

	def test_desk_css_is_a_hand_written_bundle_with_tokens_only(self):
		import importlib.util
		from pathlib import Path

		script = Path(frappe.get_app_path("tracecore")).parent / "scripts" / "check_architecture.py"
		spec = importlib.util.spec_from_file_location("tc_check_architecture", script)
		lint = importlib.util.module_from_spec(spec)
		spec.loader.exec_module(lint)

		self.assertIn("tc_desk.bundle.css", frappe.get_hooks("app_include_css"))
		path = frappe.get_app_path("tracecore", "public", "css", "tc_desk.bundle.css")
		with open(path, encoding="utf-8") as handle:
			css = handle.read()
		self.assertIn(".tc-quick-nav", css)
		self.assertIn('[aria-current="page"]', css)
		self.assertEqual(lint._check_css("tracecore/public/css/tc_desk.bundle.css", css), [])

	def _js(self, body):
		return run_js(self, [QUICK_NAV], [["TcQuickNav"]], body)

	def test_current_key_follows_the_url(self):
		out = self._js(
			"""
			const k = TcQuickNav.current_key;
			emit([k("/app/tracecore/linen"), k("/app/tracecore"), k("/app/tc-ksnk/tuan-thu"),
				k("/app/tracecore/stock"), k("/app/asset"), k("/app/tracecore/waste/")]);
			"""
		)
		self.assertEqual(out, ["linen", None, "ksnk", None, None, "waste"])

	def test_pick_module_opens_requested_module_only_when_allowed(self):
		out = self._js(
			"""
			const modules = [{key: "overview"}, {key: "approvals"}, {key: "waste"}, {key: "stations"}];
			const here = (m) => m.key !== "overview" && m.key !== "stations";
			const p = (requested, selected) => TcQuickNav.pick_module(modules, requested, selected, here);
			emit([p("waste", null), p("linen", null), p("linen", "waste"), p(null, "waste"),
				p("overview", null), p("stations", null), p(null, null)]);
			"""
		)
		self.assertEqual(out, ["waste", "approvals", "waste", "waste", "approvals", "approvals", "approvals"])

	def test_module_path_keeps_the_module_in_the_url(self):
		out = self._js(
			'emit([TcQuickNav.module_path("linen"), TcQuickNav.module_path(null), TcQuickNav.module_path("a b")]);'
		)
		self.assertEqual(out, ["/app/tracecore/linen", "/app/tracecore", "/app/tracecore/a%20b"])

	def test_render_shows_only_allowed_links_with_text_and_current_state(self):
		out = self._js(
			"""
			const deps = {t: (s) => "vi:" + s, icon: (name) => `<svg data-icon="${name}"></svg>`, esc};
			emit({
				none: TcQuickNav.render([], "waste", deps),
				some: TcQuickNav.render(["ksnk", "waste", "bogus"], "waste", deps),
			});
			"""
		)
		self.assertEqual(out["none"], "")
		html = out["some"]
		self.assertIn('class="tc-quick-nav d-none d-lg-flex"', html)
		self.assertIn('aria-label="vi:Quick access"', html)
		# thứ tự cố định theo thiết kế, không theo thứ tự key từ server
		self.assertLess(html.index('href="/app/tracecore/waste"'), html.index('href="/app/tc-ksnk"'))
		self.assertNotIn("instruments", html)
		self.assertNotIn("bogus", html)
		self.assertIn('data-key="waste" aria-current="page"', html)
		self.assertEqual(html.count('aria-current="page"'), 1)
		self.assertIn("<span>vi:Waste</span>", html)
		self.assertIn("<span>vi:Infection control</span>", html)
		self.assertIn('data-icon="delete"', html)

	def test_mark_moves_the_current_state(self):
		out = self._js(
			"""
			const a = (key) => ({dataset: {key}, attrs: {}, setAttribute(k, v) { this.attrs[k] = v; },
				removeAttribute(k) { delete this.attrs[k]; }});
			const links = [a("linen"), a("waste")];
			links[0].attrs["aria-current"] = "page";
			TcQuickNav.mark(links, "waste");
			emit(links.map((l) => l.attrs["aria-current"] || null));
			"""
		)
		self.assertEqual(out, [None, "page"])

	def test_quick_links_are_translated(self):
		with open(frappe.get_app_path("tracecore", "translations", "vi.csv"), encoding="utf-8") as handle:
			rows = handle.read()
		for row in (
			"Quick access,Truy cập nhanh,TraceCore Quick Access",
			"Instruments,Dụng cụ,TraceCore Quick Access",
			"Linen,Đồ vải,TraceCore Quick Access",
			"Waste,Chất thải,TraceCore Quick Access",
			"Infection control,KSNK,TraceCore Quick Access",
		):
			self.assertIn(row, rows)

	def test_launcher_page_and_navbar_use_the_shared_helpers(self):
		# hành vi đã test ở TcQuickNav; ở đây chỉ kiểm trang chủ và navbar gọi đúng hàm dùng chung
		with open(
			frappe.get_app_path("tracecore", "ui", "page", "tracecore", "tracecore.js"), encoding="utf-8"
		) as handle:
			page = handle.read()
		self.assertIn("TcQuickNav.pick_module(", page)
		self.assertIn("TcQuickNav.module_path(", page)
		self.assertIn("history.replaceState(", page)
		with open(
			frappe.get_app_path("tracecore", "public", "js", "tc_launcher.js"), encoding="utf-8"
		) as handle:
			launcher = handle.read()
		self.assertIn("TcQuickNav.render(frappe.boot.tc_quick_nav", launcher)
		with open(
			frappe.get_app_path("tracecore", "public", "js", "tracecore.bundle.js"), encoding="utf-8"
		) as handle:
			bundle = handle.read()
		self.assertLess(bundle.index('import "./tc_quick_nav.js"'), bundle.index('import "./tc_launcher.js"'))
