/* global tracecore */
// Gọi RPC Desk trả body `ok: false` khi chặn nghiệp vụ (reject_block). Body đó đi kèm HTTP 404/409/422, mà
// frappe.call chỉ đưa vào nhánh `error(xhr)` (request.js không có handler cho các mã này), nên form nào chỉ đọc
// `callback` sẽ không bao giờ thấy lỗi chặn. Helper này đọc body ở cả hai nhánh:
//   on_ok(result)    — body ok (HTTP 200)
//   on_block(error)  — body ok: false; `error` = {code, title, reason, action, items}
//   on_fail()        — lỗi khác (mạng, quyền, 500…): Frappe đã tự hiện thông báo
frappe.provide("tracecore");

tracecore.desk_call = function ({ method, args, on_ok, on_block, on_fail }) {
	const handle = (result) => {
		if (result && result.ok === false) {
			on_block && on_block(result.error || {});
			return;
		}
		on_ok && on_ok(result || {});
	};
	frappe.call({
		method,
		args,
		callback: (response) => handle(response.message),
		error: (xhr) => {
			const body = xhr && xhr.responseJSON && xhr.responseJSON.message;
			if (body && body.ok === false) {
				handle(body);
				return;
			}
			on_fail && on_fail();
		},
	});
};

// Như frappe.xcall nhưng gửi GET: RPC chỉ nhận GET (`@frappe.whitelist(methods=["GET"])`) trả 403 "Không được phép"
// cho POST, mà frappe.xcall luôn gửi POST. Trả Promise của `message`; lỗi thì reject như xcall.
tracecore.desk_get = function (method, args) {
	return new Promise((resolve, reject) => {
		frappe.call({
			method,
			args,
			type: "GET",
			callback: (response) => resolve(response.message),
			error: (response) => reject(response && response.message),
		});
	});
};
