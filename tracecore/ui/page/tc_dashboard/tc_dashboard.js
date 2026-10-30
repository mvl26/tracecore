/* global tracecore */
// Desk Page tc-dashboard — SCR-32 Dashboard vận hành (FEAT-006, FR-M9-01, FR-M9-01.1, FR-M9-01.2, UC-32; A-54).
// Khối theo vai trò do server chọn (tracecore.v1.dashboard.summary); trang chỉ trình bày. Làm mới 60 s khi trang đang
// hiện và khi có tc_notification (D9). Không dữ liệu → 0 / "Không có dữ liệu", không ẩn khối (D10).
// Trạng thái luôn có chữ, không chỉ màu. Có đủ 4 trạng thái: đang tải, trống, lỗi, mất mạng.

const TC_DASH = "tracecore.v1.dashboard.summary";
const TC_DASH_REFRESH_MS = 60000;
// ngữ cảnh dịch cho từ chung (Ngày, Tuần, Máy…) để không đè bản dịch của Frappe ở chỗ khác
const DASH_CTX = "Operations Dashboard";
const DASH_FILTER_KEY = "tc_dashboard_filters";

frappe.pages["tc-dashboard"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Operations Dashboard"),
		single_column: true,
	});
	const root = $("<section class='tc-dash-page' data-surface='WEB'></section>").appendTo(page.main);
	const state = { data: null, request: 0, timer: null, filters: savedFilters() };
	const visible = () => frappe.get_route()[0] === "tc-dashboard" && !document.hidden;

	function savedFilters() {
		const fallback = { period: "day", zone: "", equipment: "", department: "" };
		try {
			return Object.assign(fallback, JSON.parse(localStorage.getItem(DASH_FILTER_KEY) || "{}"));
		} catch (error) {
			return fallback;
		}
	}

	function saveFilters() {
		try {
			localStorage.setItem(DASH_FILTER_KEY, JSON.stringify(state.filters));
		} catch (error) {
			/* chỉ là tiện ích: không lưu được thì thôi */
		}
	}

	const fields = {
		period: page.add_field({
			fieldname: "period",
			fieldtype: "Select",
			label: __("Period", null, DASH_CTX),
			options: [
				{ value: "day", label: __("Today", null, DASH_CTX) },
				{ value: "week", label: __("This week", null, DASH_CTX) },
				{ value: "month", label: __("This month", null, DASH_CTX) },
			],
			default: state.filters.period,
			change: () => setFilter("period"),
		}),
		zone: page.add_field({
			fieldname: "zone",
			fieldtype: "Select",
			label: __("Zone", null, DASH_CTX),
			options: [{ value: "", label: __("All zones", null, DASH_CTX) }],
			change: () => setFilter("zone"),
		}),
		equipment: page.add_field({
			fieldname: "equipment",
			fieldtype: "Select",
			label: __("Machine", null, DASH_CTX),
			options: [{ value: "", label: __("All machines", null, DASH_CTX) }],
			change: () => setFilter("equipment"),
		}),
		department: page.add_field({
			fieldname: "department",
			fieldtype: "Link",
			options: "Department",
			label: __("Department", null, DASH_CTX),
			default: state.filters.department,
			change: () => setFilter("department"),
		}),
	};
	page.set_secondary_action(__("Refresh"), () => load(true), "refresh");

	function setFilter(name) {
		const value = fields[name].get_value() || "";
		if (state.filters[name] === value) return;
		state.filters[name] = value;
		saveFilters();
		load(true);
	}

	function setOptions(field, empty, rows, current) {
		const options = [empty].concat(rows);
		field.df.options = options;
		field.set_options && field.set_options();
		const known = rows.some((row) => row.value === current);
		field.set_value(known ? current : "");
	}

	function message(text, reason, kind) {
		root.empty();
		const box = $("<div></div>")
			.addClass(kind === "error" ? "tc-dash-error" : "tc-dash-empty")
			.attr("role", kind === "error" ? "alert" : "status")
			.appendTo(root);
		$("<p class='tc-dash-strong'></p>").text(text).appendTo(box);
		if (reason) $("<p></p>").text(reason).appendTo(box);
		if (kind === "error")
			$("<button type='button' class='btn btn-primary'></button>")
				.text(__("Try again"))
				.on("click", () => load(true))
				.appendTo(box);
	}

	function loading() {
		root.empty();
		$("<p class='tc-dash-empty' role='status'></p>").text(__("Loading dashboard…")).appendTo(root);
		const grid = $("<div class='tc-dash-kpis'></div>").appendTo(root);
		for (let i = 0; i < 4; i++) $("<div class='tc-dash-kpi is-loading'><span class='tc-dash-skeleton'></span></div>").appendTo(grid);
	}

	function route(doctype, filters) {
		frappe.route_options = filters || {};
		frappe.set_route("List", doctype);
	}

	function kpi(parent, value, label, variant, onOpen) {
		const tile = $("<div class='tc-dash-kpi'></div>").addClass(variant ? "is-" + variant : "").appendTo(parent);
		$("<b></b>").text(value).appendTo(tile);
		$("<small></small>").text(label).appendTo(tile);
		if (onOpen) {
			tile.attr({ role: "button", tabindex: 0 }).addClass("is-link");
			tile.on("click", onOpen).on("keydown", (event) => {
				if (event.key === "Enter" || event.key === " ") {
					event.preventDefault();
					onOpen();
				}
			});
		}
		return tile;
	}

	function section(title) {
		const box = $("<section class='tc-dash-section'></section>").appendTo(root);
		$("<h3></h3>").text(title).appendTo(box);
		return box;
	}

	function table(parent, columns, rows, emptyHint) {
		const wrap = $("<div class='tc-dash-table-wrap'></div>").appendTo(parent);
		const tbl = $("<table class='tc-dash-table'></table>").appendTo(wrap);
		const head = $("<tr></tr>").appendTo($("<thead></thead>").appendTo(tbl));
		columns.forEach((col) => $("<th></th>").toggleClass("is-num", !!col.num).text(col.label).appendTo(head));
		const body = $("<tbody></tbody>").appendTo(tbl);
		if (!rows.length) {
			$("<td></td>")
				.attr("colspan", columns.length)
				.text(__("No data — {0}", [emptyHint], DASH_CTX))
				.appendTo($("<tr></tr>").appendTo(body));
			return;
		}
		rows.forEach((row) => {
			const tr = $("<tr></tr>").appendTo(body);
			columns.forEach((col) => {
				const td = $("<td></td>").toggleClass("is-num", !!col.num).toggleClass("is-code", !!col.code).appendTo(tr);
				const value = col.value(row);
				if (value instanceof jQuery) td.append(value);
				else td.text(value === null || value === undefined ? "" : value);
			});
		});
	}

	function openButton(label, doctype, name) {
		return $("<button type='button' class='btn btn-default btn-xs'></button>")
			.text(label)
			.on("click", () => frappe.set_route("Form", doctype, name));
	}

	// danh sách "Cần xử lý" (D7): số đếm + 5 dòng đầu + "Xem tất cả"
	function actionCard(parent, title, count, doctype, filters, columns, rows, emptyHint) {
		const card = $("<article class='tc-dash-card'></article>")
			.toggleClass("is-alert", count > 0)
			.appendTo(parent);
		const head = $("<div class='tc-dash-card-head'></div>").appendTo(card);
		$("<h4></h4>").text(title).appendTo(head);
		$("<span class='tc-dash-badge'></span>")
			.toggleClass("is-alert", count > 0)
			.text(count > 0 ? __("{0} to handle", [count], DASH_CTX) : __("None", null, DASH_CTX))
			.appendTo(head);
		table(card, columns, rows, emptyHint);
		if (doctype)
			$("<button type='button' class='btn btn-default btn-sm'></button>")
				.text(__("View all", null, DASH_CTX))
				.on("click", () => route(doctype, filters))
				.appendTo(card);
	}

	function date(value) {
		return value ? frappe.datetime.str_to_user(value) : "";
	}

	function renderSets(sets) {
		const box = section(__("Sets by status", null, DASH_CTX));
		const grid = $("<div class='tc-dash-kpis'></div>").appendTo(box);
		sets.forEach((row) =>
			kpi(grid, row.count, __(row.status, null, "Set Unit"), row.status === "Reprocess" && row.count ? "warn" : "", () =>
				route("Set Unit", Object.assign({ status: row.status }, state.filters.department ? { department: state.filters.department } : {}))
			)
		);
	}

	function renderFailures(failures) {
		const box = section(__("Failed batches", null, DASH_CTX));
		const grid = $("<div class='tc-dash-kpis'></div>").appendTo(box);
		[
			[failures.load, __("Sterilization loads failed", null, DASH_CTX), "Sterilization Load"],
			[failures.wash, __("Wash batches failed", null, DASH_CTX), "Wash Batch"],
		].forEach(([rate, label, doctype]) =>
			kpi(
				grid,
				format_number(rate.percent, null, 1) + " %",
				label + " · " + __("{0} of {1}", [rate.failed, rate.finished], DASH_CTX),
				rate.failed ? "alert" : "ok",
				() => route(doctype, { status: "Failed" })
			)
		);
	}

	function renderSterile(sterile) {
		const box = section(__("Sterile store", null, DASH_CTX));
		const grid = $("<div class='tc-dash-kpis'></div>").appendTo(box);
		kpi(grid, sterile.total, __("Packs in sterile store", null, DASH_CTX), "", () => route("Pack", { status: "In Sterile Stock" }));
		kpi(
			grid,
			sterile.expiring.length,
			__("Packs expiring within 7 days", null, DASH_CTX),
			sterile.expiring.length ? "warn" : "ok"
		);
		table(
			box,
			[
				{ label: __("Set type", null, DASH_CTX), value: (r) => r.set_name || r.set_type },
				{ label: __("Packs", null, DASH_CTX), num: true, value: (r) => r.count },
				{ label: __("Nearest expiry", null, DASH_CTX), value: (r) => date(r.nearest_expiry) },
			],
			sterile.by_set_type,
			__("no packs in the sterile store", null, DASH_CTX)
		);
	}

	function renderOutput(output) {
		const box = section(__("Output in period", null, DASH_CTX));
		const cols = $("<div class='tc-dash-columns'></div>").appendTo(box);
		const count = { label: __("Passed gates", null, DASH_CTX), num: true, value: (r) => r.count };
		table(
			$("<div></div>").appendTo(cols),
			[{ label: __("Station", null, DASH_CTX), value: (r) => r.station_name }, count],
			output.station,
			__("no passed gate in this period", null, DASH_CTX)
		);
		table(
			$("<div></div>").appendTo(cols),
			[{ label: __("Staff", null, DASH_CTX), value: (r) => r.full_name }, count],
			output.user,
			__("no passed gate in this period", null, DASH_CTX)
		);
		table(
			box,
			[
				{ label: __("Machine", null, DASH_CTX), value: (r) => r.equipment_name },
				{ label: __("Wash batches", null, DASH_CTX), num: true, value: (r) => r.wash },
				{ label: __("Sterilization loads", null, DASH_CTX), num: true, value: (r) => r.load },
			],
			output.equipment,
			__("no batch started in this period", null, DASH_CTX)
		);
	}

	function renderActions(blocks) {
		const names = ["overrides", "recalls", "par", "equipment", "certificates", "stock"];
		if (!names.some((name) => blocks[name])) return;
		const box = section(__("Needs action", null, DASH_CTX));
		const grid = $("<div class='tc-dash-cards'></div>").appendTo(box);
		if (blocks.overrides)
			actionCard(
				grid,
				__("Par overrides awaiting approval", null, DASH_CTX),
				blocks.overrides.count,
				"Par Override",
				{ status: "Requested" },
				[
					{ label: __("Set ID", null, DASH_CTX), code: true, value: (r) => r.set_unit },
					{ label: __("Requested at", null, DASH_CTX), value: (r) => date(r.requested_at) },
					{ label: "", value: (r) => openButton(__("Review and approve", null, DASH_CTX), "Par Override", r.name) },
				],
				blocks.overrides.rows,
				__("no request waiting", null, DASH_CTX)
			);
		if (blocks.recalls)
			actionCard(
				grid,
				__("Open recalls", null, DASH_CTX),
				blocks.recalls.count,
				"Recall Order",
				{ status: "Open" },
				[
					{ label: __("Recall", null, DASH_CTX), code: true, value: (r) => r.name },
					{ label: __("Confirmed", null, DASH_CTX), num: true, value: (r) => r.confirmed_count + "/" + r.pack_count },
					{ label: "", value: (r) => openButton(__("Follow up", null, DASH_CTX), "Recall Order", r.name) },
				],
				blocks.recalls.rows,
				__("no open recall", null, DASH_CTX)
			);
		if (blocks.par)
			actionCard(
				grid,
				__("Sets near or over their par", null, DASH_CTX),
				blocks.par.count,
				null,
				null,
				[
					{ label: __("Set ID", null, DASH_CTX), code: true, value: (r) => r.set_unit },
					{ label: __("Cycles", null, DASH_CTX), num: true, value: (r) => r.cycles_used + "/" + r.max_cycles },
					{
						label: __("State", null, DASH_CTX),
						value: (r) => (r.state === "blocked" ? __("Out of par", null, DASH_CTX) : __("Near par", null, DASH_CTX)),
					},
					{ label: "", value: (r) => openButton(__("Open"), "Set Unit", r.set_unit) },
				],
				blocks.par.rows,
				__("no set near its par", null, DASH_CTX)
			);
		if (blocks.equipment)
			actionCard(
				grid,
				__("Machines needing attention", null, DASH_CTX),
				blocks.equipment.count,
				"Equipment",
				{ status: ["!=", "Retired"] },
				[
					{ label: __("Machine", null, DASH_CTX), value: (r) => r.equipment_name || r.name },
					{ label: __("Status", null, DASH_CTX), value: (r) => __(r.status, null, "Equipment") },
					{
						label: __("Due in (days)", null, DASH_CTX),
						num: true,
						value: (r) => (r.due_in === null || r.due_in === undefined ? "" : r.due_in),
					},
					{ label: "", value: (r) => openButton(__("Open"), "Equipment", r.name) },
				],
				blocks.equipment.rows,
				__("no machine locked or due", null, DASH_CTX)
			);
		if (blocks.certificates)
			actionCard(
				grid,
				__("Certificates expiring within 60 days", null, DASH_CTX),
				blocks.certificates.count,
				"Certificate",
				{ status: ["in", ["Valid", "Expired"]] },
				[
					{ label: __("Staff", null, DASH_CTX), value: (r) => r.employee_name || r.employee },
					{ label: __("Expires on", null, DASH_CTX), value: (r) => date(r.expires_on) },
					{ label: __("Days left", null, DASH_CTX), num: true, value: (r) => r.days_left },
					{ label: "", value: (r) => openButton(__("Open"), "Certificate", r.name) },
				],
				blocks.certificates.rows,
				__("no certificate expiring", null, DASH_CTX)
			);
		if (blocks.stock) {
			actionCard(
				grid,
				__("Items below minimum stock", null, DASH_CTX),
				blocks.stock.below_minimum.length,
				"Item",
				null,
				[
					{ label: __("Item", null, DASH_CTX), value: (r) => r.item_name || r.item },
					{ label: __("Warehouse", null, DASH_CTX), value: (r) => r.warehouse },
					{ label: __("In stock / minimum", null, DASH_CTX), num: true, value: (r) => r.qty + "/" + r.minimum },
				],
				blocks.stock.below_minimum.slice(0, 5),
				__("no item below minimum", null, DASH_CTX)
			);
			actionCard(
				grid,
				__("Batches expiring within 30 days", null, DASH_CTX),
				blocks.stock.expiring.length,
				"Batch",
				null,
				[
					{ label: __("Batch", null, DASH_CTX), code: true, value: (r) => r.batch },
					{ label: __("Item", null, DASH_CTX), value: (r) => r.item },
					{ label: __("Expires on", null, DASH_CTX), value: (r) => date(r.expiry_date) },
				],
				blocks.stock.expiring.slice(0, 5),
				__("no batch expiring", null, DASH_CTX)
			);
		}
	}

	function render() {
		const data = state.data;
		const blocks = data.blocks;
		root.empty();
		$("<p class='tc-dash-updated' role='status'></p>")
			.text(__("Updated at {0}", [frappe.datetime.str_to_user(data.generated_at.slice(0, 19).replace("T", " "))], DASH_CTX))
			.appendTo(root);
		if (!Object.keys(blocks).length) {
			message(
				__("No dashboard block for your role"),
				__("Ask R10 to grant the role that matches your work.")
			);
			return;
		}
		if (blocks.sets) renderSets(blocks.sets);
		if (blocks.failures) renderFailures(blocks.failures);
		if (blocks.sterile) renderSterile(blocks.sterile);
		renderActions(blocks);
		if (blocks.output) renderOutput(blocks.output);
	}

	async function load(showLoading) {
		if (!navigator.onLine) {
			message(__("Offline"), __("Connect to the network to see the dashboard."), "error");
			return;
		}
		const current = ++state.request;
		if (showLoading && !state.data) loading();
		try {
			const data = await tracecore.desk_get(TC_DASH, {
				period: state.filters.period,
				zone: state.filters.zone || null,
				equipment: state.filters.equipment || null,
				department: state.filters.department || null,
			});
			if (current !== state.request) return;
			state.data = data;
			setOptions(fields.zone, { value: "", label: __("All zones", null, DASH_CTX) }, data.options.zones, state.filters.zone);
			setOptions(
				fields.equipment,
				{ value: "", label: __("All machines", null, DASH_CTX) },
				data.options.equipment,
				state.filters.equipment
			);
			render();
		} catch (error) {
			if (current === state.request)
				message(
					__("Cannot load the dashboard"),
					__("Check your connection and account permissions, then try again."),
					"error"
				);
		}
	}

	function schedule() {
		clearInterval(state.timer);
		state.timer = setInterval(() => {
			if (visible()) load(false);
			else clearInterval(state.timer);
		}, TC_DASH_REFRESH_MS);
	}

	frappe.realtime.on("tc_notification", () => visible() && load(false));
	window.addEventListener("online", () => visible() && load(true));
	window.addEventListener("offline", () => visible() && load(true));
	document.addEventListener("visibilitychange", () => {
		if (visible()) {
			load(false);
			schedule();
		}
	});
	wrapper.tc_dash_show = () => {
		load(true);
		schedule();
	};
};

frappe.pages["tc-dashboard"].on_page_show = function (wrapper) {
	wrapper.tc_dash_show();
};
