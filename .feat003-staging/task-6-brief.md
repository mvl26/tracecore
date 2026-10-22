## Task 6: Shell trạm đăng nhập, idle lock, logout

**Files:** Modify Page `station`, `station_t4.js`, tests; create Playwright tests.

- [ ] UI kiosk/PDA: chưa có phiên chỉ hiện quét thẻ; success hiện người/trạm/hạn; lỗi inline có lý do/hành động.
- [ ] Idle 10 phút khóa/xóa state; logout/rút/quét lại thẻ kết thúc session; server expiry ép về login.
- [ ] Token chỉ ở memory/sessionStorage, không localStorage; calls truyền token an toàn.
- [ ] Test login trạm thứ hai khiến trạm cũ heartbeat bị từ chối; commit.

### Binding interfaces from Task 4

- Auth endpoints are Guest POST RPCs under `tracecore.v1.station`: login(card_id, station, client_ts), heartbeat(token, client_ts), logout(token, client_ts), verify_pin(token, pin, client_ts). Token is passed in JSON body, not Authorization header.
- Login response contains `{ok, session:{token, employee, employee_name, user, station, expires_at, roles}}`; errors are `{ok:false,error:{code,title,reason,action}}` with HTTP status.
- All T4 human kiosk RPCs require body `token` and derive station/user from session. The page's rpc helper must attach the in-memory/sessionStorage token for protected T4 calls without leaking it to localStorage, URLs, DOM, errors, or console.
- Authentication RPCs require client_ts. Existing idempotency and scan timestamps remain intact.
- Server idle cutoff is authoritative 10 minutes. Client may proactively lock at 10 minutes but heartbeat/session error must always force login and clear token.
- Second login replaces first server session; old kiosk heartbeat must clear state and show login.
- Preserve FEAT-018 T4 interface/layout/indicator-lot dedicated input behavior and offline error behavior. Authentication shell wraps it; it must not alter packing business rules.
- UI strings translatable; inline error displays title/reason/action. No hardcoded demo credentials or card numbers.
