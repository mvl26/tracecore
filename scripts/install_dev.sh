#!/usr/bin/env bash
# Dựng bench DEV TraceCore (Ubuntu 22.04 / WSL): bench init theo deploy/pins.env, apps
# erpnext + hrms + tracecore, site dev (developer_mode) và site test (allow_tests). Idempotent.
#
#   scripts/install_dev.sh [--dry-run]
#
# Biến: BENCH_DIR (~/tracecore-dev), DEV_SITE (tracecore-dev.local), TEST_SITE (test_site),
# TRACECORE_SOURCE (đường dẫn/URL repo app, mặc định repo hiện tại).
# Mật khẩu: DB_ROOT_PASSWORD, ADMIN_PASSWORD từ env hoặc ~/.tracecore-dev-secrets — không bao giờ in ra.
set -euo pipefail

HERE=$(cd "$(dirname "$0")/.." && pwd)
# shellcheck source=../deploy/pins.env
. "$HERE/deploy/pins.env"
# shellcheck source=lib.sh
. "$HERE/scripts/lib.sh"
[ "${1:-}" = "--dry-run" ] && DRY_RUN=1

BENCH_DIR=${BENCH_DIR:-$HOME/tracecore-dev}
DEV_SITE=${DEV_SITE:-tracecore-dev.local}
TEST_SITE=${TEST_SITE:-test_site}
TRACECORE_SOURCE=${TRACECORE_SOURCE:-$HERE}
SECRETS_FILE=${SECRETS_FILE:-$HOME/.tracecore-dev-secrets}
if [ -f "$SECRETS_FILE" ]; then
	# shellcheck disable=SC1090
	. "$SECRETS_FILE"
fi
if [ "$DRY_RUN" = "1" ]; then
	DB_ROOT_PASSWORD=${DB_ROOT_PASSWORD:-__DB_ROOT_PASSWORD__}
	ADMIN_PASSWORD=${ADMIN_PASSWORD:-__ADMIN_PASSWORD__}
fi
: "${DB_ROOT_PASSWORD:?set DB_ROOT_PASSWORD (env or $SECRETS_FILE)}"
: "${ADMIN_PASSWORD:?set ADMIN_PASSWORD (env or $SECRETS_FILE)}"

log "bench $BENCH_DIR (frappe $FRAPPE_REF, erpnext $ERPNEXT_REF, hrms $HRMS_REF)"
unless "test -d '$BENCH_DIR/apps/frappe'" \
	bench init --frappe-branch "$FRAPPE_REF" --python "python$PYTHON_VERSION" "$BENCH_DIR"
[ "$DRY_RUN" = "1" ] || cd "$BENCH_DIR"

log "Redis của bench (cần cho new-site / install-app)"
unless "redis-cli -p 13000 ping" redis-server config/redis_cache.conf --daemonize yes
unless "redis-cli -p 11000 ping" redis-server config/redis_queue.conf --daemonize yes

log "apps"
unless "test -d apps/erpnext" bench get-app --branch "$ERPNEXT_REF" "$ERPNEXT_REPO"
unless "test -d apps/hrms" bench get-app --branch "$HRMS_REF" "$HRMS_REPO"
unless "test -d apps/tracecore" bench get-app "$TRACECORE_SOURCE"
verify_pin frappe "$FRAPPE_SHA"
verify_pin erpnext "$ERPNEXT_SHA"
verify_pin hrms "$HRMS_SHA"

for site in "$DEV_SITE" "$TEST_SITE"; do
	log "site $site"
	unless "test -d 'sites/$site'" \
		bench new-site "$site" --db-root-password "$DB_ROOT_PASSWORD" --admin-password "$ADMIN_PASSWORD"
	for app in erpnext hrms tracecore; do
		unless "bench --site '$site' list-apps | grep -q '^$app'" bench --site "$site" install-app "$app"
	done
done

run bench --site "$DEV_SITE" set-config developer_mode 1
run bench --site "$DEV_SITE" set-config tc_gs1_company_prefix 9520000
run bench --site "$TEST_SITE" set-config allow_tests true
run bench use "$DEV_SITE"
run bench build --app tracecore
log "done - dev site $DEV_SITE, test site $TEST_SITE (chạy: bench start)"
