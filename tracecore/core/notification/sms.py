"""Adapter SMS (FEAT-010, ADR-014): ``send(to, text)`` gọi gateway HTTP của bệnh viện theo `TraceCore Settings`.

Tắt sẵn: chưa có gateway thì không gửi và không tạo dòng thông báo SMS. Gateway giả định nhận JSON
``{"to", "text", "sender"}`` và trả HTTP 2xx khi nhận; khác gateway thì sửa ở đây, phần còn lại không đổi.
"""

import frappe
import requests

TIMEOUT_SECONDS = 10


def is_enabled() -> bool:
	settings = frappe.get_cached_doc("TraceCore Settings")
	return bool(settings.enable_sms and settings.sms_gateway_url)


def send(to: str, text: str) -> None:
	settings = frappe.get_cached_doc("TraceCore Settings")
	token = settings.get_password("sms_api_token", raise_exception=False)
	headers = {"Authorization": f"Bearer {token}"} if token else {}
	response = requests.post(
		settings.sms_gateway_url,
		json={"to": to, "text": text, "sender": settings.sms_sender or None},
		headers=headers,
		timeout=TIMEOUT_SECONDS,
	)
	response.raise_for_status()
