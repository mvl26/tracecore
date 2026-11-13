/* global TcStationUrl */
// Page tc-flow (A-158): phần thuần của khung giao diện người dùng cho luồng xử lý dụng cụ.
// Khung chỉ điều hướng và hiển thị; mọi thao tác của trạm chạy bằng mã của Page station (lớp TraceCoreStation và các màn
// T1–T8), nạp trong phạm vi riêng nên không khai báo lại biến toàn cục của Page station. Test: tracecore/tests/js_harness.py.

// chức năng trạm thuộc luồng xử lý dụng cụ (kỹ thuật viên) và chức năng của khoa sử dụng
const TC_FLOW_KTV_FUNCTIONS = [
	"RECEIVE",
	"MANUAL_WASH",
	"WASH_LOAD",
	"WASH_UNLOAD",
	"ASSEMBLE",
	"PACK",
	"STERI_LOAD",
	"STERI_UNLOAD",
	"PUTAWAY",
	"ISSUE",
];
const TC_FLOW_DEPT_FUNCTION = "USE";

const TcFlow = {
	// cổng khoa mang thêm ?department=<khoa>; trạm (nếu đang mở) ở ?station=<mã>
	path(station, department) {
		const query = [];
		if (department) query.push(`department=${encodeURIComponent(department)}`);
		if (station) query.push(`station=${encodeURIComponent(station)}`);
		return query.length ? `/app/tc-flow?${query.join("&")}` : "/app/tc-flow";
	},

	stationParam(search) {
		return new URLSearchParams(search || "").get("station") || null;
	},

	departmentParam(search) {
		return new URLSearchParams(search || "").get("department") || null;
	},

	mode(station) {
		const functions = (station && station.functions) || [];
		return functions.includes(TC_FLOW_DEPT_FUNCTION) ? "dept" : "ktv";
	},

	sorted(stations) {
		const number = (station) => parseInt(station.station_no, 10) || 0;
		return stations.slice().sort((a, b) => {
			if (!number(a) !== !number(b)) return number(a) ? -1 : 1;
			return number(a) - number(b) || String(a.name).localeCompare(String(b.name));
		});
	},

	ktvStations(stations) {
		return TcFlow.sorted(
			(stations || []).filter(
				(station) =>
					station.implemented !== false &&
					TcFlow.mode(station) === "ktv" &&
					(station.functions || []).some((name) => TC_FLOW_KTV_FUNCTIONS.includes(name))
			)
		);
	},

	deptStations(stations) {
		return TcFlow.sorted(
			(stations || []).filter(
				(station) => station.implemented !== false && TcFlow.mode(station) === "dept"
			)
		);
	},

	// mọi trạm của luồng dụng cụ T1–T8 theo số trạm: rail của kỹ thuật viên và stepper dùng chung
	flowStations(stations) {
		return TcFlow.sorted([...TcFlow.ktvStations(stations), ...TcFlow.deptStations(stations)]);
	},

	// "T1 Tiếp nhận": tên trạm đã có số thì không lặp số (cùng quy tắc hàng nút trạm của Page station)
	stationLabel(station) {
		const full = __(station.label || station.name || "");
		const number = parseInt(station.station_no, 10) || 0;
		return !number || full.startsWith(`T${number}`) ? full : `T${number} ${full}`;
	},

	// thứ tự bước T1–T8: mỗi số trạm một ô; state done / current / todo theo trạm đang mở
	stepper(stations, currentName) {
		const flow = TcFlow.flowStations(stations);
		const current = flow.find((station) => station.name === currentName);
		const at = current ? parseInt(current.station_no, 10) || 0 : 0;
		const steps = [];
		for (const station of flow) {
			const number = parseInt(station.station_no, 10) || 0;
			if (!number || steps.some((step) => step.no === number)) continue;
			const shown = current && number === at ? current : station;
			steps.push({
				no: number,
				label: TcFlow.stationLabel(shown),
				state: !at ? "todo" : number < at ? "done" : number === at ? "current" : "todo",
			});
		}
		return steps;
	},

	stockCounts(overview) {
		const held = (overview && overview.at_department) || [];
		const waiting = (overview && overview.waiting_return) || [];
		return {
			held: held.length,
			expiring: held.filter((row) => row.expiring).length,
			waiting: waiting.length,
		};
	},

	// mã gói CY-… tra theo Cycle ID, còn lại tra theo Set ID
	traceArgs(raw) {
		const code = String(raw || "").trim();
		return /^CY-/i.test(code) ? { cycle_id: code.toUpperCase() } : { set_id: code };
	},

	traceRows(chain) {
		return ((chain && chain.events) || []).map((event) => ({
			at: event.at || null,
			step: event.step || "",
			detail: [
				event.label,
				event.ref_name,
				event.result && __(event.result, null, "Step Gate Result"),
			]
				.filter(Boolean)
				.join(" · "),
			who: [event.equipment, event.user_name || event.user].filter(Boolean).join(" / "),
		}));
	},

	// Lớp TraceCoreStation khi Page station đã nạp trong phiên Desk này (script Page chạy ở phạm vi toàn cục)
	globalStation() {
		// eslint-disable-next-line no-undef
		return typeof TraceCoreStation !== "undefined" ? TraceCoreStation : null;
	},

	// Chạy script của Page station trong phạm vi riêng để lấy lớp TraceCoreStation. Script kết thúc bằng gán
	// frappe.pages["station"].on_page_*: cho nó một đối tượng tạm rồi trả frappe.pages về như cũ, để lần mở Page station
	// sau đó vẫn nạp như thường và không gặp lỗi khai báo trùng.
	kit(source) {
		const pages = frappe.pages;
		const had = Object.prototype.hasOwnProperty.call(pages, "station");
		const before = pages.station;
		pages.station = {};
		try {
			// eslint-disable-next-line no-new-func
			return new Function(`${source}\n;return { TraceCoreStation };`)();
		} finally {
			if (had) pages.station = before;
			else delete pages.station;
		}
	},

	// Lớp con của TraceCoreStation cho khung tc-flow: giữ địa chỉ ở /app/tc-flow và báo trạng thái cho khung.
	// shell: { address(name), applied(host, station), replaced(host), stations(host, list), net(host), session(host), covered() }
	hostClass(Base, shell) {
		return class TcFlowStation extends Base {
			adoptStationAddress(station) {
				this.station = station.name;
				this.stationNo = station.station_no || null;
				TcStationUrl.remember(TcStationUrl.storage(), station.station_no, station.name);
				shell.address(station.name);
			}

			applyStation(station) {
				super.applyStation(station);
				shell.applied(this, station);
			}

			// đổi trạm không tải lại trang: bỏ instance cũ, dựng instance mới trên cùng wrapper, địa chỉ vẫn ở tc-flow
			openStation(station, label, notice) {
				if (notice) this.storeNotice(notice);
				this.session = null;
				this.restoreCandidate = null;
				shell.address(station);
				const next = new this.constructor(this.wrapper, this.dispose());
				frappe.tc_station = next;
				if (label) next.root.querySelector(".tc-station-name").textContent = label;
				shell.replaced(next);
				next.show();
				return next;
			}

			renderStationPills(stations) {
				super.renderStationPills(stations);
				shell.stations(this, stations);
			}

			renderNetStatus(queued) {
				super.renderNetStatus(queued);
				shell.net(this);
			}

			activateSession(session) {
				super.activateSession(session);
				shell.session(this);
			}

			clearSession(...args) {
				super.clearSession(...args);
				shell.session(this);
			}

			// khung đang phủ màn trạm (Gói tại khoa, Tra cứu gói): ô quét của trạm không giành focus
			focus(force) {
				if (shell.covered()) return;
				super.focus(force);
			}
		};
	},
};

window.TcFlow = TcFlow;
