# Task 6 — Redirect web login to the real Home

Commit: `4e1ccdf9e3801c51d002206b98c6315f00421373`.

Exact commit message: `feat(home): redirect web login to TraceCore`.

## Framework field and necessary scope adjustment

Inspected the installed Frappe v15 source in `~/tracecore-dev/apps/frappe`:

- `frappe/auth.py`, `LoginManager.post_login`: runs `on_login` before `get_user_info`, session creation and `set_user_info`.
- `LoginManager.__slots__` has no supported landing-route attribute. `set_user_info` unconditionally writes `frappe.local.response["home_page"]` for both System and Website users after the login hook, overriding any earlier assignment.
- `frappe/templates/includes/login/login.js`: the successful System User branch assigns `sanitise_redirect(get_url_arg("redirect-to")) || data.home_page`. It does not use `data.redirect_to` for the `Logged In` result. OTP submissions use the same form `cmd=login`, with `/` as the legacy endpoint; the initial login form posts to `/login`.
- `frappe/app.py`, `run_after_request_hooks`: the supported `after_request` hook receives the completed Werkzeug response after its JSON has been built.

Therefore the two-file brief cannot implement a working response-field assignment solely inside `on_login`. Parent explicitly authorized adding exactly one `after_request` registration in `tracecore/hooks.py`. Final change is three files: `tracecore/core/account.py`, `tracecore/core/tests/test_account.py`, and `tracecore/hooks.py`.

`on_login` preserves the existing password guard. After it succeeds, it records the authenticated non-Guest user in request-local flags only for form-encoded POST `cmd=login` to `/login` or `/`. The response hook consumes that flag once, requires a matching authenticated session and successful JSON login message, and sets the supported wire field `home_page` to `/tracecore`. Failed, malformed, non-JSON, non-login, Guest, unauthenticated and API responses remain untouched. The flag is cleared on every callback path and before the expiry check.

The hook never copies `redirect-to` into the response or writes `redirect_to`; the existing client retains its same-origin sanitizer and precedence for valid explicit routes. No password policy, role, API method, session or station-card code changed.

## TDD evidence

Tests were written first and run against real installed Frappe/MariaDB/Redis `test_site`, using current Windows sources via `PYTHONPATH=/mnt/d/tracecore` while the WSL app checkout remained at `9d36830`.

The initial whole-module red run executed 39 tests. It found an unconfigured test-user OTP enrollment attempting outgoing email. The test helper was corrected to enroll the fixture in OTP App and complete real OTP, following the existing account-recovery test convention; authentication itself is not mocked. Database commits alone are suppressed to preserve the existing per-test savepoint isolation.

Feature-specific RED, before production changes:

```text
PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --module tracecore.core.tests.test_account --test test_web_login_sets_tracecore_home_after_password_check --test test_login_home_preserves_explicit_redirect_for_framework_validation --test test_login_home_hook_ignores_failed_or_unrelated_responses

Ran 3 tests in 7.677s
FAILED (failures=5)
```

Expected failures: final real login JSON still had `/app` instead of `/tracecore` (normal login plus three explicit-route cases), and the absent callback did not consume the request-local flag. No test errors remained.

Focused GREEN after implementation:

```text
PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --module tracecore.core.tests.test_account --test test_web_login_sets_tracecore_home_after_password_check --test test_expired_password_still_blocks_before_redirect --test test_guest_and_api_login_do_not_receive_unsafe_redirect --test test_login_home_preserves_explicit_redirect_for_framework_validation --test test_login_home_hook_ignores_failed_or_unrelated_responses

Ran 5 tests in 11.715s
OK
```

Tests exercise real `LoginManager.login`, OTP, expiry handling, `set_user_info`, JSON serialization and registered `run_after_request_hooks`; they do not substitute a simplified login manager. Additional regression coverage checks Website User success, request method/content type/command, malformed JSON, matching authenticated user and callback idempotence.

## Verification

- Installed Frappe client supplemental check: `node /mnt/d/tracecore/.superpowers/sdd/check-task-6-login-client.cjs` from the bench: **7/7 passed**. Evaluates the exact installed `sanitise_redirect` function and exact installed `Logged In` redirect expression. Valid relative and same-origin absolute explicit routes win; absent, external absolute/protocol-relative, JavaScript and backslash-host destinations fall back to `/tracecore`.
- Full account suite: `PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --module tracecore.core.tests.test_account`: **41/41 passed**, `Ran 41 tests in 131.767s`, `OK`. Existing password, account/session, station-card, role and offboarding tests stayed green.
- Home website tests: `PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --module tracecore.tests.test_home_page`: **8/8 passed**, `Ran 8 tests in 4.254s`, `OK`.
- Scoped pre-commit: `cd /mnt/d/tracecore && pre-commit run --files tracecore/core/account.py tracecore/core/tests/test_account.py tracecore/hooks.py`: **all applicable checks passed**, exit 0. Whitespace, merge conflicts, AST/debug statements, Ruff import/lint/formatting, Bandit, architecture rules and BRU checks passed. Inapplicable hooks skipped. Initial runs applied Ruff import ordering/formatting only.
- `git diff --check` and `git diff --cached --check`: passed before final commit. `git show --stat HEAD` confirms exactly the three authorized files; final tracked worktree is clean. Only pre-existing/uncommitted `.superpowers` artifacts remain.

## Self-review and remaining verification

Reviewed the account and hooks diff: only request-local redirect selection was added, password rejection still occurs before redirect marking, the callback cannot change the JSON until a matching session exists, and all early exits consume the flag. Response mutation uses Werkzeug `set_data`, which updates Content-Length. Only the fixed local Home route is assigned. Tests retain existing account/station coverage and clean up generated session cache entries.

The standard API login endpoint `/api/method/login` is explicitly excluded, including form-encoded API requests. Form POST `cmd=login` to the framework's two browser endpoints is the compatibility boundary for interactive login.

Parent will fast-forward the clean WSL checkout after the commit, then run the exact normal bench commands without `PYTHONPATH`. This final synced-checkout verification is required before marking Task 6 integrated. `.superpowers` reports and the supplemental verification script are not committed.

## Review follow-up — OTP across separate requests

Reviewer Minor requested a committed regression for the actual second-stage OTP request to `/`. The previous helper completed both stages in one request context; the production predicate already allowed `/`, but that browser boundary lacked direct coverage.

Added `test_otp_login_redirects_across_fresh_request_boundary` only in `tracecore/core/tests/test_account.py`:

- First, a real R02 password form POST to `/login` produces the OTP challenge, remains Guest, does not set a landing flag and leaves its serialized challenge response unchanged.
- Second, a distinct form POST to `/` carries exactly `cmd`, `otp`, `tmp_id`, with a new LoginManager, Request, request-local flags dictionary, Guest session and empty response. Real Frappe authentication restores credentials from the challenge cache. The final registered response hook returns `message = "Logged In"` and `home_page = "/tracecore"`, consuming the flag.
- Third, an unrelated fresh request has no inherited flag and its response remains byte-for-byte unchanged. The old flags dictionaries and the restored outer test context also contain no landing flag.

The first run exposed a test assertion about `frappe.flags` object identity: that public name is a LocalProxy shared across contexts. The regression now compares the actual `frappe.local.flags` dictionaries, which are distinct. No production issue was found, and no production file changed.

Focused verification:

```text
PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --module tracecore.core.tests.test_account --test test_otp_login_redirects_across_fresh_request_boundary
Ran 1 test in 2.821s
OK
```

Scoped pre-commit: `cd /mnt/d/tracecore && pre-commit run --files tracecore/core/tests/test_account.py`: all applicable checks passed, exit 0. Ruff formatting was applied on the initial run; the final run passed whitespace, merge conflicts, AST/debug statements, Ruff sorting/lint/formatting, architecture and BRU checks. Inapplicable hooks skipped. `git diff --check -- tracecore/core/tests/test_account.py` passed. Self-review confirmed a single 54-line test addition and no production changes.

Full account suite: `PYTHONPATH=/mnt/d/tracecore bench --site test_site run-tests --module tracecore.core.tests.test_account`: **42/42 passed**, `Ran 42 tests in 171.686s`, `OK`. Existing password, OTP recovery, account and station-session tests remain green. WSL checkout was at `4e1ccdf`; the path override selected the added test from the Windows checkout.

Follow-up commit: `e12d4229b6e9d58437fff9c5f906aed12dec7cd9` — `test(home): cover OTP redirect request boundary`. `git show --stat HEAD` confirms the test file only, 54 inserted lines. Final tracked worktree is clean; `.superpowers` remains uncommitted. Parent may fast-forward the WSL checkout to this commit for normal-run integration evidence.
