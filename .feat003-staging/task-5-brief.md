## Task 5: Vận hành tài khoản web và vô hiệu nhân viên

**Files:** Create `core/account.py`, tests; modify hooks/install/provision/settings/translations.

- [ ] Test password min 10, expiry 90 ngày, khóa sau 5; 2FA đúng role.
- [ ] Đổi PIN/password yêu cầu giá trị cũ và audit không secret; reset bởi R10 hoặc R02 có proof, bắt đổi lần sau.
- [ ] Employee nghỉ việc: card/User disabled, mọi session đóng; lịch sử audit giữ nguyên.
- [ ] Test chỉ R10 tạo/vô hiệu User; commit.

### Binding decisions

- Password minimum 10 characters, lock after 5 failed logins, expiry 90 days.
- Web login roles R01/R02/R09/R10 use User + 2FA; station login uses card and PIN for privileged actions.
- PIN exactly 6 digits; stored as encrypted bcrypt, never logged or serialized.
- Employee card ID must be trim/uppercase and unique.
- When an Employee leaves or card becomes disabled, all open station sessions must close. Leaving also disables linked User; no delete of User/Employee/session/audit.
- R10 can reset accounts. R02 reset requires a valid short-lived station PIN proof; do not weaken this by accepting a raw client identity.
- If Frappe v15 has no native 90-day setting, implement a precise application-level mechanism and test it; do not invent a non-existent field.
