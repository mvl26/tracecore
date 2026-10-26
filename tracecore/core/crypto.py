"""Băm mã bệnh nhân để tra cứu mà không giải mã (FEAT-028, FR-M2-19, NFR-SEC-02, architecture §8 mã BN).

``patient_hash`` = HMAC-SHA256 của mã đã chuẩn hóa (bỏ khoảng trắng hai đầu, viết hoa). Khóa là
``tc_patient_hash_key`` trong site_config; site chưa đặt khóa riêng thì dùng ``encryption_key`` của site (cùng khóa
Frappe mã hóa trường Password). Đổi khóa thì phải chạy lại patch điền hash. Chỉ khớp chính xác, không tìm gần đúng.
"""

import hashlib
import hmac

import frappe
from frappe.utils.password import get_encryption_key


def _key():
	return (frappe.conf.get("tc_patient_hash_key") or get_encryption_key()).encode()


def normalise_patient_code(code):
	return (code or "").strip().upper()


def patient_hash(code):
	"""Hash 64 ký tự hex của mã bệnh nhân; mã trống → None."""
	text = normalise_patient_code(code)
	if not text:
		return None
	return hmac.new(_key(), text.encode(), hashlib.sha256).hexdigest()
