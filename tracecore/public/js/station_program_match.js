// Chương trình theo máy của loại bộ ở T2, T5 (A-110, ticket 1865; FR-M2-03.7/.8, FR-M2-09.7/.8).
// Frappe nối file này trước station_t2.js và station_t5.js (hook page_js). `load` là phiên nạp của màn:
// {programs, program, set_programs, program_control, programTouched, override_reason}. Bảng `set_programs`
// (loại bộ → {default, allowed}) đến từ RPC quét máy nên màn gắn nhãn và gợi ý được cả khi offline; server kiểm lại
// khi nạp và khi Hoàn thành nạp (`core.program_match`).

window.TcProgramMatch = {
	DEFAULT: "Default",
	ALLOWED: "Allowed",
	OUTSIDE: "Outside",
	UNMAPPED: "Unmapped",

	entry(load, setType) {
		return ((load && load.set_programs) || {})[setType] || null;
	},

	fit(load, setType, program = load && load.program) {
		const entry = this.entry(load, setType);
		if (!entry) return this.UNMAPPED;
		if (program && program === entry.default) return this.DEFAULT;
		return (entry.allowed || []).includes(program) ? this.ALLOWED : this.OUTSIDE;
	},

	// Cùng quy tắc với `program_match.suggest`: chương trình chung được phép cho mọi loại bộ đã khai, ưu tiên chương
	// trình là mặc định của nhiều loại bộ nhất; `conflict` khi mặc định khác nhau hoặc không có chương trình chung.
	suggest(load, setTypes) {
		const entries = [...new Set(setTypes)]
			.map((name) => this.entry(load, name))
			.filter(Boolean);
		if (!entries.length) return { program: null, conflict: false, common: [] };
		const votes = {};
		entries.forEach((entry) => {
			if (entry.default) votes[entry.default] = (votes[entry.default] || 0) + 1;
		});
		const common = entries
			.map((entry) => entry.allowed || [])
			.reduce((left, right) => left.filter((name) => right.includes(name)))
			.slice()
			.sort((a, b) => (votes[b] || 0) - (votes[a] || 0) || (a < b ? -1 : a > b ? 1 : 0));
		const defaults = Object.keys(votes);
		return {
			program: common[0] || null,
			conflict: defaults.length > 1 || !common.length,
			common,
		};
	},

	// Bộ/gói đầu tiên của lô/mẻ: chọn chương trình mặc định của loại bộ khi người dùng chưa tự đổi (D5).
	// Trả chương trình vừa chọn, hoặc null khi không đổi.
	autoSelect(load, setType, isFirst) {
		if (!load || load.programTouched || !isFirst) return null;
		const entry = this.entry(load, setType);
		const target = entry && entry.default;
		if (!target || target === load.program) return null;
		if (!(load.programs || []).some((row) => row.program_code === target)) return null;
		load.program = target;
		return target;
	},

	programName(load, code) {
		const row = (load.programs || []).find((entry) => entry.program_code === code);
		return row ? row.program_name : code;
	},

	outsideTypes(load, setTypes) {
		return [...new Set(setTypes)].filter((name) => this.fit(load, name) === this.OUTSIDE);
	},

	needsReason(load, setTypes) {
		return (
			(load.program_control || "Warn") === "Override" &&
			this.outsideTypes(load, setTypes).length > 0 &&
			!(load.override_reason || "").trim()
		);
	},

	// Nhãn chữ (không chỉ màu, design.md §6) của một dòng bộ/gói
	badgeHtml(load, setType) {
		const fit = this.fit(load, setType);
		const [mark, text, variant] = {
			Default: ["&#10003; ", __("Default program"), " tc-badge-g"],
			Allowed: ["", __("Allowed program"), ""],
			Outside: ["! ", __("Program not listed"), " tc-badge-o"],
			Unmapped: ["", __("No program set for this machine"), ""],
		}[fit];
		return `<span class="tc-badge${variant}" data-program-fit="${fit}"><span aria-hidden="true">${mark}</span>${frappe.utils.escape_html(
			text
		)}</span>`;
	},

	// Cảnh báo một dòng khi các loại bộ cần chương trình khác nhau, kèm nút dùng chương trình chung (D6)
	conflictNotice(load, setTypes, action) {
		const result = this.suggest(load, setTypes);
		if (!result.conflict) return null;
		if (!result.program)
			return {
				notice: {
					variant: "warn",
					title: __("These sets need different programs"),
					reason: __("No program is allowed for every set type on this machine."),
					action: __("Load the sets with different programs in separate batches."),
				},
				buttons: "",
			};
		const name = this.programName(load, result.program);
		const buttons =
			result.program === load.program
				? ""
				: `<div class="tc-actions"><button type="button" class="tc-btn tc-btn-secondary" data-action="${action}"
				data-program="${frappe.utils.escape_html(result.program)}">${frappe.utils.escape_html(
						__("Use {0}", [name])
				  )}</button></div>`;
		return {
			notice: {
				variant: "warn",
				title: __("These sets have different default programs"),
				reason: __("Program {0} is allowed for every set type in the list.", [name]),
				action: __("Use this program, or load the sets in separate batches."),
			},
			buttons,
		};
	},

	// Ô lý do khi mức kiểm soát là Ghi đè có lý do và có bộ ngoài danh sách (D7)
	reasonHtml(load, setTypes, inputId) {
		if ((load.program_control || "Warn") !== "Override") return "";
		if (!this.outsideTypes(load, setTypes).length) return "";
		const esc = frappe.utils.escape_html;
		return `<div class="tc-field">
			<label for="${inputId}">${esc(
			__("Reason for using a program not listed for these sets")
		)} *</label>
			<textarea id="${inputId}" rows="2" data-program-reason="1">${esc(
			load.override_reason || ""
		)}</textarea>
		</div>`;
	},
};
