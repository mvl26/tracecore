// Phiếu xuất hồ sơ lưu trữ (FEAT-012, SCR-43): tải gói ZIP và kiểm checksum khi đã xong; tự tải lại khi job chạy xong.
frappe.ui.form.on("Archive Export", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status !== "Completed") {
			return;
		}
		frm.add_custom_button(__("Download Archive"), () =>
			window.open(frm.doc.archive_file, "_blank")
		);
		frm.add_custom_button(__("Verify Checksum"), () =>
			frappe
				.call({ method: "tracecore.v1.archive.verify", args: { name: frm.doc.name } })
				.then((r) => {
					const result = r.message || {};
					frappe.msgprint({
						title: __("Verify Checksum"),
						indicator: result.ok ? "green" : "red",
						message: result.ok
							? __("The archive file matches its SHA-256 checksum.")
							: __("The archive file does NOT match its SHA-256 checksum."),
					});
				})
		);
	},
	onload(frm) {
		frappe.realtime.on("tc_archive_ready", (data) => {
			if (data && data.name === frm.doc.name) {
				frm.reload_doc();
			}
		});
	},
});
