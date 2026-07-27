# Beauty Bot — Foundation Refactor Design

**Date:** 2026-07-26  
**Scope:** Option B — extensible foundation + bugfixes + UI polish  
**Out of scope:** DB, booking slots, payment checks, reminders (next phase)

## Goal

Turn the current vitrina into a production-ready, extensible Telegram bot skeleton: no dead code, clear layers, hardened runtime, elevated UX. Behavior for the client stays the same (menu, price, portfolio, about, contacts, subscribe-gated master contact).

## Architecture

Keep `main.py` at repo root (Dockerfile). Packages:

```
config/           # settings (lazy-safe), constants
domain/           # enums, exceptions (future booking/payment ready)
infrastructure/   # bot factory, single-instance lock
services/         # subscription, portfolio, session, media cache
presentation/
  ui/             # screen helpers (edit/send/delete)
  keyboards/      # visual language
  texts/          # copy
handlers/         # thin routers
middlewares/      # logging, throttle, DI, errors
```

### Rules

1. Handlers only route and call services / UI helpers.
2. Services hold business logic; repositories appear when DB lands.
3. One UI module for “show text / show photo / safe delete”.
4. DI via middleware + explicit container created in lifespan.
5. Domain exceptions exist for next phase; unused formatters/models deleted.

### Runtime

- Lifespan: create bot → container → middlewares → routers → commands → polling → close session.
- Settings loaded once in main (not as a side-effect that breaks imports without `.env` for tools — keep `settings` but validate required fields only when building app).
- Throttling with TTL cleanup.
- Portfolio + welcome `file_id` cache.
- Session remains in-memory stub (replaced by DB users later).

## UI / Visual language

Direction: **quiet luxury / editorial salon** — not emoji carnival.

- Primary CTA alone full-width: «Запись».
- Secondary actions in a calm 2-column grid: Работы · Прайс · О мастере · Контакты.
- Labels short, sentence-case feel, minimal emoji (at most one mark where it clarifies).
- Copy: tighter, more confident, less soft filler; keep Beauty SZN voice.
- Portfolio nav: `←` `1 / N` `→` + Назад.
- Subscription: Подписаться (URL) → Проверить подписку → Назад.
- Dividers: light typographic lines, not emoji walls.

## Bugfixes included

- Delete/repair dead `utils/formatters.py`, broken `utils/dates.py` imports.
- Remove/relocate orphan booking exceptions & `MY_BOOKINGS`.
- Fix portfolio `file_id` after `edit_media`.
- Cache welcome cover `file_id`.
- Throttle memory cleanup.
- Deduplicate delete/show helpers.
- Fix README path (`beauty_bot` → project root).
- Remove apscheduler log stub without dependency.

## Success criteria

- `python main.py` starts cleanly.
- All current user flows work.
- No importable broken modules.
- New feature folders have an obvious home.
- UI reads premium, not template-bot.
