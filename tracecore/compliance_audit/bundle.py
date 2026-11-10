"""Phiếu gói dự phòng gắn đợt thiết bị (FEAT-062; FR-M12-07, BRU-AUD-003; A-141 e).

Chấm tất-cả-hoặc-không là ``scoring.all_or_none`` (FEAT-060). Ở đây chỉ kiểm `Audit Session.device_episode`:

- mẫu gói VAP / CLABSI / CAUTI bắt buộc gắn đợt thiết bị; mẫu gói SSI / Khác không bắt buộc;
- đợt phải cùng khoa, đang đặt tại ngày phiếu (đặt ≤ ngày phiếu ≤ ngày rút) và đúng loại thiết bị của gói;
- mẫu không phải gói dự phòng không nhận đợt.

Đọc `Device Episode` (M13) qua ``frappe.db`` theo Link, không import module M13. Đợt đã ghi sổ trên phiếu offline
(phát lại) cũng kiểm như phiếu trực tuyến: đợt đóng sau ngày phiếu vẫn hợp lệ.
"""

import frappe
from frappe import _
from frappe.utils import getdate

from tracecore.core.errors import Block, BlockedError

BUNDLE_TYPE = "Prevention Bundle"
DEVICE_OF_BUNDLE = {"VAP": "Ventilator", "CLABSI": "Central Line", "CAUTI": "Urinary Catheter"}
EPISODE_DOCTYPE = "Device Episode"


def _invalid(reason, action):
	return BlockedError(
		Block(
			"AUDIT_EPISODE_INVALID",
			_("Device episode not valid for this audit"),
			reason,
			action,
			items=["device_episode"],
		)
	)


def validate(doc):
	"""Gọi từ ``sessions.validate`` sau khi đã biết mẫu."""
	template = (
		frappe.db.get_value("Audit Template", doc.audit_template, ["audit_type", "bundle_type"], as_dict=True)
		or frappe._dict()
	)
	device = DEVICE_OF_BUNDLE.get(template.bundle_type) if template.audit_type == BUNDLE_TYPE else None
	if not doc.device_episode:
		if device:
			raise BlockedError(
				Block(
					"AUDIT_EPISODE_REQUIRED",
					_("Device episode required"),
					_("A {0} bundle audit must be linked to an open device episode.").format(
						template.bundle_type
					),
					_("Choose the patient's open device episode, then post the audit."),
					items=["device_episode"],
				)
			)
		return
	if template.audit_type != BUNDLE_TYPE:
		raise _invalid(
			_("Only prevention bundle audits are linked to a device episode."),
			_("Remove the device episode from this audit."),
		)
	episode = frappe.db.get_value(
		EPISODE_DOCTYPE,
		doc.device_episode,
		["department", "device_type", "inserted_on", "removed_on"],
		as_dict=True,
	)
	if not episode:
		raise _invalid(
			_("Device episode {0} does not exist.").format(doc.device_episode),
			_("Choose an open device episode of the department."),
		)
	if episode.department != doc.department:
		raise _invalid(
			_("Device episode {0} belongs to another department.").format(doc.device_episode),
			_("Choose an open device episode of the audited department."),
		)
	if device and episode.device_type != device:
		raise _invalid(
			_("The {0} bundle applies to {1}, but episode {2} is {3}.").format(
				template.bundle_type, _(device).lower(), doc.device_episode, _(episode.device_type).lower()
			),
			_("Choose an episode with the matching device or another bundle template."),
		)
	on = getdate(doc.audit_date)
	if getdate(episode.inserted_on) > on or (episode.removed_on and getdate(episode.removed_on) < on):
		raise _invalid(
			_("The device of episode {0} was not in place on the audit day.").format(doc.device_episode),
			_("Choose an episode that is open on the audit day."),
		)
