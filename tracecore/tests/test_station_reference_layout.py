"""Shell STN theo mẫu đã duyệt: dùng lại trạm và phiên thật, không dữ liệu demo."""

from pathlib import Path

from frappe.tests.utils import FrappeTestCase


class TestStationReferenceLayout(FrappeTestCase):
	def test_full_station_menu_includes_other_zones(self):
		from tracecore.v1.navigation import context

		result = context(station="TR-001", all_stations=1)
		import frappe

		expected = frappe.get_all("Zone Station", filters={"is_zone": 0, "is_active": 1}, pluck="name")
		self.assertEqual(set(expected), {row["name"] for row in result["stations"]})
		self.assertTrue(all("permitted" in row for row in result["stations"]))

	def test_navigation_is_limited_to_the_current_zone(self):
		from tracecore.v1.navigation import context

		result = context(station="TR-001")
		self.assertTrue(result["stations"])
		self.assertTrue(all(row["step"] in ("T1", "T2") for row in result["stations"]))
		self.assertIn("TR-001", [row["name"] for row in result["stations"]])

	def test_shell_has_navigation_and_process_landmarks(self):
		source = (Path(__file__).parents[1] / "ui/page/station/station.html").read_text(encoding="utf-8")
		for selector in ("tc-rail", "tc-station-nav", "tc-breadcrumb", "tc-process-steps", "tc-connection"):
			with self.subTest(selector=selector):
				self.assertIn(selector, source)
		self.assertEqual(source.count('id="tc-scan-input"'), 1)
		self.assertEqual(source.count('data-action="logout"'), 1)
