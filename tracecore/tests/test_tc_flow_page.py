"""FEAT-099 (A-158): Page tc-flow, giao diện người dùng cho luồng xử lý dụng cụ, dùng lại màn trạm hiện có."""

import json
import re
import subprocess
from pathlib import Path

import frappe
from frappe.tests.utils import FrappeTestCase

from tracecore.tests import js_harness
from tracecore.tests.js_harness import run_js

# lớp con của khung gọi hoặc ghi đè các method này của TraceCoreStation; đổi tên ở Page station thì test này báo
HOST_METHODS = [
	"adoptStationAddress",
	"applyStation",
	"openStation",
	"renderStationPills",
	"renderNetStatus",
	"activateSession",
	"clearSession",
	"focus",
	"switchStation",
	"endSession",
	"storeNotice",
	"rpcRead",
	"failureCause",
	"isOffline",
	"show",
	"hide",
	"dispose",
]

SHELL = "public/js/tc_flow_shell.js"
PAGE_DIR = Path(frappe.get_app_path("tracecore", "ui", "page", "tc_flow"))

STATIONS = """
const stations = [
	{ name: "TR-008", label: "Usage OR", station_no: 8, functions: ["USE"], implemented: true },
	{ name: "TR-002", label: "T2 Wash", station_no: 2, functions: ["WASH_LOAD", "WASH_UNLOAD"], implemented: true },
	{ name: "TR-001", label: "Receiving", station_no: 1, functions: ["RECEIVE"], implemented: true },
	{ name: "TR-020", label: "Linen", station_no: 20, functions: ["LINEN"], implemented: true },
	{ name: "TR-004", label: "Pack", station_no: 4, functions: ["PACK"], implemented: false },
	{ name: "TR-005", label: "Sterilize", station_no: 5, functions: ["STERI_LOAD"], implemented: true },
	{ name: "TR-05B", label: "Release", station_no: 5, functions: ["STERI_UNLOAD"], implemented: true },
];
"""


def run(testcase, body):
	return run_js(testcase, [SHELL], [["TcFlow"]], STATIONS + body)


class TestTcFlowShell(FrappeTestCase):
	def test_address_stays_on_the_new_page(self):
		out = run(
			self,
			"""emit({
				home: TcFlow.path(null),
				station: TcFlow.path("TR 001"),
				param: TcFlow.stationParam("?station=TR-001&x=1"),
				none: TcFlow.stationParam(""),
			});""",
		)
		self.assertEqual(out["home"], "/app/tc-flow")
		self.assertEqual(out["station"], "/app/tc-flow?station=TR%20001")
		self.assertEqual(out["param"], "TR-001")
		self.assertIsNone(out["none"])

	def test_station_lists_keep_only_the_instrument_flow(self):
		out = run(
			self,
			"""emit({
				ktv: TcFlow.ktvStations(stations).map((s) => s.name),
				dept: TcFlow.deptStations(stations).map((s) => s.name),
				modes: [TcFlow.mode(stations[0]), TcFlow.mode(stations[1]), TcFlow.mode(null)],
				labels: TcFlow.ktvStations(stations).map((s) => TcFlow.stationLabel(s)),
			});""",
		)
		# trạm đồ vải và trạm chưa có màn không vào danh sách; thứ tự theo số trạm
		self.assertEqual(out["ktv"], ["TR-001", "TR-002", "TR-005", "TR-05B"])
		self.assertEqual(out["dept"], ["TR-008"])
		self.assertEqual(out["modes"], ["dept", "ktv", "ktv"])
		self.assertEqual(out["labels"][:2], ["T1 Receiving", "T2 Wash"])

	def test_stepper_marks_done_and_current_steps(self):
		out = run(self, """emit(TcFlow.stepper(stations, "TR-005"));""")
		self.assertEqual([step["no"] for step in out], [1, 2, 5, 8])
		self.assertEqual([step["state"] for step in out], ["done", "done", "current", "todo"])
		self.assertEqual(out[0]["label"], "T1 Receiving")

	def test_stock_counts_and_trace_rows(self):
		out = run(
			self,
			"""const overview = {
				at_department: [
					{ cycle_id: "CY-1", set_name: "A", expiry: "2026-12-01", expiring: false },
					{ cycle_id: "CY-2", set_name: "B", expiry: "2026-11-15", expiring: true },
				],
				waiting_return: [{ cycle_id: "CY-3", set_name: "C" }],
			};
			const chain = { cycle_id: "CY-1", set_id: "S-1", events: [
				{ step: "T2", label: "Wash", at: "2026-11-01 08:10:00", user: "a@x", user_name: "An",
					equipment: "MR-01", ref_name: "LR-1", result: "Pass" },
				{ step: "T8", label: "Use", at: "2026-11-02 09:41:00", user: "b@x", user_name: null, ref_name: null },
			] };
			emit({
				counts: TcFlow.stockCounts(overview),
				empty: TcFlow.stockCounts(null),
				rows: TcFlow.traceRows(chain),
				byCycle: TcFlow.traceArgs(" cy-261101-0001 "),
				bySet: TcFlow.traceArgs("(01)0893(21)DB01-007"),
			});""",
		)
		self.assertEqual(out["counts"], {"held": 2, "expiring": 1, "waiting": 1})
		self.assertEqual(out["empty"], {"held": 0, "expiring": 0, "waiting": 0})
		self.assertEqual(out["rows"][0]["step"], "T2")
		self.assertEqual(out["rows"][0]["detail"], "Wash · LR-1 · Pass")
		self.assertEqual(out["rows"][0]["who"], "MR-01 / An")
		self.assertEqual(out["rows"][1]["who"], "b@x")
		self.assertEqual(out["byCycle"], {"cycle_id": "CY-261101-0001"})
		self.assertEqual(out["bySet"], {"set_id": "(01)0893(21)DB01-007"})

	def test_station_kit_is_loaded_in_a_private_scope(self):
		# script của Page station kết thúc bằng gán vào frappe.pages["station"]; nạp riêng không được để lại dấu vết toàn cục
		out = run(
			self,
			"""const source = 'class TraceCoreStation { hello() { return "hi"; } }\\n' +
				'frappe.pages["station"].on_page_load = function () {};';
			globalThis.frappe = { pages: {} };
			const kit = TcFlow.kit(source);
			const cleaned = "station" in frappe.pages;
			const real = { on_page_load: 1 };
			frappe.pages.station = real;
			TcFlow.kit(source);
			emit({
				works: new kit.TraceCoreStation().hello(),
				leaked: typeof TraceCoreStation,
				cleaned,
				kept: frappe.pages.station === real && real.on_page_load === 1,
			});""",
		)
		self.assertEqual(out["works"], "hi")
		self.assertEqual(out["leaked"], "undefined")
		self.assertFalse(out["cleaned"])
		self.assertTrue(out["kept"])

	def test_host_class_never_sends_the_address_back_to_the_old_page(self):
		out = run(
			self,
			"""const log = [];
			globalThis.frappe = {};
			globalThis.TcStationUrl = { remember: (s, no, name) => log.push(["remember", no, name]), storage: () => null };
			class Base {
				constructor(wrapper, barrier) {
					this.wrapper = wrapper; this.barrier = barrier;
					this.root = element(); this.root.querySelector = () => element();
					this.session = { token: "t" };
				}
				adoptStationAddress() { log.push(["OLD-ADDRESS"]); }
				applyStation(station) { this.stationInfo = station; }
				openStation() { log.push(["OLD-OPEN"]); }
				storeNotice(notice) { log.push(["notice", notice.code]); }
				dispose() { log.push(["dispose"]); return Promise.resolve(); }
				show() { log.push(["show"]); }
				renderStationPills(list) { log.push(["pills", list.length]); }
				renderNetStatus(queued) { log.push(["net", queued]); }
				activateSession(session) { this.session = session; }
				clearSession() { this.session = null; }
				focus() { log.push(["focus"]); }
			}
			let covered = false;
			const shell = {
				address: (name) => log.push(["address", name]),
				applied: (host, station) => log.push(["applied", station.name]),
				replaced: (host) => log.push(["replaced", host.wrapper]),
				stations: (host, list) => log.push(["stations", list.length]),
				net: (host) => log.push(["shell-net"]),
				session: (host) => log.push(["session", Boolean(host.session)]),
				covered: () => covered,
			};
			const Host = TcFlow.hostClass(Base, shell);
			const host = new Host("W");
			host.adoptStationAddress({ name: "TR-001", station_no: 1 });
			host.applyStation({ name: "TR-001" });
			host.renderStationPills([1, 2]);
			host.renderNetStatus(3);
			host.activateSession({ token: "x" });
			host.clearSession();
			host.focus();
			covered = true;
			host.focus();
			const next = host.openStation("TR-002", "Wash", { code: "N" });
			emit({
				log,
				station: host.station,
				no: host.stationNo,
				nextIsHost: next instanceof Host && next !== host,
				current: frappe.tc_station === next,
			});""",
		)
		flat = [entry[0] for entry in out["log"]]
		self.assertNotIn("OLD-ADDRESS", flat)
		self.assertNotIn("OLD-OPEN", flat)
		self.assertIn(["address", "TR-001"], out["log"])
		self.assertIn(["remember", 1, "TR-001"], out["log"])
		self.assertIn(["applied", "TR-001"], out["log"])
		self.assertIn(["stations", 2], out["log"])
		self.assertIn(["session", True], out["log"])
		self.assertIn(["session", False], out["log"])
		self.assertEqual(
			flat.count("focus"), 1
		)  # khung đang phủ màn trạm thì ô quét của trạm không giành focus
		self.assertIn(["notice", "N"], out["log"])
		self.assertIn(["address", "TR-002"], out["log"])
		self.assertIn(["replaced", "W"], out["log"])
		self.assertLess(flat.index("dispose"), flat.index("show"))
		self.assertEqual(out["station"], "TR-001")
		self.assertEqual(out["no"], 1)
		self.assertTrue(out["nextIsHost"])


class TestTcFlowStationKit(FrappeTestCase):
	def test_real_station_script_loads_in_a_private_scope(self):
		"""Ghép script như Frappe ghép cho Page station (station.js + page_js) rồi nạp qua TcFlow.kit."""
		node = js_harness.node_or_skip(self)
		paths = [frappe.get_app_path("tracecore", "ui", "page", "station", "station.js")]
		paths += [
			frappe.get_app_path("tracecore", *rel.split("/"))
			for rel in frappe.get_hooks("page_js")["station"]
		]
		body = (
			"const kit = TcFlow.kit(source);\n"
			"const Base = kit.TraceCoreStation;\n"
			"const Host = TcFlow.hostClass(Base, {});\n"
			f"const missing = {json.dumps(HOST_METHODS)}.filter((name) => typeof Base.prototype[name] !== 'function');\n"
			"emit({ kind: typeof Base, missing, leaked: typeof TraceCoreStation, sub: Host.prototype instanceof Base });"
		)
		program = (
			js_harness._PRELUDE
			+ f"load({json.dumps(frappe.get_app_path('tracecore', *SHELL.split('/')))}, ['TcFlow']);\n"
			+ f"sandbox.source = {json.dumps(paths)}.map((p) => fs.readFileSync(p, 'utf8')).join('\\n\\n');\n"
			+ "sandbox.emit = (v) => process.stdout.write(JSON.stringify(v));\n"
			+ f"vm.runInContext({json.dumps(body)}, sandbox);\n"
		)
		done = subprocess.run([node, "-e", program], capture_output=True, text=True, check=False)
		self.assertEqual(done.returncode, 0, done.stderr[-2000:])
		out = json.loads(done.stdout)
		self.assertEqual(out["kind"], "function")
		self.assertEqual(out["missing"], [])
		self.assertEqual(
			out["leaked"], "undefined"
		)  # không để lại lớp toàn cục: mở Page station sau đó không lỗi khai báo trùng
		self.assertTrue(out["sub"])


class TestTcFlowPage(FrappeTestCase):
	def test_page_is_registered_with_station_roles(self):
		page = json.loads((PAGE_DIR / "tc_flow.json").read_text(encoding="utf-8"))
		station = json.loads(
			Path(frappe.get_app_path("tracecore", "ui", "page", "station", "station.json")).read_text(
				encoding="utf-8"
			)
		)
		self.assertEqual(page["name"], "tc-flow")
		self.assertEqual(page["module"], "UI")
		self.assertEqual(page["standard"], "Yes")
		self.assertEqual(
			sorted(row["role"] for row in page["roles"]), sorted(row["role"] for row in station["roles"])
		)
		self.assertTrue(frappe.db.exists("Page", "tc-flow"))

	def test_shell_is_attached_to_the_new_page_only(self):
		page_js = frappe.get_hooks("page_js")
		self.assertIn(SHELL, page_js["tc-flow"])
		self.assertNotIn(SHELL, page_js["station"])

	def test_page_reuses_station_code_without_copying_it(self):
		source = (PAGE_DIR / "tc_flow.js").read_text(encoding="utf-8")
		shell = Path(frappe.get_app_path("tracecore", *SHELL.split("/"))).read_text(encoding="utf-8")
		self.assertIn('with_page("station"', source)
		self.assertIn("TcFlow.hostClass(", source)
		self.assertIn("tracecore.codes.client_ts()", source)
		self.assertIn('"tracecore.v1.usage.overview"', source)
		self.assertIn('"tracecore.v1.trace.query"', source)
		self.assertIn('"tracecore.v1.navigation.context"', source)
		# không tự gọi RPC ghi của trạm, không đổi trạng thái bộ: mọi thao tác ghi đi qua màn trạm hiện có
		for text in (source, shell):
			self.assertNotIn("/app/station", text)
			self.assertNotRegex(
				text, r"tracecore\.v1\.(receive|wash|assembly|pack|load|release|putaway|issue)\."
			)
			self.assertNotIn("set_value", text)
		# token phiên trạm không được ghi vào bộ nhớ lâu dài
		self.assertNotIn("localStorage", source)

	def test_page_markup_follows_station_ui_rules(self):
		html = (PAGE_DIR / "tc_flow.html").read_text(encoding="utf-8")
		css = (PAGE_DIR / "tc_flow.css").read_text(encoding="utf-8")
		source = (PAGE_DIR / "tc_flow.js").read_text(encoding="utf-8")
		for cls in ("tcf-landing", "tcf-roles", "tcf-rail", "tcf-nav", "tcf-host", "tcf-stock", "tcf-trace"):
			self.assertIn(cls, html)
		# lỗi chặn: alert inline theo kết quả → lý do → hành động; không modal, không toast
		self.assertLess(source.index("tcf-alert-title"), source.index("tcf-alert-reason"))
		self.assertLess(source.index("tcf-alert-reason"), source.index("tcf-alert-action"))
		self.assertNotIn("frappe.msgprint", source)
		self.assertNotIn("frappe.show_alert", source)
		self.assertNotIn("frappe.throw", source)
		# chỉ token --tc-*, không hex/px, không gradient, không hover-only
		rules = "\n".join(line for line in css.splitlines() if not line.startswith("@media"))
		self.assertIsNone(re.search(r"#[0-9a-fA-F]{3,8}\b|(?<![\w-])\d+(?:\.\d+)?px\b", rules))
		self.assertNotIn("gradient", css)
		self.assertNotIn(":hover", css)
		self.assertIn("prefers-reduced-motion", css)
		self.assertIn("var(--tc-touch-min)", css)
		# trạng thái bước không chỉ bằng màu
		self.assertIn("tcf-step-mark", source)
		self.assertIn("aria-current", source)
