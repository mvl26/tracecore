"""Thêm cột Tên cạnh mọi Link `in_list_view` của DocType TraceCore (Amendment A-65).

    python scripts/add_name_columns.py            # chỉ in kế hoạch
    python scripts/add_name_columns.py --write    # sửa JSON DocType + thêm dòng vi.csv

Chạy lại an toàn: Link đã có trường ``<link>_name`` thì bỏ qua. Quy tắc ở ``tracecore/core/name_columns.py``.
"""

import csv
import io
import json
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tracecore.core.name_columns import (
	GRID_MAX_COLUMNS,
	NAME_FIELD,
	name_fieldname,
	skip_reason,
)

VI_CSV = ROOT / "tracecore" / "translations" / "vi.csv"
DEFAULT_COLUMNS = {"Check": 1, "Int": 1, "Float": 1, "Percent": 1}


def label_of(df):
	return df.get("label") or df["fieldname"].replace("_", " ").title()


def load_vi():
	"""{(nhãn, context): bản dịch} từ vi.csv hiện có."""
	with VI_CSV.open(encoding="utf-8", newline="") as f:
		return {(r[0], r[2] if len(r) > 2 else ""): r[1] for r in csv.reader(f) if len(r) > 1}


def vi_name_label(vi, doctype, link_label):
	base = vi.get((link_label, doctype)) or vi.get((link_label, ""))
	return f"Tên {base[0].lower()}{base[1:]}" if base else None


def fit_columns(fields):
	"""Đặt ``columns`` cho mọi trường in_list_view của bảng con sao cho tổng ≤ GRID_MAX_COLUMNS."""
	shown = [f for f in fields if f.get("in_list_view")]
	for f in shown:
		f["columns"] = f.get("columns") or DEFAULT_COLUMNS.get(f["fieldtype"], 2)
	while sum(f["columns"] for f in shown) > GRID_MAX_COLUMNS:
		widest = max(reversed(shown), key=lambda f: f["columns"])
		if widest["columns"] <= 1:
			break
		widest["columns"] -= 1


def serialize(doc, text):
	"""JSON theo đúng kiểu file gốc: 1 khoảng trắng (Frappe) hoặc kiểu gọn mỗi trường một dòng (viết tay)."""
	if '"fields": [\n  {"' not in text:
		return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"
	dump = lambda value: json.dumps(value, ensure_ascii=False)  # noqa: E731
	out = re.sub(
		r'( "fields": \[\n)(.*?)(\n \],)',
		lambda m: m.group(1) + ",\n".join("  " + dump(f) for f in doc["fields"]) + m.group(3),
		text,
		count=1,
		flags=re.S,
	)
	out = re.sub(
		r' "field_order": \[.*?\],\n',
		lambda m: (
			' "field_order": [\n' + ",\n".join("  " + dump(n) for n in doc["field_order"]) + "\n ],\n"
			if "\n  " in m.group(0)
			else f' "field_order": {dump(doc["field_order"])},\n'
		),
		out,
		count=1,
		flags=re.S,
	)
	return re.sub(r'"modified": "[^"]*"', lambda m: f'"modified": {dump(doc["modified"])}', out, count=1)


def process(path, write, vi, report):
	text = path.read_text(encoding="utf-8")
	doc = json.loads(text)
	if doc.get("doctype") != "DocType" or path.stem != path.parent.name:
		return []
	if serialize(doc, text) != text:
		report["unsafe"].append(str(path.relative_to(ROOT)))  # định dạng lạ: sửa tay
		return []
	name, fields, added = doc["name"], doc["fields"], []
	order = doc.get("field_order")
	for df in list(fields):
		kind = df["fieldtype"]
		if not df.get("in_list_view") or kind not in ("Link", "Dynamic Link"):
			continue
		if kind == "Dynamic Link":
			report["dynamic"].append(f"{name}.{df['fieldname']}")
			continue
		reason = skip_reason(name, df["fieldname"], df["options"])
		new = name_fieldname(df["fieldname"])
		existing = next((f for f in fields if f["fieldname"] == new), None)
		if reason is None and existing:
			if existing["fieldtype"] != "Data" or existing.get("in_list_view"):
				reason = "đã có trường cùng tên"
			else:  # trường tên có sẵn nhưng ẩn khỏi danh sách: bật hiển thị, không thêm trường trùng
				existing.update(in_list_view=1, read_only=1)
				existing.setdefault("fetch_from", f"{df['fieldname']}.{NAME_FIELD[df['options']]}")
				report["added"].append(f"{name}.{new} (có sẵn, bật in_list_view)")
				added.append((name, new, existing["label"], label_of(df)))
				continue
		if reason:
			report["skipped"].append(f"{name}.{df['fieldname']} → {df['options']}: {reason}")
			continue
		label = f"{label_of(df)} Name"
		field = {
			"fetch_from": f"{df['fieldname']}.{NAME_FIELD[df['options']]}",
			"fieldname": new,
			"fieldtype": "Data",
			"in_list_view": 1,
			"label": label,
			"no_copy": 1,
			"read_only": 1,
			"translatable": 0,
		}
		fields.insert(fields.index(df) + 1, field)
		if order is not None and df["fieldname"] in order:
			order.insert(order.index(df["fieldname"]) + 1, new)
		added.append((name, new, label, label_of(df)))
		report["added"].append(f"{name}.{new} ← {field['fetch_from']}")
	if added:
		if doc.get("istable"):
			fit_columns(fields)
		doc["modified"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
		if write:
			path.write_text(serialize(doc, text), encoding="utf-8", newline="\n")
	return added


def main():
	write = "--write" in sys.argv
	vi = load_vi()
	report = {"added": [], "skipped": [], "dynamic": [], "unsafe": []}
	added = []
	for path in sorted((ROOT / "tracecore").glob("**/doctype/*/*.json")):
		added += process(path, write, vi, report)
	rows, missing = [], []
	for doctype, _field, label, link_label in added:
		if (label, doctype) in vi:
			continue
		translated = vi_name_label(vi, doctype, link_label)
		if translated:
			rows.append((label, translated, doctype))
		else:
			missing.append(f"{doctype}: {label}")
	if write and rows:
		buf = io.StringIO()
		csv.writer(buf, lineterminator="\n").writerows(rows)
		with VI_CSV.open("a", encoding="utf-8", newline="") as f:
			f.write(buf.getvalue())
	for key in ("added", "skipped", "dynamic", "unsafe"):
		print(f"## {key} ({len(report[key])})")
		print("\n".join(report[key]))
	print(
		f"## vi.csv: {len(rows)} dòng {'đã thêm' if write else 'sẽ thêm'}; thiếu bản dịch nhãn gốc ({len(missing)}):"
	)
	print("\n".join(missing))


if __name__ == "__main__":
	main()
