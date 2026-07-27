# Foundation Refactor Implementation Plan

> **For agentic workers:** Execute block-by-block. Each block must leave the bot runnable.

**Goal:** Extensible foundation + bugfixes + premium UI without booking/payment features yet.

**Architecture:** Layered packages (`domain`, `infrastructure`, `services`, `presentation`, `handlers`, `middlewares`) with DI container and lifespan in `main.py`.

**Tech Stack:** Python 3.13, aiogram 3.29, python-dotenv

## Global Constraints

- Keep current client flows working (menu, price, portfolio, about, contacts, subscribe → contact).
- No DB / payments / reminders in this plan.
- `main.py` stays at repo root for Dockerfile.
- Quiet-luxury Telegram UI: minimal emoji, short labels, primary CTA alone.

---

### Block 1: Domain + dead code
- Create `domain/` (enums, exceptions, dates)
- Delete broken `utils/formatters.py`, relocate exceptions
- Remove `MY_BOOKINGS` dead action

### Block 2: Infrastructure + config + middlewares + lifespan
- Move bot factory / single instance / bot setup
- DI container + BotContextMiddleware
- Throttle TTL, error middleware, logging
- Rewrite `main.py` lifespan

### Block 3: Services
- Portfolio file_id fix + welcome media cache
- Session service (class, injectable)
- Subscription service unchanged API

### Block 4: Presentation (UI kit, keyboards, copy)
- `presentation/ui` screen helpers
- Refined keyboards + texts

### Block 5: Handlers + docs + verify
- Thin handlers
- README / DEPLOY path fixes
- Import + smoke check
