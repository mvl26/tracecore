/* global tracecore */
// Desk Page tc-import — SCR-43 import danh mục ban đầu (FEAT-011, FR-M9-11, FR-M9-11.1, UC-39; A-41).
// Chọn loại danh mục → Tải mẫu → Chọn file .xlsx → Kiểm tra (không ghi) → Ghi sổ các dòng đúng (> 200 dòng chạy nền,
// trang hỏi lại trạng thái 3 giây một lần) → kết quả từng dòng. Khối "Ảnh hàng loạt": chọn zip, tên file = mã.
// Mọi kiểm tra ở server (tracecore.v1.imports.*); trang chỉ gửi file và trình bày. Lỗi chặn là khối inline đỏ
// (kết quả → lý do → hành động), không toast/modal. Gọi RPC qua tracecore.codes.send (tc_codes.js): ghi sổ dùng một
// khóa X-Idempotency-Key cho mỗi thao tác, gửi lại sau lỗi mạng bằng đúng request cũ.

const TC_IMP = "tracecore.v1.imports.";
const TC_IMP_POLL_MS = 3000;
// CSS chỉ dùng biến --tc-* (R4)
const TC_IMP_CSS = `
.tc-imp { max-width: 1100px; }
.tc-imp-block { margin-bottom: var(--tc-sp-5); padding: var(--tc-sp-4); border: var(--tc-bw-hair) solid var(--tc-border);
	border-radius: var(--tc-r-md); background: var(--tc-surface); }
.tc-imp-block h3 { margin: 0 0 var(--tc-sp-3); }
.tc-imp-actions { display: flex; flex-wrap: wrap; gap: var(--tc-sp-3); align-items: center; margin: var(--tc-sp-3) 0; }
.tc-imp-alert { margin-top: var(--tc-sp-3); padding: var(--tc-sp-2-5) var(--tc-sp-3);
	border-left: var(--tc-bw-alert) solid var(--tc-info); border-radius: 0 var(--tc-r-sm) var(--tc-r-sm) 0;
	background: var(--tc-info-tint); color: var(--tc-text); }
.tc-imp-alert p { margin: 0 0 var(--tc-sp-1); }
.tc-imp-alert-title { font-weight: var(--tc-fw-bold); }
.tc-imp-alert-error { background: var(--tc-fail-tint); border-left-color: var(--tc-fail); }
.tc-imp-alert-error .tc-imp-alert-title { color: var(--tc-fail-text); }
.tc-imp-alert-warn { background: var(--tc-warn-tint); border-left-color: var(--tc-warn); }
.tc-imp-alert-warn .tc-imp-alert-title { color: var(--tc-warn-text); }
.tc-imp-alert-ok { background: var(--tc-pass-tint); border-left-color: var(--tc-pass); }
.tc-imp-alert-ok .tc-imp-alert-title { color: var(--tc-pass-text); }
.tc-imp-table { width: 100%; margin: var(--tc-sp-2) 0; border-collapse: collapse; }
.tc-imp-table th, .tc-imp-table td { padding: var(--tc-sp-1) var(--tc-sp-2);
	border-bottom: var(--tc-bw-hair) solid var(--tc-border-row); text-align: left; vertical-align: top; }
.tc-imp-table th { color: var(--tc-text-2); font-weight: var(--tc-fw-bold); }
.tc-imp-mono { font-family: var(--tc-font-mono); }
.tc-imp-hint { color: var(--tc-text-2); }
`;

function tc_imp_esc(text) {
	return frappe.utils.escape_html(text === undefined || text === null ? "" : String(text));
}

function tc_imp_alert(variant, mark, notice, extra = "") {
	const role = variant === "error" ? "alert" : "status";
	return `<div class="tc-imp-alert tc-imp-alert-${variant}" role="${role}">
		<p class="tc-imp-alert-title"><span aria-hidden="true">${mark}</span> ${tc_imp_esc(
		notice.title
	)}</p>
		${notice.reason ? `<p>${tc_imp_esc(notice.reason)}</p>` : ""}
		${extra}
		${notice.action ? `<p>${tc_imp_esc(notice.action)}</p>` : ""}
	</div>`;
}

function tc_imp_issue_table(rows) {
	if (!rows.length) return "";
	const body = rows
		.map(
			(row) => `<tr>
			<td class="tc-imp-mono">${tc_imp_esc(row.row || row.row_no)}</td>
			<td class="tc-imp-mono">${tc_imp_esc(row.code_value || row.code || "")}</td>
			<td>${tc_imp_esc(row.field || "")}</td>
			<td>${tc_imp_esc(row.reason || row.message)}</td>
		</tr>`
		)
		.join("");
	return `<table class="tc-imp-table">
		<thead><tr>
			<th>${tc_imp_esc(__("Excel row"))}</th>
			<th>${tc_imp_esc(__("Code"))}</th>
			<th>${tc_imp_esc(__("Excel column"))}</th>
			<th>${tc_imp_esc(__("Problem"))}</th>
		</tr></thead>
		<tbody>${body}</tbody>
	</table>`;
}

function tc_imp_download(url) {
	const link = document.createElement("a");
	link.href = url;
	link.download = "";
	document.body.appendChild(link);
	link.click();
	link.remove();
}

class TraceCoreImport {
	constructor(wrapper) {
		this.page = frappe.ui.make_app_page({
			parent: wrapper,
			title: __("Catalog Import"),
			single_column: true,
		});
		frappe.dom.set_style(TC_IMP_CSS, "tc-import-style");
		this.state = {
			kind: null,
			file_url: null,
			file_name: null,
			checked: null,
			pending: null,
			busy: false,
		};
		this.photo = { file_url: null, file_name: null, pending: null, busy: false };
		this.page.main.html(`<div class="tc-imp">
			<section class="tc-imp-block" data-block="catalog">
				<h3>${tc_imp_esc(__("Import a catalog from Excel"))}</h3>
				<div data-field="kind"></div>
				<div class="tc-imp-actions">
					<button type="button" class="btn btn-default" data-action="template">${tc_imp_esc(
						__("Download template")
					)}</button>
					<button type="button" class="btn btn-default" data-action="choose">${tc_imp_esc(
						__("Choose Excel file")
					)}</button>
					<span class="tc-imp-mono" data-region="file"></span>
				</div>
				<div class="tc-imp-actions">
					<button type="button" class="btn btn-default" data-action="check">${tc_imp_esc(
						__("Check file")
					)}</button>
					<button type="button" class="btn btn-primary" data-action="run">${tc_imp_esc(
						__("Save correct rows")
					)}</button>
				</div>
				<div data-region="result"></div>
			</section>
			<section class="tc-imp-block" data-block="photos">
				<h3>${tc_imp_esc(__("Photos in bulk"))}</h3>
				<p class="tc-imp-hint">${tc_imp_esc(
					__(
						"Zip file of JPEG, PNG or WebP photos. File name = instrument code, or set type code (-2, -3 for the 2nd and 3rd tray photo)."
					)
				)}</p>
				<div class="tc-imp-actions">
					<button type="button" class="btn btn-default" data-action="choose-zip">${tc_imp_esc(
						__("Choose zip file")
					)}</button>
					<span class="tc-imp-mono" data-region="zip"></span>
					<button type="button" class="btn btn-primary" data-action="photos">${tc_imp_esc(
						__("Attach photos")
					)}</button>
				</div>
				<div data-region="photo-result"></div>
			</section>
		</div>`);
		this.root = this.page.main.find(".tc-imp");
		this.root.on("click", "[data-action]", (event) =>
			this.on_action(event.currentTarget.dataset.action)
		);
		this.load_kinds();
	}

	region(name) {
		return this.root.find(`[data-region="${name}"]`);
	}

	async load_kinds() {
		const outcome = await tracecore.codes.send(TC_IMP + "kinds", null, {});
		if (!outcome.ok)
			return this.region("result").html(tc_imp_alert("error", "&#10005;", outcome.error));
		this.kinds = outcome.data.kinds;
		this.kind_control = frappe.ui.form.make_control({
			parent: this.root.find('[data-field="kind"]'),
			df: {
				fieldtype: "Select",
				fieldname: "kind",
				label: __("Catalog"),
				options: [{ value: "", label: "" }].concat(
					this.kinds.map((kind) => ({ value: kind.key, label: kind.label }))
				),
				change: () => this.choose_kind(this.kind_control.get_value()),
			},
			render_input: true,
		});
		this.sync();
	}

	choose_kind(kind) {
		this.state.kind = kind || null;
		this.state.checked = null;
		this.state.pending = null;
		this.region("result").html("");
		this.sync();
	}

	sync() {
		const s = this.state;
		this.region("file").text(s.file_name || __("No file chosen."));
		this.root.find('[data-action="template"]').prop("disabled", !s.kind);
		this.root.find('[data-action="choose"]').prop("disabled", !s.kind || s.busy);
		this.root.find('[data-action="check"]').prop("disabled", !s.kind || !s.file_url || s.busy);
		this.root
			.find('[data-action="run"]')
			.prop("disabled", s.busy || s.checked !== `${s.kind}|${s.file_url}`);
		this.region("zip").text(this.photo.file_name || __("No file chosen."));
		this.root
			.find('[data-action="photos"]')
			.prop("disabled", !this.photo.file_url || this.photo.busy);
	}

	on_action(action) {
		const actions = {
			template: () =>
				tc_imp_download(
					`/api/method/${TC_IMP}template?kind=${encodeURIComponent(this.state.kind)}`
				),
			choose: () =>
				this.choose(".xlsx", (file) =>
					Object.assign(this.state, file, { checked: null, pending: null })
				),
			check: () => this.check(),
			run: () => this.run(),
			"choose-zip": () =>
				this.choose(".zip", (file) => Object.assign(this.photo, file, { pending: null })),
			photos: () => this.attach_photos(),
		};
		if (actions[action]) actions[action]();
	}

	choose(extension, apply) {
		new frappe.ui.FileUploader({
			make_attachments_public: false,
			disable_file_browser: true,
			restrictions: { allowed_file_types: [extension], max_number_of_files: 1 },
			on_success: (file_doc) => {
				apply({ file_url: file_doc.file_url, file_name: file_doc.file_name });
				this.sync();
			},
		});
	}

	async check() {
		const s = this.state;
		const signature = `${s.kind}|${s.file_url}`;
		s.busy = true;
		this.sync();
		this.region("result").html(
			`<p class="tc-imp-hint">${tc_imp_esc(__("Checking the file..."))}</p>`
		);
		const outcome = await tracecore.codes.send(TC_IMP + "check", null, {
			kind: s.kind,
			file_url: s.file_url,
		});
		s.busy = false;
		if (!outcome.ok) {
			s.checked = null;
			this.region("result").html(tc_imp_alert("error", "&#10005;", outcome.error));
			return this.sync();
		}
		const data = outcome.data;
		s.checked = data.valid > 0 ? signature : null;
		let html = tc_imp_alert(
			data.issues.length ? "warn" : "ok",
			data.issues.length ? "!" : "&#10003;",
			{
				title: __("{0} row(s) checked", [data.total]),
				reason: __("{0} record(s) ready to save, {1} already exist, {2} row problem(s).", [
					data.valid,
					data.existing.length,
					data.issues.length,
				]),
				action: data.valid
					? __("Choose Save correct rows to save them; wrong rows are not saved.")
					: __("Fix the file and check it again."),
			}
		);
		if (data.previous_batch) {
			html += tc_imp_alert("warn", "!", {
				title: __("This file was already imported"),
				reason: __("Import {0} used the same file.", [data.previous_batch]),
				action: __(
					"Saving again may create duplicate records for catalogs without a code, such as set units."
				),
			});
		}
		if (data.existing.length) {
			html += `<p class="tc-imp-hint">${tc_imp_esc(
				__("Already existing (skipped): {0}", [data.existing.join(", ")])
			)}</p>`;
		}
		html += tc_imp_issue_table(data.issues);
		this.region("result").html(html);
		this.sync();
	}

	async run() {
		const s = this.state;
		const signature = `${s.kind}|${s.file_url}`;
		if (s.busy || s.checked !== signature) return;
		if (!s.pending || s.pending.signature !== signature) {
			s.pending = {
				signature,
				request: tracecore.codes.new_request({ kind: s.kind, file_url: s.file_url }),
			};
		}
		s.busy = true;
		this.sync();
		const outcome = await tracecore.codes.send(TC_IMP + "run", s.pending.request);
		s.busy = false;
		if (!outcome.ok) {
			if (!outcome.network) s.pending = null;
			this.region("result").html(tc_imp_alert("error", "&#10005;", outcome.error));
			return this.sync();
		}
		s.pending = null;
		s.checked = null;
		this.sync();
		this.follow(outcome.data.batch);
	}

	async follow(batch) {
		const outcome = await tracecore.codes.send(TC_IMP + "batch", null, { name: batch });
		if (!outcome.ok)
			return this.region("result").html(tc_imp_alert("error", "&#10005;", outcome.error));
		const data = outcome.data;
		const link = `<a class="tc-imp-mono" href="${frappe.utils.get_form_link(
			"Import Batch",
			batch
		)}">${tc_imp_esc(batch)}</a>`;
		if (data.status === "Queued" || data.status === "Running") {
			this.region("result").html(
				tc_imp_alert(
					"info",
					"i",
					{
						title: __("Import is running in the background"),
						reason: __("{0} row(s) are being saved. This page updates by itself.", [
							data.total,
						]),
					},
					`<p>${link}</p>`
				)
			);
			setTimeout(() => this.follow(batch), TC_IMP_POLL_MS);
			return;
		}
		if (data.status === "Failed") {
			this.region("result").html(
				tc_imp_alert(
					"error",
					"&#10005;",
					{
						title: __("Import stopped"),
						reason: data.error || __("The server could not finish the import."),
						action: __(
							"Nothing of this import was saved. Check the file again, or call R10."
						),
					},
					`<p>${link}</p>`
				)
			);
			return;
		}
		const errors = data.rows.filter((row) => row.result === "Error");
		this.region("result").html(
			tc_imp_alert(
				errors.length ? "warn" : "ok",
				errors.length ? "!" : "&#10003;",
				{
					title: __("Import {0} finished", [batch]),
					reason: __("{0} created, {1} already existing, {2} with errors.", [
						data.created,
						data.skipped,
						data.failed,
					]),
					action: errors.length
						? __("Fix the rows listed below and import the file again.")
						: "",
				},
				`<p>${link}</p>`
			) + tc_imp_issue_table(errors)
		);
	}

	async attach_photos() {
		const p = this.photo;
		if (p.busy || !p.file_url) return;
		if (!p.pending) p.pending = tracecore.codes.new_request({ file_url: p.file_url });
		p.busy = true;
		this.sync();
		this.region("photo-result").html(
			`<p class="tc-imp-hint">${tc_imp_esc(__("Attaching photos..."))}</p>`
		);
		const outcome = await tracecore.codes.send(TC_IMP + "photos", p.pending);
		p.busy = false;
		if (!outcome.ok) {
			if (!outcome.network) p.pending = null;
			this.region("photo-result").html(tc_imp_alert("error", "&#10005;", outcome.error));
			return this.sync();
		}
		p.pending = null;
		const data = outcome.data;
		const problems = data.rejected.map((row) => ({ code: row.file, reason: row.reason }));
		const unmatched = data.unmatched.map((file) => ({
			code: file,
			reason: __("No instrument or set type has this code."),
		}));
		this.region("photo-result").html(
			tc_imp_alert(
				problems.length || unmatched.length ? "warn" : "ok",
				problems.length || unmatched.length ? "!" : "&#10003;",
				{
					title: __("{0} photo(s) attached", [data.attached.length]),
					reason: __("{0} file(s) did not match a code, {1} were not accepted.", [
						unmatched.length,
						problems.length,
					]),
				}
			) + tc_imp_issue_table(unmatched.concat(problems))
		);
		this.sync();
	}
}

frappe.pages["tc-import"].on_page_load = function (wrapper) {
	frappe.tc_import = new TraceCoreImport(wrapper);
};
