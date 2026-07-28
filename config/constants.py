"""Application-wide constants."""

__all__ = [
    "PORTFOLIO_EXTENSIONS",
    "THROTTLE_BURST",
    "THROTTLE_MIN_INTERVAL",
    "THROTTLE_REFILL_SECONDS",
    "THROTTLE_TTL_SECONDS",
]

# Anti-flood, two layers (see middlewares/throttling.py):
# 1. minimum gap between two actions — swallows accidental double taps;
THROTTLE_MIN_INTERVAL: float = 0.35
# 2. token bucket — allows a normal navigation burst, then caps the sustained
#    rate so one user cannot keep the single-writer SQLite connection busy.
THROTTLE_BURST: int = 8
THROTTLE_REFILL_SECONDS: float = 1.0

# Drop idle throttle entries after this many seconds
THROTTLE_TTL_SECONDS: float = 600.0

# Portfolio
PORTFOLIO_EXTENSIONS: tuple[str, ...] = (".jpg", ".jpeg", ".png", ".webp")
