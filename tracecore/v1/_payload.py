"""Định dạng response chung cho RPC tracecore.v1 (lỗi nghiệp vụ: kết quả → lý do → hành động)."""


def rejection(code, title, reason, action):
	return {"ok": False, "error": {"code": code, "title": title, "reason": reason, "action": action}}
