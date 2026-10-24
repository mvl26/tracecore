"""Audit Log cho vật tư tiêu hao CSSD trên Item, Batch, Stock Entry của ERPNext (FEAT-041, F-6, NFR-SEC-03).

ERPNext dùng chung ba DocType này cho cả hàng hóa ngoài khoa KSNK, nên bộ lọc ``is_cssd_document`` chỉ cho
``core.audit.on_document_event`` ghi khi doc liên quan vật tư CSSD. Không đăng ký ``on_trash``: xóa bị chặn ở
permission (``inventory.permissions``), không ở hook.
"""

from tracecore.core import audit
from tracecore.inventory.items import is_cssd_item


def is_cssd_document(doc) -> bool:
	"""Item có nhóm CSSD; Batch của Item CSSD; Stock Entry có ít nhất một dòng Item CSSD."""
	if doc.doctype == "Item":
		return bool(doc.get("tc_item_group_cssd"))
	if doc.doctype == "Batch":
		return is_cssd_item(doc.get("item"))
	if doc.doctype == "Stock Entry":
		return any(is_cssd_item(row.get("item_code")) for row in doc.get("items") or [])
	return False


def on_cssd_event(doc, method: str) -> None:
	"""Handler ``doc_events``: ghi Audit Log (Create/Update/Submit/Cancel) cho tài liệu vật tư CSSD."""
	if is_cssd_document(doc):
		audit.on_document_event(doc, method)
