"""Page Desk tc-dashboard — SCR-32 (FEAT-006, FR-M9-01, FR-M9-01.1, FR-M9-01.2; A-54 D1, D2, D9, D10)."""

import os
import re

import frappe
from frappe.tests.utils import FrappeTestCase

PAGE_DIR = os.path.join(frappe.get_app_path("tracecore"), "ui", "page", "tc_dashboard")


def _read(name):
	with open(os.path.join(PAGE_DIR, name), encoding="utf-8") as handle:
		return handle.read()


class TestDashboardPage(FrappeTestCase):
	def test_page_is_registered_for_managers_only(self):
		page = frappe.get_doc("Page", "tc-dashboard")
		self.assertEqual(page.module, "UI")
		roles = {row.role for row in page.roles}
		self.assertEqual(roles, {"TC R01", "TC R02", "TC R07", "TC R09", "TC R10", "System Manager"})

	def test_page_reads_the_summary_rpc_with_get(self):
		script = _read("tc_dashboard.js")
		self.assertIn('"tracecore.v1.dashboard.summary"', script)
		self.assertIn("tracecore.desk_get(TC_DASH", script)
		self.assertNotIn("frappe.call(", script)

	def test_refresh_polls_every_60_seconds_only_while_visible(self):
		script = _read("tc_dashboard.js")
		self.assertIn("TC_DASH_REFRESH_MS = 60000", script)
		self.assertIn("document.hidden", script)
		self.assertIn('frappe.realtime.on("tc_notification"', script)
		self.assertIn("clearInterval(state.timer)", script)

	def test_page_has_loading_empty_error_and_offline_states(self):
		script = _read("tc_dashboard.js")
		for text in (
			"Loading dashboard…",
			"No data — {0}",
			"Cannot load the dashboard",
			"Connect to the network to see the dashboard.",
		):
			self.assertIn(text, script)
		self.assertIn("navigator.onLine", script)
		self.assertIn('role", kind === "error" ? "alert"', script)

	def test_shown_strings_go_through_translation(self):
		script = _read("tc_dashboard.js")
		# chữ hiển thị chỉ qua __(); không gán chuỗi chữ cái thẳng vào .text("…")
		self.assertIsNone(re.search(r"\.text\(\s*[\"'][A-Za-zÀ-ỹ]", script))

	def test_css_uses_tokens_only(self):
		css = _read("tc_dashboard.css")
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b", css))
		body = re.sub(r"@media[^{]*\{", "{", css)
		self.assertIsNone(re.search(r"(?<![\w-])\d+(?:\.\d+)?px\b", body))
		self.assertIn("var(--tc-bw-kpi)", css)


class TestDashboardSidebar(FrappeTestCase):
	"""Trang Tổng quan vận hành chia theo mục ở sidebar (ux-foundations DASH-01)."""

	def _source(self):
		with open(
			frappe.get_app_path("tracecore", "ui", "page", "tc_dashboard", "tc_dashboard.js"),
			encoding="utf-8",
		) as handle:
			return handle.read()

	def test_every_block_belongs_to_exactly_one_section(self):
		from tracecore.v1.dashboard import BLOCK_SOURCES

		match = re.search(r"const DASH_SECTIONS = \[(.*?)\n\];", self._source(), re.S)
		self.assertTrue(match, "thiếu DASH_SECTIONS")
		placed = re.findall(r'"([a-z]+)"', "".join(re.findall(r"blocks: \[(.*?)\]", match.group(1), re.S)))
		self.assertEqual(sorted(placed), sorted(BLOCK_SOURCES))

	def test_section_labels_are_translated(self):
		from tracecore.tests.test_station_page import vi_translations

		match = re.search(r"const DASH_SECTIONS = \[(.*?)\n\];", self._source(), re.S)
		ours = vi_translations()
		for label in re.findall(r'label: "([^"]+)"', match.group(1)):
			self.assertTrue(ours.get(f"{label}:Operations Dashboard") or ours.get(label), label)

	def test_linen_and_waste_sections_have_overview_action_and_detail(self):  # DASH-02
		source = self._source()
		for text in ("renderLinen", "renderWaste", "Overview", "Needs action", "Details"):
			self.assertIn(text, source)
		self.assertIn("linen: () => renderLinen(blocks.linen)", source)
		self.assertIn("Kg by waste type", source)
		# màu túi luôn kèm tên loại, không chỉ bằng màu
		self.assertIn("tc-dash-bar-label", source)

	def test_only_the_selected_section_is_rendered(self):
		source = self._source()
		self.assertIn("tc-dash-nav", source)
		self.assertIn("DASH_SECTION_KEY", source)
		self.assertNotIn("if (blocks.sets) renderSets(blocks.sets);", source)
