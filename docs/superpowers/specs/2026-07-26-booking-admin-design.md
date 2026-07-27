# Booking + Admin Design

**Date:** 2026-07-26  
**Payment:** Receipt-as-checkbox — any photo/document auto-confirms; forwarded to admin with booking notify.  
**DB:** PostgreSQL (deploy); SQLite allowed locally via `DATABASE_URL`.

## Client booking

1. Subscribe gate  
2. Full name → phone  
3. Pick day (with free slots) → pick time  
4. Slot `held` (15 min TTL, unique)  
5. Payment link + ask for receipt photo  
6. On photo/doc → `booked` + notify admin (text + receipt media)

## Admin

- Auth: `ADMIN_TELEGRAM_ID`  
- `/admin` or `/start` as admin → admin home  
- Schedule CRUD, bookings list, cancel, reschedule  
- Monthly (1st, 10:00 MSK): remind to publish schedule  

## Anti-race

- `Slot.status`: free | held | booked  
- Hold with `held_until` + `held_by_user_id`  
- Confirm only if still held by same user and not expired  
- Periodic cleanup of expired holds  
