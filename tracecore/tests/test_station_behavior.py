"""Hành vi màn trạm chạy thật trong Node (ticket Helpdesk 01/11/2026)."""

from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

T1 = "public/js/station_t1.js"
T4 = "public/js/station_t4.js"
FAKE_STATION = """
const makeStation = () => ({
	result: element(), input: element(), session: {roles: []}, sessionVersion: 1,
	listen() {}, isOffline: () => false, setState() {}, focus() {}, renderLoading() {},
	businessButtons: () => "",
});
"""


class TestT4Queue(FrappeTestCase):
	def test_queue_is_reloaded_after_packing(self):
		out = run_js(
			self,
			[T4],
			[["T4Packing"]],
			FAKE_STATION
			+ """
			const t4 = new T4Packing(makeStation());
			let resets = 0;
			t4.queue = {reset() { resets += 1; }};
			t4.handlePrint = () => {};
			t4.onGenerated({print: null});
			emit({resets});
			""",
		)
		self.assertEqual(out["resets"], 1)


class TestT1Today(FrappeTestCase):
	def test_today_block_shows_only_names_with_code_as_tooltip(self):
		out = run_js(
			self,
			[T1],
			[["T1Receiving"]],
			FAKE_STATION
			+ """
			const t1 = new T1Receiving(makeStation());
			t1.today = {total_receipts: 1, total_sets: 1, receipts: [{
				receipt: "PT-1", received_at: "2026-11-01 08:00", department: "K", department_name: "Khoa",
				deliverer: "HR-EMP-00001", deliverer_name: "Nguoi Giao",
				receiver: "HR-EMP-00020", receiver_name: "Nhan Vien 20",
				set_count: 1, flagged_count: 0,
			}]};
			emit(t1.todayHtml());
			""",
		)
		self.assertIn("Nhan Vien 20", out)
		self.assertNotIn("HR-EMP-00020 ·", out)
		self.assertNotIn(">HR-EMP-00020", out)
		self.assertIn('title="HR-EMP-00020"', out)
