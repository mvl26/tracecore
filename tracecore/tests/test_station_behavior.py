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


T1_ITEM = """
const t1 = new T1Receiving(makeStation());
const item = {set_id: "S1", set_name: "Bo", lines: [
	{instrument: "A", instrument_name: "Kep", qty: 2, actual_qty: 2, confirmed: 0, position: 1},
	{instrument: "B", instrument_name: "Keo", qty: 1, actual_qty: 1, confirmed: 0, position: 2},
]};
t1.receipt = {receipt: "PT-1", items: []};
t1.currentId = "S1";
t1.current = () => item;
t1.refresh = () => {};
t1.show = () => {};
"""


class TestT1CountTable(FrappeTestCase):
	def test_table_has_four_columns_and_prefilled_input_without_ticks(self):
		out = run_js(self, [T1], [["T1Receiving"]], FAKE_STATION + T1_ITEM + "emit(t1.linesHtml(item));")
		self.assertEqual(out.count("<th "), 4)
		self.assertNotIn("tc-check", out)
		self.assertRegex(out, r'class="tc-t1-actual"[^>]*value="2"')
		self.assertIn('data-line="1"', out)

	def test_confirm_sends_actual_quantity_per_line(self):
		out = run_js(
			self,
			[T1],
			[["T1Receiving"]],
			FAKE_STATION
			+ T1_ITEM
			+ """
			let sent = null;
			t1.request = (name, args) => { sent = args; };
			const box = element();
			box.id = "x";
			box.dataset.line = "0";
			box.value = "1";
			box.closest = () => null;
			box.matches = (selector) => selector === ".tc-t1-actual";
			t1.onInput({target: box});
			t1.notes.S1 = "Thieu";
			t1.confirmSet();
			emit(sent.lines);
			""",
		)
		self.assertEqual(out[0]["actual_qty"], 1)
		self.assertEqual(out[0]["confirmed"], 0)
		self.assertEqual(out[1]["actual_qty"], 1)

	def test_blank_quantity_blocks_inline(self):
		out = run_js(
			self,
			[T1],
			[["T1Receiving"]],
			FAKE_STATION
			+ T1_ITEM
			+ """
			let called = false;
			t1.request = () => { called = true; };
			item.lines[0].actual_qty = null;
			t1.confirmSet();
			emit({called, variant: t1.notice && t1.notice.variant});
			""",
		)
		self.assertEqual(out, {"called": False, "variant": "error"})


class TestT1ScanLabel(FrappeTestCase):
	def test_visible_label_follows_the_step(self):
		out = run_js(
			self,
			[T1],
			[["T1Receiving"]],
			FAKE_STATION
			+ """
			const station = makeStation();
			const label = element();
			station.input.labels = [label];
			const t1 = new T1Receiving(station);
			const first = [label.textContent, station.input.attrs["aria-label"], station.input.placeholder];
			t1.receipt = {receipt: "PT-1", items: []};
			t1.updatePlaceholder();
			emit({first, second: [label.textContent, station.input.attrs["aria-label"], station.input.placeholder]});
			""",
		)
		self.assertEqual(len(set(out["first"])), 1)
		self.assertEqual(len(set(out["second"])), 1)
		self.assertIn("employee card", out["first"][0])
		self.assertIn("Set ID", out["second"][0])


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
