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
t5.printNoteHtml = () => "";
"""
T2_DONE = """
const station = makeStation();
const t2 = new T2Wash(station);
t2.done = {batch: "LR-261101-07", sets: ["S1"], rejected: [], chemicals: [], qr_png_b64: "QQ==",
	machine: {name: "M1", equipment_name: "May 1"}, program_name: "P1", at: "2026-11-01T08:00:00+07:00",
	print: {print_job: "PJ-1", status: "Queued", printer: "PRN-001", zpl: "^XA^XZ", warning: null}};
t2.printNoteHtml = () => "";
"""


class TestLabelPdfButton(FrappeTestCase):
	"""A-99, A-100: nút Lưu PDF nhãn trên thẻ Hoàn thành nạp T5, T2 khi trạm có máy in; T4 không có."""

	def t5(self, body):
		return run_js(self, [ERR, T5], [[], ["T5Load"]], FAKE_STATION + T5_DONE + body)

	def t2(self, body):
		return run_js(self, [ERR, T2], [[], ["T2Wash"]], FAKE_STATION + T2_DONE + body)

	def test_t5_card_has_the_enabled_button_online(self):
		out = self.t5("emit(t5.doneHtml());")
		self.assertRegex(out, r'<button[^>]*data-action="t5-label-pdf"')
		self.assertNotRegex(out, r'data-action="t5-label-pdf"[^>]*disabled')

	def test_no_printer_shows_only_the_code_and_the_click_does_nothing(self):
		"""A-100: không có máy in, hoặc nhãn không dựng được: chỉ còn dòng mã như trước A-99."""
		for card, runner, code in (("t5", self.t5, "ME-261101-02"), ("t2", self.t2, "LR-261101-07")):
			with self.subTest(card=card):
				out = runner(
					f"""
					{card}.done.print = {{print_job: "PJ-1", status: "Waiting", printer: null, zpl: null,
						warning: {{code: "NO_PRINTER_AT_STATION", title: "t", reason: "r", action: "a"}}}};
					const html = {card}.doneHtml();
					const calls = [];
					{card}.request = (rpc) => calls.push(rpc);
					{card}.show = () => {{}};
					{card}.saveLabelPdf();
					emit({{html, calls}});
					"""
				)
				self.assertNotIn(f"{card}-label-pdf", out["html"])
				self.assertNotIn("Save label PDF", out["html"])
				self.assertNotIn("tc-code-row", out["html"])
				self.assertIn(f'<p class="tc-cycle">{code}</p>', out["html"])
				self.assertEqual(out["calls"], [])

	def test_t5_offline_disables_the_button_with_a_reason(self):
		out = self.t5("t5.offline = true; emit(t5.doneHtml());")
		self.assertRegex(out, r'data-action="t5-label-pdf"[^>]*disabled')
		self.assertIn("network connection", out)

	def test_t5_click_requests_the_rpc_and_saves_the_file(self):
		out = self.t5(
			"""
			const calls = [];
			t5.request = (method, args, onOk) => { calls.push([method, args]);
				onOk({ok: true, pdf_b64: "JVBERg==", filename: "ME-261101-02.pdf"}); };
			const saved = [];
			window.tcSavePdf = (b64, name) => saved.push([b64, name]);
			station.station = "TR-005";
			t5.show = () => {};
			t5.onAction("t5-label-pdf", element());
			emit({calls, saved});
			"""
		)
		self.assertEqual(
			out["calls"], [["tracecore.v1.load.label_pdf", {"load": "ME-261101-02", "station": "TR-005"}]]
		)
		self.assertEqual(out["saved"], [["JVBERg==", "ME-261101-02.pdf"]])

	def test_t2_card_and_click(self):
		out = self.t2(
			"""
			const html = t2.doneHtml();
			const calls = [];
			t2.request = (method, args) => calls.push([method, args]);
			station.station = "TR-002";
			t2.onAction("t2-label-pdf", element());
			t2.offline = true;
			emit({html, calls, off: t2.doneHtml()});
			"""
		)
		self.assertIn('data-action="t2-label-pdf"', out["html"])
		self.assertEqual(
			out["calls"], [["tracecore.v1.wash.label_pdf", {"batch": "LR-261101-07", "station": "TR-002"}]]
		)
		self.assertRegex(out["off"], r'data-action="t2-label-pdf"[^>]*disabled')

	def test_t4_has_no_label_pdf_button(self):
		with open(
			frappe.get_app_path("tracecore", "public", "js", "station_t4.js"), encoding="utf-8"
		) as handle:
			self.assertNotIn("label_pdf", handle.read())

	def test_strings_are_translated(self):
		path = frappe.get_app_path("tracecore", "translations", "vi.csv")
		with open(path, encoding="utf-8", newline="") as handle:
			translated = {row[0]: row[1] for row in csv.reader(handle) if row}
		for text in ("Save label PDF", "Saving a label PDF needs a network connection."):
			self.assertTrue(translated.get(text), msg=text)


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
				for hidden in ("tc-t5b-pin", "tc-t5b-reason", "t5b-release"):
					self.assertNotIn(hidden, html)
				self.assertNotRegex(html, r"R0\d")
				self.assertIn("t5b-reject", html)  # mẻ Không đạt giữ nguyên

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
			screen.ctx = {name: "ME-261101-09"};
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
