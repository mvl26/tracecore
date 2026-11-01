"""Khung trạm chạy thật trong Node: đăng xuất khi quá hạn, bỏ script Page cũ trong localStorage."""

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

SHELL = "ui/page/station/station.js"


class TestLogoutNotice(FrappeTestCase):
	"""Đăng xuất chủ động không được hiện "Phiên trạm đã bị khóa" dù vừa quá 10 phút không thao tác."""

	FAKE = """
	const calls = [];
	const shell = {
		session: {token: "t"},
		lastActivity: 0,
		endSession: (error) => calls.push(["end", error === undefined ? null : error]),
		checkSession: () => calls.push(["check"]),
	};
	const event = (action) => ({target: {closest: (selector) => (action && selector.includes(action) ? {} : null)}});
	const note = (e) => TraceCoreStation.prototype.noteActivity.call(shell, e);
	"""

	def run_shell(self, body):
		return run_js(self, [SHELL], [["TraceCoreStation"]], self.FAKE + body)

	def test_tapping_logout_after_idle_ends_without_a_notice(self):
		self.assertEqual(self.run_shell('note(event("logout")); emit(calls);'), [["end", None]])

	def test_other_taps_after_idle_still_lock_with_the_notice(self):
		self.assertEqual(self.run_shell("note(event(null)); emit(calls);"), [["check"]])

	def test_recent_activity_only_updates_the_clock(self):
		out = self.run_shell('shell.lastActivity = Date.now(); note(event("logout")); emit(calls);')
		self.assertEqual(out, [])


class TestStationScriptCache(FrappeTestCase):
	"""Script Page trạm trong localStorage được bỏ khi mã trạm đổi."""

	FAKE = """
	const store = {"_page:station": "cu", tc_station_build: "A"};
	const storage = {
		getItem: (key) => (key in store ? store[key] : null),
		setItem: (key, value) => { store[key] = value; },
		removeItem: (key) => { delete store[key]; },
	};
	"""

	def run_cache(self, body):
		return run_js(self, ["public/js/tc_page_cache.js"], [[]], self.FAKE + body + "emit(store);")

	def test_new_build_drops_the_cached_page(self):
		out = self.run_cache('window.tcSyncStationBuild({tc_station_build: "B"}, storage);')
		self.assertEqual(out, {"tc_station_build": "B"})

	def test_same_build_keeps_the_cached_page(self):
		out = self.run_cache('window.tcSyncStationBuild({tc_station_build: "A"}, storage);')
		self.assertIn("_page:station", out)

	def test_missing_boot_value_changes_nothing(self):
		out = self.run_cache("window.tcSyncStationBuild({}, storage);")
		self.assertEqual(out["tc_station_build"], "A")

	def test_build_key_follows_the_station_files(self):
		from unittest.mock import patch

		from tracecore.ui import page_cache

		first = page_cache.station_build()
		self.assertEqual(first, page_cache.station_build())
		original = page_cache._read
		with patch.object(page_cache, "_read", lambda path: original(path) + b"x"):
			self.assertNotEqual(first, page_cache.station_build())

	def test_bootinfo_carries_the_key(self):
		from tracecore.ui import page_cache

		boot = frappe._dict()
		page_cache.extend_bootinfo(boot)
		self.assertEqual(boot.tc_station_build, page_cache.station_build())
