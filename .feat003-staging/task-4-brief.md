## Task 4: API station và guard RPC

**Files:** Modify `v1/station.py`, `_common.py`, station/pack/agent tests; create security tests.

- [ ] Test POST `login/logout/heartbeat/verify_pin`: schema, HTTP/mã lỗi, client_ts, audit/idempotency.
- [ ] Login nhận `card_id`, `station`; trả token một lần + display/role/expires, không trả secret.
- [ ] API sau login nhận token; verify_pin trả proof TTL ngắn cho thao tác đặc quyền.
- [ ] Guard RPC trạm nhưng giữ luồng `TC Agent`; Pack T4 lấy `packed_by` từ session, không client; regression FEAT-018.
- [ ] Commit `feat(v1): API phiên và xác minh PIN trạm`.

### Existing interfaces / binding decisions

- `tracecore.core.station_auth` owns login/session/heartbeat/logout/PIN and now creates/consumes a 120-second, single-use PIN proof bound to a live session/user.
- Opaque station token returned once; DB only SHA-256; absolute 8h, idle 10m; every privileged RPC derives actor from the authenticated session, never from client employee/user.
- `client_ts` is mandatory for FEAT-003 auth UI/API calls and must use existing parser/error contract. Existing FEAT-018 callers/tests may need explicit update; do not keep an undocumented optional compatibility gap.
- Station human UI calls can run from Guest/Frappe session context but must be authorized by station bearer token. `TC Agent` machine flow remains role/API-key based and must not regress.
- `verify_pin` must return only opaque short-lived proof, never PIN/hash. Proof reuse or use with another live session/user is rejected.
- T4 pack scan/generate/reprint/void must require a live station session for human kiosk calls, derive station and packed_by user from it, while preserving explicitly identified TC Agent machine integrations.
- Stable structured error bodies and appropriate HTTP statuses; no secrets in logs/audit/errors.
- Preserve FEAT-018 behavior, idempotency keys, client timestamps, maintenance/indicator logic.
