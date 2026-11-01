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


T6 = "public/js/station_t6.js"
T7 = "public/js/station_t7.js"
T8 = "public/js/station_t8.js"
PACK_TRACE = "reprocessing/report/pack_trace/pack_trace.js"
LAUNCHER = "ui/page/tracecore/tracecore.js"
STATION = "ui/page/station/station.js"
DAILY = "public/js/station_daily_test.js"
MACHINE = {"name": "TB-1", "equipment_name": "May", "required": ["bowie_dick"], "missing": [], "runs": {}}


class TestDailyTestList(FrappeTestCase):
	def html(self, row):
		import json

		return run_js(
			self,
			[DAILY],
			[["DailyTestScreen"]],
			FAKE_STATION
			+ f"""
			const screen = Object.create(DailyTestScreen.prototype);
			screen.list = [{json.dumps(row)}];
			screen.statusBadge = () => "";
			emit(screen.listHtml());
			""",
		)

	def test_result_is_a_coloured_badge_with_text_not_a_tag(self):
		passed = self.html(MACHINE)
		self.assertRegex(passed, r"tc-badge tc-badge-g[^>]*>[^<]*(<[^>]+>[^<]*</[^>]+> )?[^<]*Pass")
		self.assertNotIn('class="tc-tag"', passed)
		failed = self.html({**MACHINE, "missing": ["bowie_dick"]})
		self.assertRegex(failed, r"tc-badge tc-badge-r")

	def test_unlock_shows_person_reason_and_end(self):
		out = self.html(
			{
				**MACHINE,
				"unlocked": 1,
				"unlocked_by_name": "Giam Sat",
				"unlock_reason": "Ca khan",
				"unlock_until": "2026-11-01 15:30:00",
			}
		)
		self.assertIn("Giam Sat", out)
		self.assertIn("Ca khan", out)
		self.assertIn("01/11/2026 15:30", out)


class TestT6Overview(FrappeTestCase):
	def overview(self, pending):
		import json

		data = {
			"by_set_type": [],
			"by_location": [],
			"expiring": [],
			"return_list": [],
			"pending": pending,
		}
		return run_js(
			self,
			[T6],
			[["T6Storage"]],
			FAKE_STATION
			+ f"""
			const t6 = Object.create(T6Storage.prototype);
			t6.overview = {json.dumps(data)};
			emit(t6.overviewHtml());
			""",
		)

	def test_empty_location_table_says_so(self):
		out = self.overview({"items": [], "total": 0})
		self.assertIn("No pack in storage yet.", out)
		self.assertNotIn("<th", out)

	def test_pending_queue_is_listed(self):
		out = self.overview({"items": [{"id": "CY-1", "name": "Bo", "department_name": "Khoa"}], "total": 1})
		self.assertIn("Packs waiting for storage (1)", out)
		self.assertIn("CY-1", out)

	def test_prompt_does_not_say_cycle_id(self):
		out = self.overview({"items": [], "total": 0})
		self.assertNotIn("Cycle ID", out)


class TestT7Departments(FrappeTestCase):
	def test_shortage_is_listed_and_picks_the_department(self):
		out = run_js(
			self,
			[T7],
			[["T7Issue"]],
			FAKE_STATION
			+ """
			const t7 = Object.create(T7Issue.prototype);
			t7.departments = [
				{name: "K1", department_name: "Khoa 1", shortage: [{set_type: "A", set_name: "Bo A", suggest: 2, available: 1}]},
				{name: "K2", department_name: "Khoa 2", shortage: []},
			];
			t7.button = (action, label, kind, extra) => `<button data-action="${action}"${extra}>${label}</button>`;
			emit(t7.departmentsHtml());
			""",
		)
		self.assertIn("Par shortage by department", out)
		self.assertIn("Bo A", out)
		self.assertEqual(out.count('data-dept="K1"'), 1)
		self.assertEqual(out.count('data-dept="K2"'), 1)


class TestT8Idle(FrappeTestCase):
	def idle(self, overview):
		import json

		return run_js(
			self,
			[T8],
			[["T8Usage"]],
			FAKE_STATION
			+ f"""
			const t8 = Object.create(T8Usage.prototype);
			t8.waiting = [];
			t8.station = {{session: {{department_name: "Khoa Noi"}}}};
			t8.overview = {json.dumps(overview)};
			emit(t8.idleHtml());
			""",
		)

	def test_shows_department_packs_expiry_and_waiting_return(self):
		out = self.idle(
			{
				"at_department": [
					{
						"cycle_id": "CY-1",
						"set_name": "Bo A",
						"expiry": "2026-11-04",
						"days_left": 3,
						"expiring": True,
					},
				],
				"waiting_return": [
					{"cycle_id": "CY-2", "set_name": "Bo B", "used_at": "2026-11-01 08:00:00"}
				],
			}
		)
		self.assertIn("Khoa Noi", out)
		self.assertIn("Packs at the department (1)", out)
		self.assertIn("04/11/2026", out)
		self.assertIn("Expiring soon", out)
		self.assertIn("Used, waiting to return (1)", out)
		self.assertIn("CY-2", out)
		self.assertIn("Scan the code on the pack.", out)
		self.assertNotIn("Cycle ID", out)

	def test_empty_lists_say_so(self):
		out = self.idle({"at_department": [], "waiting_return": []})
		self.assertIn("No pack is at the department.", out)
		self.assertIn("No used pack is waiting to return.", out)


class TestPackTracePhoto(FrappeTestCase):
	def cell(self, value):
		import json

		return run_js(
			self,
			[PACK_TRACE],
			[["tcIndicatorPhotoCell"]],
			f"emit(tcIndicatorPhotoCell({json.dumps(value)}));",
		)

	def test_photo_opens_as_an_image_link(self):
		out = self.cell("/private/files/chi-thi.jpg")
		self.assertIn('href="/private/files/chi-thi.jpg"', out)
		self.assertIn("<img", out)

	def test_other_urls_and_blank_show_nothing_clickable(self):
		self.assertEqual(self.cell(None), "")
		self.assertNotIn("href", self.cell("javascript:alert(1)"))
		self.assertNotIn("href", self.cell("https://evil.example/x.jpg"))


class TestDocumentTitles(FrappeTestCase):
	def title(self, station):
		import json

		return run_js(
			self,
			[STATION],
			[["tcStationTitle"]],
			f"emit(tcStationTitle({json.dumps(station)}));",
		)

	def test_station_title_has_number_name_and_app(self):
		self.assertEqual(self.title({"label": "Tiếp nhận", "station_no": 1}), "T1 Tiếp nhận 2013 TraceCore")

	def test_station_title_does_not_repeat_the_number(self):
		self.assertEqual(self.title({"label": "T4 Đóng gói", "station_no": 4}), "T4 Đóng gói 2013 TraceCore")

	def test_station_without_number(self):
		self.assertEqual(self.title({"label": "Giặt", "station_no": 0}), "Giặt 2013 TraceCore")


class TestOverviewTiles(FrappeTestCase):
	def test_summary_blocks_become_tiles_with_counts_and_routes(self):
		out = run_js(
			self,
			[LAUNCHER],
			[["tcOverviewTiles"]],
			"""emit(tcOverviewTiles({
				sets: [{status: "Sterile", count: 5}],
				failures: {load: {failed: 1, finished: 4, percent: 25}, wash: {failed: 0, finished: 2, percent: 0}},
			}));""",
		)
		self.assertEqual(out[0]["value"], 5)
		self.assertEqual(out[0]["route"], "/app/set-unit?status=Sterile")
		self.assertEqual(out[1]["value"], "1/4")
		self.assertEqual(out[1]["route"], "/app/sterilization-load?status=Failed")
		self.assertEqual(out[2]["route"], "/app/wash-batch?status=Failed")

	def test_role_without_blocks_gets_no_tile(self):
		out = run_js(self, [LAUNCHER], [["tcOverviewTiles"]], "emit(tcOverviewTiles({}));")
		self.assertEqual(out, [])


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
