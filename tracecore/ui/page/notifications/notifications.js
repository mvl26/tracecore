// Desk Page notifications — SCR-42 Trung tâm thông báo (FEAT-010, FR-M9-10, UC-38).
// Danh sách thông báo của người đăng nhập, mới nhất trước; lọc chưa đọc / theo loại sự kiện; bấm một thông báo thì đánh
// dấu Đã đọc rồi đi tới chứng từ liên quan. Mọi quy tắc ở server (tracecore.v1.notification.*); trang chỉ trình bày.
// Trạng thái luôn có chữ (Khẩn / Chưa đọc), không chỉ màu. Có đủ 4 trạng thái: đang tải, trống, lỗi, mất mạng.

const TC_NTF = "tracecore.v1.notification.";
const TC_NTF_PAGE_SIZE = 50;
// ngữ cảnh dịch cho các từ chung (Tất cả, Chưa đọc, Khẩn…) để không đè bản dịch của Frappe ở chỗ khác
const NTF_CTX = "Notification Center";

frappe.pages["notifications"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Notification Center"),
		single_column: true,
	});
	const root = $("<section class='tc-notify-page' data-surface='WEB'></section>").appendTo(
		page.main
	);
	const state = {
		onlyUnread: 0,
		eventCode: "",
		rows: [],
		hasMore: false,
		unread: 0,
		request: 0,
	};
	const visible = () => frappe.get_route()[0] === "notifications";

	const filter = page.add_field({
		fieldname: "scope",
		fieldtype: "Select",
		label: __("Show", null, NTF_CTX),
		options: [
			{ value: "all", label: __("All", null, NTF_CTX) },
			{ value: "unread", label: __("Unread", null, NTF_CTX) },
		],
		default: "all",
		change() {
			state.onlyUnread = filter.get_value() === "unread" ? 1 : 0;
			load(true);
		},
	});
	page.set_secondary_action(__("Mark all as read"), () => markAllRead(), "check");

	function message(text, reason, kind) {
		root.empty();
		const box = $("<div role='status'></div>").appendTo(root);
		box.addClass(kind === "error" ? "tc-notify-error" : "tc-notify-empty").attr(
			"role",
			kind === "error" ? "alert" : "status"
		);
		$("<p></p>").css("font-weight", "bold").text(text).appendTo(box);
		if (reason) $("<p></p>").text(reason).appendTo(box);
		if (kind === "error")
			$("<button type='button' class='btn btn-primary'></button>")
				.text(__("Try again"))
				.on("click", () => load(true))
				.appendTo(box);
	}

	function render() {
		root.empty();
		const bar = $("<div class='tc-notify-bar'></div>").appendTo(root);
		$("<span class='tc-notify-count'></span>")
			.text(__("{0} unread", [state.unread]))
			.appendTo(bar);
		if (!state.rows.length) {
			message(
				state.onlyUnread ? __("No unread notifications") : __("No notifications yet"),
				__("New notifications appear here and in the bell at the top.")
			);
			return;
		}
		const list = $("<div class='tc-notify-list'></div>").appendTo(root);
		state.rows.forEach((row) => list.append(item(row)));
		if (state.hasMore)
			$("<button type='button' class='btn btn-default'></button>")
				.text(__("Load more"))
				.on("click", () => load(false))
				.appendTo(root);
	}

	function item(row) {
		const unread = row.status === "Sent";
		const urgent = row.urgency === "Urgent";
		const card = $("<article class='tc-notify-item' tabindex='0'></article>")
			.toggleClass("is-unread", unread)
			.toggleClass("is-urgent", urgent);
		const head = $("<div class='tc-notify-head'></div>").appendTo(card);
		if (urgent)
			$("<span class='tc-notify-tag is-urgent'></span>")
				.text(__("Urgent", null, NTF_CTX))
				.appendTo(head);
		if (unread)
			$("<span class='tc-notify-tag is-unread'></span>")
				.text(__("Unread", null, NTF_CTX))
				.appendTo(head);
		$("<span class='tc-notify-tag'></span>").text(__(row.event_label)).appendTo(head);
		$("<div class='tc-notify-subject'></div>")
			.toggleClass("is-read", !unread)
			.text(row.subject)
			.appendTo(card);
		if (row.message) $("<div></div>").text(row.message).appendTo(card);
		$("<div class='tc-notify-meta'></div>")
			.text(frappe.datetime.str_to_user(row.sent_at))
			.appendTo(card);
		const open = () => openRow(row);
		card.on("click", open).on("keydown", (event) => {
			if (event.key === "Enter" || event.key === " ") {
				event.preventDefault();
				open();
			}
		});
		return card;
	}

	async function openRow(row) {
		if (row.status === "Sent") {
			try {
				await frappe.xcall(TC_NTF + "mark_read", { names: JSON.stringify([row.name]) });
			} catch (error) {
				/* đọc không được thì vẫn cho mở chứng từ */
			}
		}
		if (row.link) window.location.assign(row.link);
		else load(true);
	}

	async function markAllRead() {
		try {
			await frappe.xcall(TC_NTF + "mark_all_read", { event_code: state.eventCode || null });
			load(true);
		} catch (error) {
			message(
				__("Cannot update notifications"),
				__("Check your connection, then try again."),
				"error"
			);
		}
	}

	async function load(reset) {
		if (!navigator.onLine) {
			message(__("Offline"), __("Connect to the network to see notifications."), "error");
			return;
		}
		const current = ++state.request;
		const start = reset ? 0 : state.rows.length;
		if (reset) message(__("Loading notifications…"), "");
		try {
			const data = await frappe.xcall(TC_NTF + "inbox", {
				only_unread: state.onlyUnread,
				event_code: state.eventCode || null,
				start,
				limit: TC_NTF_PAGE_SIZE,
			});
			if (current !== state.request || !visible()) return;
			state.rows = reset ? data.rows : state.rows.concat(data.rows);
			state.hasMore = data.has_more;
			state.unread = data.unread;
			render();
		} catch (error) {
			if (current === state.request && visible())
				message(
					__("Cannot load notifications"),
					__("Check your connection and account permissions, then try again."),
					"error"
				);
		}
	}

	frappe.realtime.on("tc_notification", () => {
		if (visible()) load(true);
	});
	window.addEventListener("online", () => visible() && load(true));
	window.addEventListener("offline", () => visible() && load(true));
	wrapper.tc_notify_load = () => load(true);
};

frappe.pages["notifications"].on_page_show = function (wrapper) {
	wrapper.tc_notify_load();
};
