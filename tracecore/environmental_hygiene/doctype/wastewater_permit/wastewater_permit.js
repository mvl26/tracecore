// Wastewater Permit (FEAT-095; FR-M15-08, .1, .2): bản Nháp nạp danh mục thông số mẫu theo quy chuẩn và cột (mẫu Nháp
// chờ chuyên gia duyệt — sửa theo GPMT thật trước khi ghi sổ); bản đã duyệt tạo phiên bản mới.
frappe.ui.form.on("Wastewater Permit", {
	refresh(frm) {
		if (frm.doc.docstatus === 0) {
			frm.add_custom_button(__("Load standard template"), () => {
				const dialog = new frappe.ui.Dialog({
					title: __("Load standard template"),
					fields: [
						{
							fieldname: "point",
							fieldtype: "Link",
							options: "Wastewater Point",
							label: __("Point"),
							reqd: 1,
						},
						{
							fieldname: "standard",
							fieldtype: "Select",
							options: "QCVN 28:2010/BTNMT\nQCVN 40:2025/BTNMT",
							label: __("Technical Standard"),
							default:
								frm.doc.standard === "QCVN 40:2025/BTNMT"
									? frm.doc.standard
									: "QCVN 28:2010/BTNMT",
							reqd: 1,
						},
						{
							fieldname: "column",
							fieldtype: "Select",
							options: "A\nB",
							label: __("Column"),
							default: frm.doc.standard_column === "A" ? "A" : "B",
							reqd: 1,
						},
						{
							fieldname: "frequency",
							fieldtype: "Select",
							options: "3\n6\n12",
							label: __("Frequency (months)"),
							default: "3",
						},
						{
							fieldname: "note",
							fieldtype: "HTML",
							options: `<p class="text-muted">${__(
								"Template values are a draft awaiting the hospital expert's review; edit them to match the actual permit before posting."
							)}</p>`,
						},
					],
					primary_action_label: __("Load"),
					primary_action(values) {
						frappe.call({
							method: "tracecore.v1.wastewater.template",
							type: "GET",
							args: values,
							callback: (r) => {
								(r.message || []).forEach((row) =>
									frm.add_child("parameters", row)
								);
								frm.refresh_field("parameters");
								dialog.hide();
							},
						});
					},
				});
				dialog.show();
			});
		}
		if (frm.doc.docstatus === 1 && !frm.doc.superseded_by) {
			frm.add_custom_button(__("New version"), () => {
				const now = new Date();
				const pad = (n) => String(Math.floor(Math.abs(n))).padStart(2, "0");
				const offset = -now.getTimezoneOffset();
				const client_ts =
					`${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
					`T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}` +
					`${offset >= 0 ? "+" : "-"}${pad(offset / 60)}:${pad(offset % 60)}`;
				frappe.call({
					method: "tracecore.v1.wastewater.new_permit_version",
					args: { permit: frm.doc.name, client_ts },
					headers: { "X-Idempotency-Key": crypto.randomUUID() },
					callback: (r) =>
						r.message && frappe.set_route("Form", "Wastewater Permit", r.message.name),
				});
			});
		}
	},
});
