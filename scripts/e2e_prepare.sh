#!/usr/bin/env bash
# Chuẩn bị một site DEV/TEST cho e2e kiosk (KHÔNG dùng cho production):
#   1. Hoàn tất Setup Wizard ERPNext bằng dữ liệu test (Desk ép user về Setup Wizard nếu chưa xong)
#   2. Định dạng Việt Nam (System Settings)
#   3. User trạm cho smoke FEAT-001 (TR-003, không phải T4) và user trạm T4 (TR-004); mật khẩu ngẫu nhiên
#      lưu trong file quyền 600
#   4. Set Unit demo để quét (smoke) và dữ liệu demo T4 (devdata.ensure_t4_demo: bộ hấp/plasma/gate-fail,
#      lô chỉ thị, mã cuộn nhãn, máy in)
# Kết quả ghi vào $TC_E2E_ENV (mặc định ~/.tracecore-e2e.env): TC_E2E_USER, TC_E2E_PASSWORD, TC_E2E_SET_ID,
# TC_E2E_STATION (smoke) và TC_E2E_T4_USER/PASSWORD/STATION + TC_E2E_T4_<khóa của ensure_t4_demo>.
# Bộ demo T4 bị tiêu thụ khi test đóng gói chạy: chạy lại script này trước mỗi lần chạy tests_e2e/test_station_t4.py.
#
# Dùng: scripts/e2e_prepare.sh <site>    (BENCH_DIR mặc định ~/tracecore-dev)
set -euo pipefail

SITE="${1:?usage: scripts/e2e_prepare.sh <site>}"
BENCH_DIR="${BENCH_DIR:-$HOME/tracecore-dev}"
ENV_FILE="${TC_E2E_ENV:-$HOME/.tracecore-e2e.env}"
STATION="${TC_E2E_STATION:-TR-003}"
T4_STATION="${TC_E2E_T4_STATION:-TR-004}"

cd "$BENCH_DIR"
bench_exec() { bench --site "$SITE" execute "$@" | tail -n 1; }

if [ "$(bench_exec frappe.is_setup_complete)" != "true" ]; then
	year=$(date +%Y)
	bench_exec frappe.desk.page.setup_wizard.setup_wizard.setup_complete --kwargs "{'args': {
		'language': 'English', 'country': 'Vietnam', 'timezone': 'Asia/Ho_Chi_Minh', 'currency': 'VND',
		'full_name': 'TraceCore Test', 'company_name': 'TraceCore Test', 'company_abbr': 'TCT',
		'chart_of_accounts': 'Standard', 'fy_start_date': '${year}-01-01', 'fy_end_date': '${year}-12-31',
		'setup_demo': 0}}" > /dev/null
	echo "setup wizard completed on $SITE"
fi
bench_exec tracecore.setup.install.apply_system_settings > /dev/null

umask 077
password=""
if [ -s "$ENV_FILE" ]; then
	password=$(sed -n 's/^TC_E2E_PASSWORD=//p' "$ENV_FILE")
fi
if [ -z "$password" ]; then
	password="Tc-$(head -c 24 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 16)-9!"
fi
user=$(bench_exec tracecore.setup.provision.station_user --kwargs "{'station': '$STATION', 'password': '$password'}" | tr -d '"')
t4_user=$(bench_exec tracecore.setup.provision.station_user --kwargs "{'station': '$T4_STATION', 'password': '$password'}" | tr -d '"')
set_id=$(bench_exec tracecore.setup.devdata.ensure_demo_set | tr -d '"')
t4_demo=$(bench_exec tracecore.setup.devdata.ensure_t4_demo)

{
	printf 'TC_E2E_USER=%s\nTC_E2E_PASSWORD=%s\nTC_E2E_SET_ID=%s\nTC_E2E_STATION=%s\n' \
		"$user" "$password" "$set_id" "$STATION"
	printf 'TC_E2E_T4_USER=%s\nTC_E2E_T4_PASSWORD=%s\nTC_E2E_T4_STATION=%s\n' "$t4_user" "$password" "$T4_STATION"
	printf '%s' "$t4_demo" | python3 -c 'import json, sys; [print("TC_E2E_T4_%s=%s" % (k.upper(), v)) for k, v in json.load(sys.stdin).items()]'
} > "$ENV_FILE"
chmod 600 "$ENV_FILE"
echo "e2e ready on $SITE: smoke user $user ($STATION), T4 user $t4_user ($T4_STATION), set $set_id (credentials in $ENV_FILE)"
