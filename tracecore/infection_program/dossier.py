"""Phần "kế hoạch, biên bản Hội đồng, đào tạo" của gói hồ sơ KSNK (FEAT-074; FR-M9-30; A-152).

Đăng ký qua hook ``tracecore_ic_dossier_sections``:
- ``plan_activities``: hoạt động của kế hoạch KSNK năm (đã duyệt hoặc đang soạn) của các năm trong dải.
- ``committee_meetings``: biên bản họp Hội đồng KSNK đã ghi sổ trong dải (nội dung, số người dự, nghị quyết).
- ``training``: lớp đào tạo KSNK (HRMS Training Event đã ghi sổ thuộc chương trình có loại KSNK) bắt đầu trong dải: số
  học viên, số đạt. Không có tên học viên.
"""

import frappe
from frappe import _
from frappe.utils import cint, strip_html_tags

from tracecore.core.dossier import DossierSection, ExportField

PLAN = "IC Annual Plan"
MEETING = "IC Committee Meeting"


def plan_rows(ctx):
	out = []
	for plan in frappe.get_all(
		PLAN,
		filters={"year": ["in", ctx.years], "docstatus": ["<", 2]},
		fields=["name", "year", "docstatus", "approved_on"],
		order_by="year asc, name asc",
	):
		state = _("Approved") if plan.docstatus == 1 else _("Draft")
		for row in frappe.get_all(
			"IC Plan Activity",
			filters={"parent": plan.name, "parenttype": PLAN},
			fields=[
				"activity",
				"measure_group",
				"department_name",
				"responsible_name",
				"due_date",
				"status",
				"completed_on",
				"evidence",
			],
			order_by="idx asc",
		):
			out.append(
				{
					"plan": plan.name,
					"year": plan.year,
					"plan_state": state,
					"approved_on": plan.approved_on,
					**row,
				}
			)
	return out


def meeting_rows(ctx):
	out = []
	for meeting in frappe.get_all(
		MEETING,
		filters={"docstatus": 1, "meeting_date": ["between", [ctx.from_date, ctx.to_date]]},
		fields=["name", "meeting_date", "committee", "agenda", "minutes"],
		order_by="meeting_date asc",
	):
		resolutions = frappe.get_all(
			"IC Resolution",
			filters={"parent": meeting.name, "parenttype": MEETING},
			fields=["content", "status"],
			order_by="idx asc",
		)
		out.append(
			{
				"name": meeting.name,
				"meeting_date": meeting.meeting_date,
				"committee": meeting.committee,
				"agenda": strip_html_tags(meeting.agenda or ""),
				"minutes": strip_html_tags(meeting.minutes or ""),
				"attendees": frappe.db.count(
					"IC Meeting Attendee", {"parent": meeting.name, "parenttype": MEETING}
				),
				"resolutions": "\n".join(
					f"{row.content} ({_(row.status)})" for row in resolutions if row.content
				),
			}
		)
	return out


def training_rows(ctx):
	events = frappe.db.sql(
		"""
		select te.name, te.event_name, date(te.start_time) as start_date, te.training_program,
			tp.tc_ic_category as category
		from `tabTraining Event` te
		join `tabTraining Program` tp on tp.name = te.training_program
		where te.docstatus = 1 and ifnull(tp.tc_ic_category, '') != ''
			and date(te.start_time) between %(start)s and %(end)s
		order by te.start_time asc
		""",
		{"start": ctx.from_date, "end": ctx.to_date},
		as_dict=True,
	)
	for event in events:
		event.attendees = frappe.db.count(
			"Training Event Employee", {"parent": event.name, "parenttype": "Training Event"}
		)
		event.passed = cint(
			frappe.db.sql(
				"""
				select count(distinct tre.employee)
				from `tabTraining Result Employee` tre
				join `tabTraining Result` tr on tr.name = tre.parent and tre.parenttype = 'Training Result'
				where tr.docstatus = 1 and tr.training_event = %s and tre.tc_ic_passed = 1
				""",
				event.name,
			)[0][0]
		)
	return events


def register():
	return [
		DossierSection(
			key="plan_activities",
			label="Infection control plan",
			order=40,
			fields=[
				ExportField("plan", "Plan"),
				ExportField("year", "Year", "int"),
				ExportField("plan_state", "Plan Status"),
				ExportField("approved_on", "Approved On", "date"),
				ExportField("activity", "Activity"),
				ExportField("measure_group", "Measure Group", "select"),
				ExportField("department_name", "Department"),
				ExportField("responsible_name", "Responsible"),
				ExportField("due_date", "Due Date", "date"),
				ExportField("status", "Status", "select"),
				ExportField("completed_on", "Completed On", "date"),
				ExportField("evidence", "Evidence"),
			],
			rows=plan_rows,
		),
		DossierSection(
			key="committee_meetings",
			label="Committee meeting minutes",
			order=50,
			fields=[
				ExportField("name", "Meeting"),
				ExportField("meeting_date", "Meeting Date", "date"),
				ExportField("committee", "Committee"),
				ExportField("agenda", "Agenda"),
				ExportField("minutes", "Minutes"),
				ExportField("attendees", "Attendees", "int"),
				ExportField("resolutions", "Resolutions"),
			],
			rows=meeting_rows,
		),
		DossierSection(
			key="training",
			label="Infection control training",
			order=60,
			fields=[
				ExportField("name", "Training Event"),
				ExportField("event_name", "Event Name"),
				ExportField("start_date", "Start Date", "date"),
				ExportField("training_program", "Training Program"),
				ExportField("category", "Category", "select"),
				ExportField("attendees", "Attendees", "int"),
				ExportField("passed", "Passed", "int"),
			],
			rows=training_rows,
		),
	]
