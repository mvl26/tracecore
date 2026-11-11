// IC Committee Meeting (FEAT-058; FR-M11-08.2; UC-41 A3): hiện kết luận chưa đóng của các lần họp trước.
frappe.ui.form.on("IC Committee Meeting", {
	refresh(frm) {
		const field = frm.get_field("open_resolutions_html");
		if (!field) return;
		frappe
			.xcall("tracecore.infection_program.meetings.open_resolutions_for", {
				meeting: frm.is_new() ? null : frm.doc.name,
			})
			.then((rows) => {
				const esc = frappe.utils.escape_html;
				const date = (value) => (value ? frappe.datetime.str_to_user(value) : "");
				field.$wrapper.html(
					rows && rows.length
						? `<ul>${rows
								.map(
									(r) =>
										`<li><code>${esc(r.meeting)}</code> ${esc(r.content)} — ` +
										`${esc(r.responsible_name || r.responsible)}, ${esc(
											date(r.due_date)
										)}</li>`
								)
								.join("")}</ul>`
						: `<p class="text-muted">${esc(
								__("No open conclusion from previous meetings.")
						  )}</p>`
				);
			});
	},
});
