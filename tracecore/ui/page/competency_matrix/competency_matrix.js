/* global tracecore */
// Desk Page competency-matrix — SCR-20 Ma trận năng lực: nhân viên × trạm trên một màn (FEAT-037, FR-M4-03, UC-20).
// Ô: Còn hiệu lực / Tạm thời (≤ 24 giờ) / Tạm dừng (thiếu chứng chỉ bắt buộc) / Chưa có. R02 và R10 bấm ô để gán hoặc
// thu hồi; R01 chỉ xem. Mọi quy tắc ở server (tracecore.v1.competency.*): trang chỉ gửi giá trị và trình bày. Lỗi chặn là
// khối đỏ inline trong hộp thoại (kết quả → lý do → hành động). Trạng thái luôn có chữ, không chỉ màu.

const TC_CM = "tracecore.v1.competency.";
const TC_CM_CTX = "Competency Matrix"; // ngữ cảnh dịch cho các từ chung để không đè bản dịch của Frappe
const TC_CM_CERT_TYPES = [
	"Practice License",
	"Infection Control",
	"Sterilization",
	"Pressure Equipment Operation",
	"Other",
];
const TC_CM_STATE = {
	valid: ["✓", "Valid"],
	temporary: ["◷", "Temporary"],
	suspended: ["!", "Suspended"],
	none: ["–", "None"],
};
const TC_CM_TEMP_HOURS = 8;

function tc_cm_escape(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_cm_error_html(error) {
	const lines = [
		`<b>✕ ${tc_cm_escape(error.title)}</b>`,
		tc_cm_escape(error.reason),
		tc_cm_escape(error.action),
	];
	return `<div class="alert alert-danger" role="alert">${lines
		.filter(Boolean)
		.join("<br>")}</div>`;
}

function tc_cm_cert_label(type) {
	return __(type, null, "Certificate");
}

frappe.pages["competency-matrix"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Competency Matrix"),
		single_column: true,
	});
	const root = $("<section class='tc-cm' data-surface='WEB'></section>").appendTo(page.main);
	const state = { data: null, request: 0 };
	const visible = () => frappe.get_route()[0] === "competency-matrix";
	const zoneField = page.add_field({
		fieldname: "zone",
		fieldtype: "Select",
		label: __("Work Zone"),
		options: "",
		change: () => load(),
	});

	function message(title, reason, error) {
		root.empty();
		const box = $("<div></div>")
			.addClass(error ? "tc-cm-error" : "tc-cm-message")
			.attr("role", error ? "alert" : "status")
			.appendTo(root);
		$("<p></p>").css("font-weight", "bold").text(title).appendTo(box);
		if (reason) $("<p></p>").text(reason).appendTo(box);
		if (error)
			$("<button type='button' class='btn btn-primary'></button>")
				.text(__("Try again"))
				.on("click", load)
				.appendTo(box);
	}

	function legend() {
		const bar = $("<div class='tc-cm-legend'></div>").appendTo(root);
		Object.entries(TC_CM_STATE).forEach(([key, [symbol, label]]) =>
			$("<span></span>")
				.text(`${symbol} ${__(label, null, TC_CM_CTX)}`)
				.attr(
					"title",
					key === "suspended" ? __("A required certificate is missing or expired.") : ""
				)
				.appendTo(bar)
		);
	}

	function cellButton(employee, station, cell) {
		const [symbol, label] = TC_CM_STATE[cell.state];
		const text = `${symbol} ${__(label, null, TC_CM_CTX)}`;
		const tag = state.data.can_edit ? "button" : "span";
		const node = $(`<${tag} class='tc-cm-cell'></${tag}>`)
			.attr("data-state", cell.state)
			.text(cell.state === "none" ? symbol : text)
			.attr("aria-label", `${employee.employee_name} ${station.name}: ${text}`);
		if (tag === "button")
			node.attr("type", "button").on("click", () => openCell(employee, station, cell));
		return node;
	}

	function render() {
		const data = state.data;
		root.empty();
		legend();
		if (!data.employees.length || !data.stations.length) {
			message(
				__("No employees or stations to show"),
				__("Add employees with a user account and active stations first.")
			);
			return;
		}
		const wrapperDiv = $("<div class='tc-cm-scroll'></div>").appendTo(root);
		const table = $("<table class='tc-cm-table'></table>").appendTo(wrapperDiv);
		const head = $("<tr></tr>").appendTo($("<thead></thead>").appendTo(table));
		$("<th class='tc-cm-person'></th>").text(__("Employee")).appendTo(head);
		data.stations.forEach((station) =>
			$("<th></th>")
				.append($("<span></span>").text(`${station.step || ""} ${station.label}`.trim()))
				.append($("<span class='tc-cm-zone'></span>").text(station.zone_label || ""))
				.appendTo(head)
		);
		const body = $("<tbody></tbody>").appendTo(table);
		data.employees.forEach((employee) => {
			const row = $("<tr></tr>").appendTo(body);
			$("<td class='tc-cm-person'></td>").text(employee.employee_name).appendTo(row);
			data.stations.forEach((station) =>
				$("<td></td>")
					.append(cellButton(employee, station, employee.cells[station.name]))
					.appendTo(row)
			);
		});
	}

	function submit(dialog, method, args, label) {
		const button = dialog.get_primary_btn();
		button.prop("disabled", true);
		tracecore.desk_call({
			method: TC_CM + method,
			args,
			on_ok: () => {
				dialog.hide();
				frappe.show_alert({ message: label, indicator: "green" });
				load();
			},
			on_block: (error) => {
				button.prop("disabled", false);
				dialog.fields_dict.error_html.$wrapper.html(tc_cm_error_html(error));
			},
			on_fail: () => button.prop("disabled", false),
		});
	}

	function openCell(employee, station, cell) {
		if (cell.state === "none") grantDialog(employee, station);
		else revokeDialog(employee, station, cell);
	}

	function grantDialog(employee, station) {
		const dialog = new frappe.ui.Dialog({
			title: __("Grant competency: {0} at {1}", [employee.employee_name, station.label]),
			fields: [
				{ fieldname: "error_html", fieldtype: "HTML" },
				{
					fieldname: "is_temporary",
					fieldtype: "Check",
					label: __("Temporary access (staff shortage, at most 24 hours)"),
					change() {
						const temporary = dialog.get_value("is_temporary");
						dialog.set_value(
							"valid_until",
							temporary
								? moment()
										.add(TC_CM_TEMP_HOURS, "hours")
										.format("YYYY-MM-DD HH:mm:ss")
								: moment().add(1, "years").format("YYYY-MM-DD HH:mm:ss")
						);
					},
				},
				{
					fieldname: "valid_until",
					fieldtype: "Datetime",
					label: __("Valid Until"),
					reqd: 1,
					default: moment().add(1, "years").format("YYYY-MM-DD HH:mm:ss"),
				},
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Temporary Reason"),
					depends_on: "is_temporary",
					mandatory_depends_on: "is_temporary",
				},
				{
					fieldname: "required",
					fieldtype: "MultiCheck",
					label: __("Required Certificates"),
					description: __(
						"Tick the certificates this employee must hold to sign in at this station."
					),
					options: TC_CM_CERT_TYPES.map((type) => ({
						label: tc_cm_cert_label(type),
						value: type,
						checked: 0,
					})),
					columns: 1,
				},
			],
			primary_action_label: __("Grant"),
			primary_action(values) {
				submit(
					dialog,
					"grant",
					{
						employee: employee.employee,
						station: station.name,
						valid_until: values.valid_until,
						is_temporary: values.is_temporary ? 1 : 0,
						reason: values.reason,
						required_certificates: JSON.stringify(dialog.get_value("required") || []),
					},
					__("Competency granted.")
				);
			},
		});
		dialog.show();
	}

	function revokeDialog(employee, station, cell) {
		const [, label] = TC_CM_STATE[cell.state];
		const required = (cell.required || []).map(tc_cm_cert_label);
		const missing = (cell.missing || []).map(tc_cm_cert_label);
		const lines = [
			`<p><b>${tc_cm_escape(__(label, null, TC_CM_CTX))}</b> · ${tc_cm_escape(
				__("Valid until {0}", [frappe.datetime.str_to_user(cell.valid_until)])
			)}</p>`,
			`<p>${tc_cm_escape(__("Required certificates"))}: ${tc_cm_escape(
				required.length ? required.join(", ") : __("None")
			)}</p>`,
		];
		if (missing.length)
			lines.push(
				`<p><b>${tc_cm_escape(__("Missing or expired"))}: ${tc_cm_escape(
					missing.join(", ")
				)}</b></p>`
			);
		const dialog = new frappe.ui.Dialog({
			title: __("{0} at {1}", [employee.employee_name, station.label]),
			fields: [
				{ fieldname: "error_html", fieldtype: "HTML" },
				{ fieldname: "info_html", fieldtype: "HTML", options: lines.join("") },
				{
					fieldname: "reason",
					fieldtype: "Small Text",
					label: __("Revoke Reason"),
					reqd: 1,
				},
			],
			primary_action_label: __("Revoke competency"),
			primary_action(values) {
				submit(
					dialog,
					"revoke",
					{ name: cell.competency, reason: values.reason },
					__("Competency revoked.")
				);
			},
		});
		dialog.show();
	}

	function fillZones(stations) {
		const zones = [
			...new Map(stations.map((s) => [s.zone, s.zone_label || s.zone])).entries(),
		].filter(([zone]) => zone);
		zoneField.df.options = [{ value: "", label: "" }].concat(
			zones.map(([value, label]) => ({ value, label }))
		);
		zoneField.refresh();
	}

	async function load() {
		if (!navigator.onLine) {
			message(
				__("Offline"),
				__("Connect to the network to see the competency matrix."),
				true
			);
			return;
		}
		const current = ++state.request;
		message(__("Loading competency matrix…"), "");
		try {
			const data = await tracecore.desk_get(TC_CM + "matrix", {
				zone: zoneField.get_value() || null,
			});
			if (current !== state.request || !visible()) return;
			if (!data.ok) {
				message(data.error.title, `${data.error.reason} ${data.error.action}`, true);
				return;
			}
			state.data = data;
			if (!zoneField.get_value()) fillZones(data.stations);
			render();
		} catch (error) {
			if (current === state.request && visible())
				message(
					__("Cannot load competency matrix"),
					__("Check your connection and account permissions, then try again."),
					true
				);
		}
	}

	window.addEventListener("online", () => visible() && load());
	window.addEventListener("offline", () => visible() && load());
	wrapper.tc_cm_load = load;
};

frappe.pages["competency-matrix"].on_page_show = function (wrapper) {
	wrapper.tc_cm_load();
};
