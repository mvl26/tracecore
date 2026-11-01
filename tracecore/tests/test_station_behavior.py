"""Hành vi màn trạm chạy thật trong Node (ticket Helpdesk 01/11/2026)."""

import csv

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests.js_harness import run_js

T1 = "public/js/station_t1.js"
T4 = "public/js/station_t4.js"
T2 = "public/js/station_t2.js"
T5 = "public/js/station_t5.js"
ERR = "public/js/station_error.js"
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

	def test_differing_quantity_offers_confirm_anyway(self):
		out = run_js(
			self,
			[ERR, T1],
			[[], ["T1Receiving"]],
			FAKE_STATION
			+ T1_ITEM
			+ """
			item.lines[0].actual_qty = 1;
			t1.confirmSet();
			emit(t1.noticeHtml());
			""",
		)
		self.assertIn('data-action="confirm-anyway"', out)

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
		self.assertEqual(self.title({"label": "Tiếp nhận", "station_no": 1}), "T1 Tiếp nhận \u2013 TraceCore")

	def test_station_title_does_not_repeat_the_number(self):
		self.assertEqual(
			self.title({"label": "T4 Đóng gói", "station_no": 4}), "T4 Đóng gói \u2013 TraceCore"
		)

	def test_station_without_number(self):
		self.assertEqual(self.title({"label": "Giặt", "station_no": 0}), "Giặt \u2013 TraceCore")


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


T5_DONE = """
const station = makeStation();
const t5 = new T5Load(station);
t5.done = {load: "ME-261101-02", packs: ["CY-1"], pack_rows: [], rejected: [], qr_png_b64: "QQ==",
	machine: {name: "M1", equipment_name: "May 1"}, program_name: "P1", at: "2026-11-01T08:00:00+07:00",
	print: {print_job: "PJ-1", status: "Queued", printer: "PRN-001", zpl: "^XA^XZ", warning: null}};
const screen = t5;
"""
T2_DONE = """
const station = makeStation();
const t2 = new T2Wash(station);
t2.done = {batch: "LR-261101-07", sets: ["S1"], rejected: [], chemicals: [], qr_png_b64: "QQ==",
	machine: {name: "M1", equipment_name: "May 1"}, program_name: "P1", at: "2026-11-01T08:00:00+07:00",
	print: {print_job: "PJ-1", status: "Queued", printer: "PRN-001", zpl: "^XA^XZ", warning: null}};
const screen = t2;
"""
T4_DONE = """
const station = makeStation();
const t4 = new T4Packing(station);
t4.done = {pack: {cycle_id: "CY-261101-0001", set_id: "S1", set_name: "Bo", method: "Steam", expiry: "2027-01-01",
		packed_at: "2026-11-01 08:00:00", packer: "A", ci_batch: "L", bom_version: 1, pack_type: "T",
		shelf_life_days_applied: 30},
	hri: "H", datamatrix_png_b64: "QQ==",
	print: {print_job: "PJ-1", status: "Queued", printer: "PRN-001", zpl: "^XA^XZ", warning: null}};
const screen = t4;
"""
PDF_STUBS = """
station.station = "TR-X";
screen.show = () => {};
const reads = [];
let answer = {ok: true, pdf_b64: "JVBERg==", filename: "X.pdf", print_job: "PJ-1"};
station.rpcRead = async (method, args) => {
	reads.push([method, args]);
	if (answer instanceof Error) throw answer;
	return answer;
};
station.failureCause = (error, result) => (result && result.error ? result.error.reason : "net down");
const saved = [];
window.tcSavePdf = (b64, name) => saved.push([b64, name]);
const agent = [];
window.fetch = async (url) => { agent.push(url); return {ok: true}; };
fetch = window.fetch;
const WAITING = {print_job: "PJ-1", status: "Waiting", printer: null, zpl: null,
	warning: {code: "NO_PRINTER_AT_STATION", title: "t", reason: "No printer r", action: "a"}};
"""
SCREENS = (
	(
		"t5",
		T5,
		"T5Load",
		T5_DONE,
		"tracecore.v1.load.label_pdf",
		{"load": "ME-261101-02", "station": "TR-X"},
	),
	(
		"t2",
		T2,
		"T2Wash",
		T2_DONE,
		"tracecore.v1.wash.label_pdf",
		{"batch": "LR-261101-07", "station": "TR-X"},
	),
	(
		"t4",
		T4,
		"T4Packing",
		T4_DONE,
		"tracecore.v1.pack.label_pdf",
		{"cycle_id": "CY-261101-0001", "station": "TR-X"},
	),
)


class TestLabelPrintsToPdf(FrappeTestCase):
	"""A-101: T2, T5, T4 có máy in thì tự lưu PDF nhãn, không gọi Station Agent; không có nút Lưu PDF."""

	def run_screen(self, screen, body):
		name, path, cls, done = screen[:4]
		return run_js(self, [ERR, path], [[], [cls]], FAKE_STATION + done + PDF_STUBS + body)

	def test_queued_label_is_fetched_saved_once_and_never_sent_to_the_agent(self):
		for screen in SCREENS:
			out = self.run_screen(
				screen,
				"""
				await screen.handlePrint(screen.done.print);
				emit({reads, saved, agent, note: screen.printNoteHtml()});
				""",
			)
			[[method, args]] = out["reads"]
			self.assertEqual(method, screen[4])
			self.assertEqual({key: args[key] for key in screen[5]}, screen[5])
			self.assertEqual(out["saved"], [["JVBERg==", "X.pdf"]])
			self.assertEqual(out["agent"], [])
			self.assertIn("tc-alert-ok", out["note"])
			self.assertIn("Label printed to PDF file: X.pdf", out["note"])

	def test_failure_warns_inline_keeps_the_code_and_retry_saves(self):
		for screen in SCREENS:
			out = self.run_screen(
				screen,
				f"""
				answer = {{ok: false, error: {{code: "LABEL_PDF_FAILED", reason: "no tool"}}}};
				await screen.handlePrint(screen.done.print);
				const failed = screen.printNoteHtml();
				const savedBefore = saved.length;
				answer = {{ok: true, pdf_b64: "JVBERg==", filename: "X.pdf", print_job: "PJ-1"}};
				screen.onAction("{screen[0]}-label-pdf-retry", element());
				for (let tick = 0; tick < 20; tick += 1) await Promise.resolve();
				emit({{failed, savedBefore, saved, note: screen.printNoteHtml(), reads: reads.length}});
				""",
			)
			self.assertIn("tc-alert-warn", out["failed"])
			self.assertIn("no tool", out["failed"])
			self.assertRegex(out["failed"], rf'data-action="{screen[0]}-label-pdf-retry"')
			self.assertEqual(out["savedBefore"], 0)
			self.assertEqual(len(out["saved"]), 1)
			self.assertIn("tc-alert-ok", out["note"])
			self.assertEqual(out["reads"], 2)

	def test_network_error_is_a_warning_not_an_exception(self):
		for screen in SCREENS:
			out = self.run_screen(
				screen,
				"""
				answer = new Error("boom");
				await screen.handlePrint(screen.done.print);
				emit({note: screen.printNoteHtml(), saved});
				""",
			)
			self.assertIn("net down", out["note"])
			self.assertEqual(out["saved"], [])

	def test_ended_session_during_the_request_changes_nothing(self):
		for screen in SCREENS:
			out = self.run_screen(
				screen,
				"""
				answer = Object.assign(new Error("ended"), {sessionEnded: true});
				screen.printNote = null;
				await screen.handlePrint(screen.done.print);
				emit({saved});
				""",
			)
			self.assertEqual(out["saved"], [])

	def test_no_printer_means_no_request_no_file_and_the_warning(self):
		for screen in SCREENS:
			out = self.run_screen(
				screen,
				"""
				screen.done.print = WAITING;
				await screen.handlePrint(WAITING);
				emit({reads, saved, agent, note: screen.printNoteHtml()});
				""",
			)
			self.assertEqual((out["reads"], out["saved"], out["agent"]), ([], [], []))
			self.assertIn("No printer r", out["note"])

	def test_cards_have_no_label_pdf_button_and_only_the_code(self):
		for screen in SCREENS[:2]:
			with self.subTest(screen=screen[0]):
				out = self.run_screen(screen, "screen.printNoteHtml = () => ''; emit(screen.doneHtml());")
				self.assertNotIn("Save label PDF", out)
				self.assertNotIn("tc-code-row", out)
				self.assertNotIn("label-pdf", out)
				self.assertIn('class="tc-cycle"', out)

	def test_button_helper_and_agent_code_are_gone(self):
		for path in (T2, T5, T4, "public/js/tc_outbox.js", ERR):
			with open(frappe.get_app_path("tracecore", *path.split("/")), encoding="utf-8") as handle:
				source = handle.read()
			for gone in ("tcCodeWithPdfHtml", "sendToAgent", "8765", "AGENT_URL"):
				self.assertNotIn(gone, source, msg=f"{path}: {gone}")

	def test_t4_roll_release_makes_one_merged_pdf_call(self):
		out = self.run_screen(
			SCREENS[2],
			"""
			answer = {ok: true, pdf_b64: "JVBERg==", filename: "labels.pdf",
				print_jobs: ["PJ-1", "PJ-2"], skipped: []};
			await t4.onRoll({printer: "P", method: "Steam", label_type: "L",
				released_jobs: [{print_job: "PJ-1", zpl: "z", printer: "P"}, {print_job: "PJ-2", zpl: "z", printer: "P"}],
				failed_jobs: []}, "CN-00001");
			emit({reads, saved, agent, notice: t4.notice, note: t4.printNoteHtml()});
			""",
		)
		[[method, args]] = out["reads"]
		self.assertEqual(method, "tracecore.v1.pack.waiting_labels_pdf")
		self.assertEqual(args["print_jobs"], ["PJ-1", "PJ-2"])
		self.assertEqual(out["saved"], [["JVBERg==", "labels.pdf"]])
		self.assertEqual(out["agent"], [])
		self.assertEqual(out["notice"]["variant"], "info")
		self.assertIn("labels.pdf", out["notice"]["reason"])
		self.assertIn("tc-alert-ok", out["note"])

	def test_t4_roll_failure_warns_and_offers_retry(self):
		out = self.run_screen(
			SCREENS[2],
			"""
			answer = {ok: false, error: {reason: "no tool"}};
			await t4.onRoll({printer: "P", method: "Steam", label_type: "L",
				released_jobs: [{print_job: "PJ-1", zpl: "z", printer: "P"}], failed_jobs: []}, "CN-00001");
			const failed = t4.noticeHtml();
			answer = {ok: true, pdf_b64: "JVBERg==", filename: "labels.pdf", print_jobs: ["PJ-1"], skipped: []};
			t4.onAction("t4-roll-pdf-retry", element());
			for (let tick = 0; tick < 20; tick += 1) await Promise.resolve();
			emit({failed, reads: reads.length, saved, notice: t4.notice});
			""",
		)
		self.assertIn("tc-alert-warn", out["failed"])
		self.assertIn("no tool", out["failed"])
		self.assertIn('data-action="t4-roll-pdf-retry"', out["failed"])
		self.assertEqual(out["reads"], 2)
		self.assertEqual(len(out["saved"]), 1)
		self.assertEqual(out["notice"]["variant"], "info")

	def test_strings_are_translated(self):
		path = frappe.get_app_path("tracecore", "translations", "vi.csv")
		with open(path, encoding="utf-8", newline="") as handle:
			translated = {row[0]: row[1] for row in csv.reader(handle) if row}
		for text in (
			"Label printed to PDF file: {0}",
			"Creating the label PDF...",
			"Print again",
			"Label PDF was not created; code {0} is kept.",
			"Created {0} waiting label(s) in one PDF file: {1}",
			"{0} waiting label(s) have no PDF yet.",
			"Label PDF could not be created",
			"Label is not ready to print",
		):
			self.assertTrue(translated.get(text), msg=text)
		self.assertNotIn("Save label PDF", translated)


OUTBOX_STUBS = """
const entries = [];
TcOutbox.list = async () => entries.slice();
TcOutbox.count = async () => entries.length;
TcOutbox.remove = async (key) => { entries.splice(entries.findIndex((e) => e.key === key), 1); };
TcOutbox.put = async () => {};
const posts = [];
const saved = [];
window.tcSavePdf = (b64, name) => saved.push([b64, name]);
let pdfAnswer = {ok: true, pdf_b64: "JVBERg==", filename: "labels.pdf", print_jobs: ["PJ-1", "PJ-2"], skipped: []};
fetch = window.fetch = async (url, init) => {
	const body = JSON.parse(init.body);
	posts.push([url, body]);
	if (url.endsWith("waiting_labels_pdf")) return {status: 200, json: async () => ({message: pdfAnswer})};
	return {status: 200, json: async () => ({message: {ok: true, print: {status: "Queued", print_job: body.job, zpl: "z", printer: "P"}}})};
};
const entry = (job) => ({key: job, endpoint: "tracecore.v1.pack.generate_cycle_id", station: "TR-4",
	args: {job, token: "tok", client_ts: "x"}});
"""


class TestReplayedLabels(FrappeTestCase):
	"""A-101: gói T4 đóng offline, khi có mạng nhãn ra một file PDF cho cả lượt phát lại."""

	def run_outbox(self, body):
		return run_js(self, ["public/js/tc_outbox.js"], [["tcSync", "TcOutbox"]], OUTBOX_STUBS + body)

	def test_one_pdf_for_the_whole_replay_pass(self):
		out = self.run_outbox(
			"""
			entries.push(entry("PJ-1"), entry("PJ-2"));
			await tcSync.replayAll();
			emit({posts, saved, state: tcSync.state});
			"""
		)
		pdf_calls = [post for post in out["posts"] if post[0].endswith("waiting_labels_pdf")]
		self.assertEqual(len(pdf_calls), 1)
		self.assertEqual(pdf_calls[0][1]["print_jobs"], ["PJ-1", "PJ-2"])
		self.assertEqual((pdf_calls[0][1]["station"], pdf_calls[0][1]["token"]), ("TR-4", "tok"))
		self.assertEqual(out["saved"], [["JVBERg==", "labels.pdf"]])
		self.assertEqual(out["state"]["label_file"], "labels.pdf")
		self.assertFalse(any("8765" in post[0] for post in out["posts"]))

	def test_failure_retries_on_the_next_pass_then_reports(self):
		out = self.run_outbox(
			"""
			entries.push(entry("PJ-1"));
			pdfAnswer = {ok: false, error: {reason: "no tool"}};
			await tcSync.replayAll();
			const first = tcSync.state.label_error;
			await tcSync.replayAll();
			await tcSync.replayAll();
			const count = posts.filter((post) => post[0].endsWith("waiting_labels_pdf")).length;
			await tcSync.replayAll();
			const after = posts.filter((post) => post[0].endsWith("waiting_labels_pdf")).length;
			emit({first, count, after, saved});
			"""
		)
		self.assertEqual(out["first"], "no tool")
		self.assertEqual(out["count"], 3)
		self.assertEqual(out["after"], 3)  # hết lượt thử: nhãn nằm lại Print Job Queued, không gọi mãi
		self.assertEqual(out["saved"], [])


class TestScanShell(FrappeTestCase):
	def test_browser_scrolls_stop_below_the_sticky_scan_block(self):
		with open(
			frappe.get_app_path("tracecore", "ui", "page", "station", "station.css"), encoding="utf-8"
		) as handle:
			css = handle.read()
		self.assertRegex(css, r"html:has\(\.tc-work\)[^}]*scroll-padding-top: calc\(")

	def test_scan_label_follows_the_placeholder(self):
		out = run_js(
			self,
			[ERR],
			[[]],
			"""
			let fire = null;
			globalThis.MutationObserver = class {
				constructor(callback) { fire = callback; }
				observe(_node, options) { this.options = options; globalThis.seen = options; }
			};
			const label = element();
			const input = element();
			input.labels = [label];
			input.placeholder = "Scan Set ID...";
			window.tcBindScanLabel(input);
			const first = label.textContent;
			input.placeholder = "Scan the sterilizer QR code...";
			fire();
			emit({first, second: label.textContent, filter: globalThis.seen.attributeFilter});
			""",
		)
		self.assertEqual(out["first"], "Scan Set ID...")
		self.assertEqual(out["second"], "Scan the sterilizer QR code...")
		self.assertEqual(out["filter"], ["placeholder"])

	def test_shell_binds_the_scan_label(self):
		with open(
			frappe.get_app_path("tracecore", "ui", "page", "station", "station.js"), encoding="utf-8"
		) as handle:
			self.assertIn("window.tcBindScanLabel(this.input)", handle.read())


class TestT5ReleaseBlockByRole(FrappeTestCase):
	"""Khối giải phóng theo role phiên, khớp `releasing._approver`: chỉ R02, R01 mới có PIN và nút."""

	def html(self, roles, needs_review=False, missing=()):
		return run_js(
			self,
			[ERR, T5, "public/js/station_t5b.js"],
			[[], ["T5Load"], ["T5Release"]],
			FAKE_STATION
			+ f"""
			const station = makeStation();
			station.session = {{token: "tok", roles: {roles!r}}};
			const screen = new T5Release(station, {{}});
			emit(screen.releaseHtml({{name: "ME-261101-09", needs_review: {str(needs_review).lower()}}}, {list(missing)!r}));
			""",
		)

	def test_technician_sees_the_message_and_no_release_controls(self):
		for roles in (["TC R05"], []):  # [] : System Manager không có role TC, server cũng từ chối
			with self.subTest(roles=roles):
				html = self.html(roles, missing=["cycle_result"])
				self.assertIn("A CSSD supervisor must release the load", html)
				self.assertIn(
					"Log out, then the CSSD supervisor signs in with the card at this station and enters the PIN.",
					html,
				)
				self.assertIn("tc-alert-info", html)
				for hidden in ("tc-t5b-pin", "tc-t5b-reason", "t5b-release", "t5b-reject"):
					self.assertNotIn(hidden, html)
				self.assertNotRegex(html, r"R0\d")

	def test_r02_and_r01_keep_pin_reason_and_button(self):
		for role in ("TC R02", "TC R01"):
			with self.subTest(role=role):
				html = self.html([role])
				for shown in ("tc-t5b-pin", "tc-t5b-reason", 'data-action="t5b-release"'):
					self.assertIn(shown, html)
				self.assertNotIn("A CSSD supervisor must release the load", html)

	def test_technician_gets_a_finish_button_when_nothing_is_missing(self):
		html = self.html(["TC R05"])
		self.assertIn('data-action="t5b-finish"', html)
		self.assertIn("Checks are finished", html)

	def test_no_finish_button_while_something_is_missing_or_for_the_supervisor(self):
		missing = self.html(["TC R05"], missing=["cycle_result"])
		self.assertNotIn("t5b-finish", missing)
		self.assertIn("A CSSD supervisor must release the load", missing)
		self.assertNotIn("t5b-finish", self.html(["TC R02"]))

	def test_finish_closes_the_load_and_says_it_waits_for_release(self):
		out = run_js(
			self,
			[ERR, T5, "public/js/station_t5b.js"],
			[[], ["T5Load"], ["T5Release"]],
			FAKE_STATION
			+ """
			const station = makeStation();
			station.session = {token: "tok", roles: ["TC R05"]};
			const screen = new T5Release(station, {});
			screen.show = () => {};
			screen.ctx = {load: "ME-261101-09"};
			screen.scans = {equipment_raw: "TB-1", load_raw: "ME-261101-09"};
			const handled = screen.onAction("t5b-finish", {dataset: {}});
			emit({handled, ctx: screen.ctx, scans: screen.scans, notice: screen.notice});
			""",
		)
		self.assertTrue(out["handled"])
		self.assertIsNone(out["ctx"])
		self.assertEqual(out["scans"], {"equipment_raw": "", "load_raw": ""})
		self.assertEqual(out["notice"]["variant"], "ok")
		self.assertIn("ME-261101-09", out["notice"]["title"])

	def test_review_tick_only_for_those_who_can_release(self):
		self.assertNotIn("data-t5b-review", self.html(["TC R05"], needs_review=True))
		self.assertIn("data-t5b-review", self.html(["TC R02"], needs_review=True))

	def test_message_is_translated_without_role_codes(self):
		with open(frappe.get_app_path("tracecore", "translations", "vi.csv"), encoding="utf-8") as handle:
			rows = {row[0]: row[1] for row in csv.reader(handle) if len(row) >= 2}
		self.assertEqual(rows["A CSSD supervisor must release the load"], "Cần giám sát CSSD giải phóng mẻ")
		self.assertEqual(
			rows[
				"Log out, then the CSSD supervisor signs in with the card at this station and enters the PIN."
			],
			"Đăng xuất, giám sát CSSD đăng nhập thẻ tại trạm này rồi nhập PIN",
		)


T5_NOTICE_STATION = """
const station = makeStation();
station.session = {token: "tok", roles: ["TC R05"]};
station.form = element();
// như shell: lỗi nghiệp vụ có nút gọi giám sát, thông báo không phải lỗi thì không
station.businessButtons = (notice) =>
	notice.variant && notice.variant !== "error" ? "" : '<button data-action="call-r02">Call</button>';
const released = {
	code: "LOAD_ALREADY_RELEASED", http_status: 409, action: "",
	title: "Load ME-261101-06 has been released, packs moved to sterile storage",
	reason: "Released by An Nguyen at 01/11/2026 09:30.",
};
const closed = {
	code: "LOAD_NOT_OPEN", http_status: 409, title: "Load is closed", reason: "Already failed.",
	action: "Scan a running load.", error_code: "QT-001", error_name: "Wrong station order", has_guide: 1,
};
const LOADED = {name: "ME-261101-06"};
"""


class TestT5LoadAlreadyReleased(FrappeTestCase):
	"""Mẻ đã giải phóng ở T5: thông báo, không phải lỗi; mẻ đóng khác giữ lỗi QT-001 và các nút."""

	def run_screen(self, build):
		return run_js(
			self,
			[ERR, T5, "public/js/station_t5b.js"],
			[[], ["T5Load"], ["T5Release"]],
			FAKE_STATION + T5_NOTICE_STATION + build,
		)

	def release_screen(self, error):
		return self.run_screen(
			f"""
			const screen = new T5Release(station, {{}});
			screen.show = () => {{}};
			screen.ctx = LOADED;
			screen.scans = {{equipment_raw: "SK-1", load_raw: "ME-261101-06"}};
			screen.reject({error});
			emit({{html: screen.noticeHtml(), ctx: screen.ctx, scans: screen.scans, variant: screen.notice.variant}});
			"""
		)

	def data_screen(self, error):
		return self.run_screen(
			f"""
			const screen = new T5Load(station);
			screen.show = () => {{}};
			screen.data = LOADED;
			screen.reject({error}, "tracecore.v1.load.data_scan");
			emit({{html: screen.noticeHtml(), data: screen.data, state: screen.viewState(), variant: screen.notice.variant}});
			"""
		)

	def assert_is_notice(self, out):
		self.assertEqual(out["variant"], "info")
		self.assertIn("tc-alert-info", out["html"])
		self.assertIn('role="status"', out["html"])
		self.assertIn("ME-261101-06", out["html"])
		self.assertIn("Released by An Nguyen at 01/11/2026 09:30.", out["html"])
		self.assertNotIn("call-r02", out["html"])
		self.assertNotIn("data-tc-guide", out["html"])
		self.assertNotIn("tc-alert-error", out["html"])
		self.assertNotIn("tc-alert-action", out["html"])

	def assert_is_error(self, out):
		self.assertEqual(out["variant"], "error")
		self.assertIn("tc-alert-error", out["html"])
		self.assertIn("[QT-001]", out["html"])
		self.assertIn("call-r02", out["html"])
		self.assertIn("data-tc-guide", out["html"])

	def test_unload_tab_shows_a_notice_and_clears_the_scan(self):
		out = self.release_screen("released")
		self.assert_is_notice(out)
		self.assertIsNone(out["ctx"])
		self.assertEqual(out["scans"], {"equipment_raw": "", "load_raw": ""})

	def test_cycle_data_tab_shows_a_notice_and_leaves_data_entry(self):
		out = self.data_screen("released")
		self.assert_is_notice(out)
		self.assertIsNone(out["data"])
		self.assertEqual(out["state"], "result")

	def test_other_closed_load_stays_an_error_on_both_tabs(self):
		self.assert_is_error(self.release_screen("closed"))
		out = self.data_screen("closed")
		self.assert_is_error(out)
		self.assertEqual(out["state"], "error")


T3 = "public/js/station_t3.js"
SHELL = "ui/page/station/station.js"
T3_STATION = """
globalThis.TcStepQueue = class {
	constructor() { this.items = []; this.failed = null; }
	reset() {}
	load() {}
	html() { return '<section class="QUEUE"></section>'; }
};
const station = makeStation();
let rendered = "";
let revealed = [];
let scrolled = [];
station.setState = (state, html) => { rendered = html; };
station.form = element();
station.revealNotice = (notice) => revealed.push(notice);
station.scrollResultIntoView = (target, below) => scrolled.push([target, below]);
const t3 = new T3Assembly(station);
const line = (code, extra = {}) => ({
	instrument: code, instrument_name: "Kep " + code, bom_qty: 2, actual_qty: 2, counted: 1,
	line_status: "Enough", position: 1, ...extra,
});
const ASM = {
	assembly: "A-1", docstatus: 0, bom_version: 1, cycle_no: 1, gates: [{step: "T1", result: "Pass"}],
	set: {set_id: "S-1", set_name: "Bo mo", status: "Processing", method: "Steam"},
	lines: [line("I-1"), line("I-2", {counted: 0, line_status: ""})],
	tally: {enough: 1, total: 2, counted: 1}, uncounted: [], unexplained: [], pack_locked: true,
};
"""


class TestStationQueues(FrappeTestCase):
	"""Hàng chờ T3/T4 vẫn hiện khi chưa mở bộ, kể cả cạnh thông báo lỗi."""

	def test_t4_queue_shows_beside_an_error(self):
		out = run_js(
			self,
			[ERR, T4],
			[[], ["T4Packing"]],
			FAKE_STATION
			+ """
			const station = makeStation();
			let rendered = "";
			station.setState = (state, html) => { rendered = html; };
			station.revealNotice = () => {};
			station.form = element();
			const t4 = new T4Packing(station);
			let finished = null;
			let items = null;
			t4.queue = {
				get items() { return items; },
				failed: null,
				load(done) { finished = done; },
				html: () => (items ? "<section>LOADED</section>" : "<section>WAITING</section>"),
				reset() {},
			};
			t4.notice = {variant: "error", title: "Bad", reason: "r", action: "a"};
			t4.show();
			const first = rendered;
			items = [];
			finished();
			emit({first, after: rendered});
			""",
		)
		self.assertIn("WAITING", out["first"])
		self.assertIn("Bad", out["first"])
		self.assertIn("LOADED", out["after"])
		self.assertIn("Bad", out["after"])

	def test_t3_queue_shows_beside_an_error(self):
		out = run_js(
			self,
			[ERR, T3],
			[[], ["T3Assembly"]],
			FAKE_STATION
			+ T3_STATION
			+ """
			t3.notice = {variant: "error", title: "Bad", reason: "r", action: "a"};
			t3.show();
			emit(rendered);
			""",
		)
		self.assertIn("QUEUE", out)
		self.assertIn("Bad", out)


class TestT3Layout(FrappeTestCase):
	"""#1827: tên bộ và trạng thái dính dưới ô quét; quét xong thấy ngay các dòng."""

	def test_set_name_and_status_are_in_a_sticky_bar(self):
		out = run_js(
			self,
			[ERR, T3],
			[[], ["T3Assembly"]],
			FAKE_STATION + T3_STATION + "t3.asm = ASM; t3.show(); emit(rendered);",
		)
		bar = out[out.index("tc-t3-setbar") : out.index("</div>", out.index("tc-t3-setbar"))]
		self.assertIn("S-1", bar)
		self.assertIn("Bo mo", bar)
		self.assertIn("Processing", bar)
		self.assertLess(out.index("tc-t3-setbar"), out.index("tc-gates"))

	def test_opening_a_set_scrolls_to_the_lines_below_the_bar(self):
		out = run_js(
			self,
			[ERR, T3],
			[[], ["T3Assembly"]],
			FAKE_STATION
			+ T3_STATION
			+ """
			const bar = {offsetHeight: 60};
			const lines = {name: "lines"};
			station.result.querySelector = (selector) =>
				selector === ".tc-t3-setbar" ? bar : selector.includes(".tc-t3-lines") ? lines : null;
			t3.onOpen(ASM);
			emit(scrolled.map(([target, below]) => [target && target.name, below]));
			""",
		)
		self.assertEqual(out, [["lines", 60]])


class TestT3VarianceForm(FrappeTestCase):
	"""#1842: nút trên dòng đóng biểu mẫu cũ; lỗi lưu biểu mẫu hiện ngay tại biểu mẫu."""

	BEFORE = (
		FAKE_STATION
		+ T3_STATION
		+ """
		t3.asm = ASM;
		t3.request = () => {};
		t3.openVariance("I-1", 1);
		t3.form.note = "cu";
		"""
	)

	def run_t3(self, body):
		return run_js(self, [ERR, T3], [[], ["T3Assembly"]], self.BEFORE + body)

	def test_all_present_closes_the_open_form(self):
		self.assertIsNone(
			self.run_t3('t3.onAction("t3-full", {dataset: {instrument: "I-1"}}); emit({f: t3.form});')["f"]
		)

	def test_stepping_back_to_the_bom_closes_the_open_form(self):
		out = self.run_t3('t3.onAction("t3-inc", {dataset: {instrument: "I-1"}}); emit({f: t3.form});')
		self.assertIsNone(out["f"])

	def test_stepping_away_from_the_bom_updates_the_form_quantity(self):
		out = self.run_t3('t3.onAction("t3-dec", {dataset: {instrument: "I-1"}}); emit(t3.form);')
		self.assertEqual(out["qty"], 0)

	def test_form_error_is_rendered_at_the_form(self):
		out = self.run_t3(
			"""
			t3.form.note = "";
			t3.form.choice = "Short";
			t3.saveVariance();
			emit({top: t3.noticeHtml(), html: rendered});
			"""
		)
		self.assertNotIn("tc-alert-error", out["top"])
		form = out["html"][out["html"].index("tc-t3-form") :]
		self.assertIn("tc-alert-error", form)
		self.assertLess(form.index("tc-alert-error"), form.index("t3-variance-save"))


class TestRevealNotice(FrappeTestCase):
	"""Thông báo chặn nằm ngoài khung nhìn thì cuộn tới, mỗi thông báo một lần."""

	FAKE_SHELL = """
	window.innerHeight = 768;
	let scrolls = 0;
	const node = {
		top: -790,
		getBoundingClientRect() { return {top: this.top, bottom: this.top + 100}; },
		scrollIntoView() { scrolls += 1; },
	};
	const shell = {
		result: {querySelector: () => node},
		form: {offsetHeight: 100},
		root: {style: {setProperty() {}}},
		syncStickyHeight: TraceCoreStation.prototype.syncStickyHeight,
	};
	const reveal = (notice) => TraceCoreStation.prototype.revealNotice.call(shell, notice);
	"""

	def run_shell(self, body):
		return run_js(self, [SHELL], [["TraceCoreStation"]], self.FAKE_SHELL + body)

	def test_scrolls_once_per_notice(self):
		out = self.run_shell(
			"""
			const notice = {variant: "error", title: "x"};
			reveal(notice);
			reveal(notice);
			emit({scrolls});
			"""
		)
		self.assertEqual(out["scrolls"], 1)

	def test_visible_notice_does_not_scroll(self):
		out = self.run_shell('node.top = 200; reveal({variant: "error"}); emit({scrolls});')
		self.assertEqual(out["scrolls"], 0)

	def test_notice_under_the_sticky_scan_box_scrolls(self):
		out = self.run_shell('node.top = 50; reveal({variant: "error"}); emit({scrolls});')
		self.assertEqual(out["scrolls"], 1)

	def test_confirm_prompt_scrolls_but_plain_info_does_not(self):
		out = self.run_shell(
			"""
			reveal({variant: "ok", title: "x"});
			const info = scrolls;
			reveal({variant: "warn", code: "CONFIRM_INCOMPLETE"});
			emit({info, confirm: scrolls});
			"""
		)
		self.assertEqual(out, {"info": 0, "confirm": 1})

	def test_t1_confirm_prompt_is_revealed(self):
		out = run_js(
			self,
			[ERR, T1],
			[[], ["T1Receiving"]],
			FAKE_STATION
			+ T1_ITEM
			+ """
			delete t1.show;
			let got = null;
			t1.station.revealNotice = (notice) => { got = notice; };
			t1.loaded = true;
			t1.receiptHtml = () => "";
			t1.todayHtml = () => "";
			t1.watchImages = () => {};
			t1.station.form = element();
			item.lines[0].actual_qty = 1;
			t1.confirmSet();
			emit({code: got && got.code});
			""",
		)
		self.assertEqual(out["code"], "CONFIRM_INCOMPLETE")


class TestT1DifferingQuantityWording(FrappeTestCase):
	"""Lệch số lượng không phải "chưa xác nhận"; gắn cờ do lệch không gọi là "ghi chú bất thường"."""

	def confirm(self, setup):
		return run_js(
			self,
			[ERR, T1],
			[[], ["T1Receiving"]],
			FAKE_STATION
			+ T1_ITEM
			+ f"""
			t1.request = (name, args, done) => done({{item: {{set_id: "S1", needs_review: 1}}}});
			t1.upsertSummary = () => {{}};
			t1.waiting = [];
			item.lines[0].actual_qty = 1;
			{setup}
			t1.confirmSet(true);
			emit(t1.notice);
			""",
		)

	def test_prompt_title_says_the_quantity_differs(self):
		out = run_js(
			self,
			[ERR, T1],
			[[], ["T1Receiving"]],
			FAKE_STATION + T1_ITEM + "item.lines[0].actual_qty = 1; t1.confirmSet(); emit(t1.notice);",
		)
		self.assertEqual(out["title"], "Quantity differs from the set list")

	def test_flagged_by_mismatch_without_note(self):
		self.assertEqual(self.confirm("")["reason"], "The set quantity differs; assembly will check it.")

	def test_flagged_with_a_note_keeps_abnormal_note_wording(self):
		self.assertIn("abnormal note", self.confirm('t1.notes.S1 = "Thieu keo";')["reason"])

	def test_summary_counts_sets_needing_review(self):
		out = run_js(
			self,
			[ERR, T1],
			[[], ["T1Receiving"]],
			FAKE_STATION
			+ T1_ITEM
			+ """
			t1.receipt.items = [{set_id: "S1", set_name: "Bo", needs_review: 1, confirmed: 1}];
			emit(t1.listHtml());
			""",
		)
		self.assertIn("1 sets received · 1 need review", out)
		self.assertNotIn("abnormal note", out)
		self.assertIn("Needs review", out)


class TestPrintWarningTitle(FrappeTestCase):
	"""Trạm chưa có máy in thì nói đúng thế; nhãn không dựng được thì nói mã vẫn giữ, không nhắc phần mềm trạm (A-101)."""

	CASES = (("T5Load", T5, "ME-1", "load"), ("T2Wash", T2, "LR-1", "batch"))

	def note(self, cls, path, key, code):
		return run_js(
			self,
			[ERR, path],
			[[], [cls]],
			FAKE_STATION
			+ f"""
			const screen = new {cls}(makeStation());
			screen.done = {{{key}: "X", print: {{print_job: "PJ-1", printer: null,
				warning: {{code: "{code}", reason: "r", action: "a"}}}}}};
			screen.printNote = {{kind: "waiting"}};
			emit(screen.printNoteHtml());
			""",
		)

	def test_no_printer_title(self):
		for cls, path, _code, key in self.CASES:
			with self.subTest(cls=cls):
				out = self.note(cls, path, key, "NO_PRINTER_AT_STATION")
				self.assertIn("No printer at this station, the label is waiting", out)
				self.assertNotIn("Station Agent", out)

	def test_render_failure_wording(self):
		for cls, path, _code, key in self.CASES:
			with self.subTest(cls=cls):
				out = self.note(cls, path, key, "LABEL_RENDER_FAILED")
				self.assertIn("kept, the label was not printed", out)
				self.assertNotIn("Station Agent", out)


class TestDecimalDisplay(FrappeTestCase):
	"""CLAUDE.md: dấu phẩy thập phân, cả số điền sẵn trong ô và nhãn dải giá trị."""

	SCHEMA = """
	frappe = {boot: {time_zone: {system: "Asia/Ho_Chi_Minh"}}};
	const context = {
		batch: "LR-1", sets: [], equipment: {name: "M1"}, prefill: {},
		parameter_schema: [{parameter_name: "Nhiet do", unit: "C", required: 1, min_value: 90.5, max_value: 95.5, default_value: 92.5}],
	};
	"""

	def test_helper(self):
		out = run_js(
			self,
			[ERR],
			[[]],
			"""
			emit([92.5, "92.5", "-1.25", 92, "92,5", "abc.def", null, "1.2.3"].map((value) => window.tcDecimal(value)));
			""",
		)
		self.assertEqual(out, ["92,5", "92,5", "-1,25", "92", "92,5", "abc.def", "", "1.2.3"])

	def test_t5_form_shows_commas(self):
		out = run_js(
			self,
			[ERR, T5],
			[[], ["T5Load"]],
			FAKE_STATION
			+ self.SCHEMA
			+ """
			const t5 = new T5Load(makeStation());
			t5.data = {context};
			context.equipment = {name: "M1"};
			t5.form = {values: {"Nhiet do": window.tcDecimal(92.5)}, started: "", ended: "", alerts: "no", alertsText: "", reason: "", card: ""};
			emit(t5.formHtml());
			""",
		)
		self.assertIn('value="92,5"', out)
		self.assertIn("90,5", out)
		self.assertIn("95,5", out)
		self.assertNotIn("92.5", out)

	def test_t2_form_shows_commas(self):
		out = run_js(
			self,
			[ERR, T2],
			[[], ["T2Wash"]],
			FAKE_STATION
			+ self.SCHEMA
			+ """
			const t2 = new T2Wash(makeStation());
			t2.unload = {context};
			t2.form = {values: {"Nhiet do": window.tcDecimal(92.5)}, started: "", ended: "", alerts: "no", alertsText: "", reason: "", card: "", chemicalName: ""};
			emit(t2.manualFormHtml(context));
			""",
		)
		self.assertIn('value="92,5"', out)
		self.assertIn("90,5", out)
		self.assertNotIn("92.5", out)

	def test_prefill_values_become_commas(self):
		for cls, path, screen_name, args in (
			("T5Load", T5, "t5", "t5.data = {};"),
			("T2Wash", T2, "t2", "t2.unload = {};"),
		):
			with self.subTest(cls=cls):
				out = run_js(
					self,
					[ERR, path],
					[[], [cls]],
					FAKE_STATION
					+ f"""
					frappe = {{boot: {{time_zone: {{system: "Asia/Ho_Chi_Minh"}}}}}};
					const {screen_name} = new {cls}(makeStation());
					{args}
					{screen_name}.show = () => {{}};
					{screen_name}.request = (method, rpc, done) => done({{
						load: {{packs: [], sets: [], equipment: {{name: "M"}}, prefill: {{values: {{A: 92.5}}}}, params: [{{parameter_name: "B", value: 1.5}}]}},
						batch: {{sets: [], equipment: {{name: "M"}}, prefill: {{values: {{A: 92.5}}}}, machine_data: {{parameters: [{{parameter_name: "B", value: 1.5}}]}}}},
					}});
					{screen_name}.fetchContext();
					emit({screen_name}.form.values);
					""",
				)
				self.assertEqual(out, {"A": "92,5", "B": "1,5"})


class TestT2SetNames(FrappeTestCase):
	"""#1836: Bộ trong lô hiện tên bộ kèm mã, mã giữ font mã định danh."""

	EXPECTED = 'Bo mo (<span class="tc-mono">S1</span>)'

	def t2(self, body):
		return run_js(self, [ERR, T2], [[], ["T2Wash"]], FAKE_STATION + T2_DONE + body)

	def test_done_card(self):
		out = self.t2('t2.done.set_rows = [{set_id: "S1", set_name: "Bo mo"}]; emit(t2.doneHtml());')
		self.assertIn(self.EXPECTED, out)

	def test_lookup_card(self):
		out = self.t2(
			"""
			emit(t2.lookupHtml({batch: "LR-1", status: "Running", equipment: {name: "M"}, program: {},
				chemicals: [], sets: [{set_id: "S1", set_name: "Bo mo"}]}));
			"""
		)
		self.assertIn(self.EXPECTED, out)

	def test_running_card(self):
		out = self.t2(
			"""
			t2.statusBadge = () => "";
			emit(t2.batchCardHtml({batch: "LR-1", sets: ["S1"], set_rows: [{set_id: "S1", set_name: "Bo mo"}]}));
			"""
		)
		self.assertIn(self.EXPECTED, out)

	def test_code_only_when_name_unknown(self):
		out = self.t2("emit(t2.doneHtml());")
		self.assertIn('<span class="tc-mono">S1</span>', out)


class TestDailyTestNoTestLabel(FrappeTestCase):
	def test_not_applicable_uses_the_normal_font(self):
		source = frappe.read_file(frappe.get_app_path("tracecore", "public/js/station_daily_test.js"))
		start = source.index("const noTest")
		self.assertNotIn("tc-tag", source[start : source.index("return `<tr>", start)])


class TestT5ConfirmLine(FrappeTestCase):
	def test_shows_the_employee_name_not_the_code(self):
		out = run_js(
			self,
			[ERR, T5],
			[[], ["T5Load"]],
			FAKE_STATION
			+ """
			const station = makeStation();
			station.session = {employee: "NV-00009", employee_name: "An Nguyen", roles: []};
			const t5 = new T5Load(station);
			t5.data = {context: {equipment: {name: "M1"}, parameter_schema: []}};
			t5.form = {values: {}, started: "", ended: "", alerts: "no", alertsText: "", reason: "", card: ""};
			emit(t5.formHtml());
			""",
		)
		self.assertIn("I, An Nguyen, confirm", out)
		self.assertNotIn("NV-00009", out)


T5B = "public/js/station_t5b.js"
T6 = "public/js/station_t6.js"
T7 = "public/js/station_t7.js"
T3 = "public/js/station_t3.js"
SHELL = "ui/page/station/station.js"


class TestT5RejectBlock(FrappeTestCase):
	"""A-102: khối Loại mẻ chỉ cho R02, R01; KTV ghi Không đạt thấy cần giám sát CSSD xử lý."""

	CTX = """
	const station = makeStation();
	station.session = {roles: ROLES};
	const screen = new T5Release(station);
	const ctx = {load: "ME-1", cycle_result: RESULT, indicator_state: {}, needs_review: 0};
	emit(screen.releaseHtml(ctx, []));
	"""

	def html(self, roles, result="Fail"):
		body = self.CTX.replace("ROLES", repr(list(roles))).replace("RESULT", repr(result))
		return run_js(self, [ERR, T5, T5B], [[], ["T5Load"], ["T5Release"]], FAKE_STATION + body)

	def test_supervisors_see_the_reject_block(self):
		for role in ("TC R02", "TC R01"):
			self.assertIn('data-action="t5b-reject"', self.html([role]))

	def test_technician_sees_who_must_handle_a_failed_load(self):
		out = self.html(["TC R05"])
		self.assertNotIn("t5b-reject", out)
		self.assertIn("A CSSD supervisor must handle this load", out)

	def test_technician_with_a_passed_load_has_no_such_message(self):
		out = self.html(["TC R05"], "Pass")
		self.assertNotIn("t5b-reject", out)
		self.assertNotIn("A CSSD supervisor must handle this load", out)


class TestT5UnloadLists(FrappeTestCase):
	"""A-102: tab Dỡ mẻ tách Mẻ chờ dỡ và Mẻ chờ giải phóng."""

	BODY = """
	const screen = new T5Release(makeStation());
	const row = (id, unloaded) => ({id, equipment: "M", equipment_name: "May", program: "P", started_at: null,
		status: "Cycle Complete", count: 1, requires_bi: 0, unloaded});
	screen.running = ROWS;
	emit(screen.waitingHtml());
	"""

	def html(self, rows):
		return run_js(
			self,
			[ERR, T5, T5B],
			[[], ["T5Load"], ["T5Release"]],
			FAKE_STATION + self.BODY.replace("ROWS", rows),
		)

	def test_two_lists_and_the_status_label(self):
		out = self.html('[row("ME-A", false), row("ME-B", true)]')
		self.assertIn("Loads waiting to unload (1)", out)
		self.assertIn("Loads waiting for release (1)", out)
		self.assertIn("Waiting for release", out)
		self.assertNotIn("Unloaded", out)
		self.assertLess(out.index("ME-A"), out.index("Loads waiting for release"))
		self.assertLess(out.index("Loads waiting for release"), out.index("ME-B"))

	def test_each_cell_has_its_label_for_the_narrow_layout(self):
		out = self.html('[row("ME-A", false)]')
		self.assertIn('class="tc-t6-table tc-t5b-waiting"', out)
		self.assertIn('data-label="Sterilizer"', out)

	def test_only_waiting_for_release_has_no_empty_unload_list_twice(self):
		out = self.html('[row("ME-B", true)]')
		self.assertNotIn("No load is waiting.", out)  # không hiện danh sách chờ dỡ rỗng cạnh danh sách có mẻ
		self.assertIn("Loads waiting for release (1)", out)

	def test_css_keeps_words_whole_and_stacks_on_narrow_screens(self):
		with open(
			frappe.get_app_path("tracecore", "ui", "page", "station", "station.css"), encoding="utf-8"
		) as handle:
			css = handle.read()
		self.assertIn(".tc-t5b-waiting td::before", css)
		self.assertRegex(css, r"\.tc-t5b-waiting[^{]*\{[^}]*overflow-wrap: normal")


class TestT5AlertsOption(FrappeTestCase):
	def test_t5_uses_the_same_no_as_t2_not_the_none_string(self):
		with open(frappe.get_app_path("tracecore", *T5.split("/")), encoding="utf-8") as handle:
			source = handle.read()
		self.assertNotIn('__("None")', source)
		self.assertRegex(source, r'value="no"[^\n]*__\("No"\)')


class TestT6BlockedScan(FrappeTestCase):
	def test_block_drops_the_open_pack_so_no_shelf_prompt_shows(self):
		out = run_js(
			self,
			[T6],
			[["T6Storage"]],
			FAKE_STATION
			+ """
			const t6 = new T6Storage(makeStation());
			t6.show = () => {};
			t6.pack = {cycle_id: "CY-OLD", status: "Released"};
			t6.reject({code: "PACK_NOT_RELEASED", title: "t", reason: "r", action: "a"});
			emit({pack: t6.pack, notice: t6.notice.code});
			""",
		)
		self.assertIsNone(out["pack"])
		self.assertEqual(out["notice"], "PACK_NOT_RELEASED")


class TestT7DepartmentWarning(FrappeTestCase):
	BODY = """
	const t7 = new T7Issue(makeStation());
	t7.station.station = "TR-7";
	t7.show = () => {};
	t7.issue = {issue_note: "IN-1", packs: []};
	const calls = [];
	t7.request = (name, args) => calls.push([name, args]);
	t7.reject({code: "PACK_DEPT_MISMATCH", title: "t", reason: "r", action: "a"}, {args: {raw: "CY-1", note: "ghi chu"}});
	"""

	def run_t7(self, body):
		return run_js(self, [T7], [["T7Issue"]], FAKE_STATION + self.BODY + body)

	def test_dialog_asks_for_a_reason_and_resends_with_it(self):
		out = self.run_t7(
			"""
			const dialog = t7.dialogsHtml();
			const variant = t7.notice.variant;
			t7.field = () => "Khoa muon";
			t7.onAction("dept-mismatch-submit", element());
			emit({dialog, calls, variant});
			"""
		)
		self.assertIn("tc-t7-dept-reason", out["dialog"])
		self.assertEqual(out["variant"], "warn")
		self.assertEqual(out["calls"][0][0], "add_pack")
		args = out["calls"][0][1]
		self.assertEqual(
			(args["raw"], args["department_reason"], args["note"]), ("CY-1", "Khoa muon", "ghi chu")
		)

	def test_empty_reason_sends_nothing(self):
		out = self.run_t7(
			"""
			t7.field = () => "";
			t7.markInvalid = () => {};
			t7.onAction("dept-mismatch-submit", element());
			emit({calls});
			"""
		)
		self.assertEqual(out["calls"], [])


class TestT3ConfirmAll(FrappeTestCase):
	BODY = """
	window.TcStepQueue = class { reset() {} };
	const t3 = new T3Assembly(makeStation());
	t3.show = () => {};
	t3.asm = {assembly: "AS-1", bom_version: 1, docstatus: 0, lines: [], tray_images: [], tally: {}};
	"""

	def test_button_and_request(self):
		out = run_js(
			self,
			[T3],
			[["T3Assembly"]],
			FAKE_STATION
			+ self.BODY
			+ """
			const html = t3.linesHtml();
			const calls = [];
			t3.request = (name, args) => calls.push(args);
			t3.onAction("t3-all", element());
			emit({html, calls});
			""",
		)
		self.assertIn('data-action="t3-all"', out["html"])
		self.assertIn("Confirm all components", out["html"])
		self.assertEqual(out["calls"], [{"assembly": "AS-1", "all_ok": 1}])

	def test_no_button_on_a_recorded_assembly(self):
		out = run_js(
			self,
			[T3],
			[["T3Assembly"]],
			FAKE_STATION + self.BODY + "t3.asm.docstatus = 1; emit(t3.linesHtml());",
		)
		self.assertNotIn("t3-all", out)


class TestOpenStationByUrl(FrappeTestCase):
	"""A-102, #1822: mở trạm khác bằng URL đi đúng đường của nút chuyển trạm khi phiên thẻ còn."""

	FAKE = """
	const store = {};
	sessionStorage = window.sessionStorage = {
		getItem: (key) => (key in store ? store[key] : null),
		setItem: (key, value) => { store[key] = value; },
		removeItem: (key) => { delete store[key]; },
	};
	store["tc-station-active"] = JSON.stringify({station: "TR-3", token: "old"});
	const calls = [];
	let answer = {ok: true, session: {token: "new"}};
	const shell = {
		station: "TR-4",
		rpc: async (method, args) => { calls.push([method, args]); return answer; },
		storedToken(value) { if (value) store["tc-station-session:TR-4"] = value; return store["tc-station-session:TR-4"]; },
		restoreSession: async (token) => calls.push(["restore", token]),
		renderLogin: (error) => calls.push(["login", error ? error.code : null]),
		activeSession: TraceCoreStation.prototype.activeSession,
		rememberActive: TraceCoreStation.prototype.rememberActive,
	};
	const adopt = () => TraceCoreStation.prototype.adoptSession.call(shell);
	"""

	def run_shell(self, body):
		return run_js(self, [SHELL], [["TraceCoreStation"]], self.FAKE + body)

	def test_valid_same_zone_session_uses_switch_station_then_restores(self):
		out = self.run_shell("const done = await adopt(); emit({done, calls});")
		self.assertTrue(out["done"])
		self.assertEqual(out["calls"][0][0], "tracecore.v1.station.switch_station")
		self.assertEqual((out["calls"][0][1]["token"], out["calls"][0][1]["station"]), ("old", "TR-4"))
		self.assertEqual(out["calls"][1], ["restore", "new"])

	def test_no_session_elsewhere_means_card_screen(self):
		out = self.run_shell(
			'delete store["tc-station-active"]; const done = await adopt(); emit({done, calls});'
		)
		self.assertFalse(out["done"])
		self.assertEqual(out["calls"], [])

	def test_other_zone_goes_to_rescan_with_the_reason_and_forgets_the_token(self):
		out = self.run_shell(
			"""
			answer = {ok: false, error: {code: "STATION_ZONE_RESCAN", reason: "r", action: "a"}};
			const done = await adopt();
			emit({done, calls, active: store["tc-station-active"] || null});
			"""
		)
		self.assertTrue(out["done"])
		self.assertEqual(out["calls"][-1], ["login", "STATION_ZONE_RESCAN"])
		self.assertIsNone(out["active"])

	def test_missing_competency_shows_the_block_and_keeps_the_old_session(self):
		out = self.run_shell(
			"""
			answer = {ok: false, error: {code: "COMPETENCY_REQUIRED", reason: "r", action: "a"}};
			await adopt();
			emit({calls, active: store["tc-station-active"] || null});
			"""
		)
		self.assertEqual(out["calls"][-1], ["login", "COMPETENCY_REQUIRED"])
		self.assertTrue(out["active"])

	def test_expired_session_is_plain_card_screen(self):
		out = self.run_shell(
			"""
			answer = {ok: false, error: {code: "SESSION_EXPIRED", reason: "r", action: "a"}};
			const done = await adopt();
			emit({done, active: store["tc-station-active"] || null});
			"""
		)
		self.assertFalse(out["done"])
		self.assertIsNone(out["active"])
