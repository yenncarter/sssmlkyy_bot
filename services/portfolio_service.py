"""Portfolio images with Telegram file_id cache."""

from __future__ import annotations

import random
from hashlib import sha256
from pathlib import Path

from aiogram.types import FSInputFile

from config.constants import PORTFOLIO_EXTENSIONS
from services.media_cache import MediaCache


class PortfolioService:
    """Load portfolio images and cache Telegram file_id for fast swipe."""

    def __init__(
        self,
        portfolio_dir: Path,
        media_cache: MediaCache | None = None,
    ) -> None:
        self._dir = portfolio_dir
        self._cache = media_cache or MediaCache()
        self._images: list[Path] | None = None

    def _cache_key(self, path: Path) -> str:
        # Key by filename so reshuffles / renames of order don't mix file_ids
        return f"portfolio:{path.name.lower()}"

    def reload(self) -> None:
        """Invalidate local image list (keeps file_id cache)."""
        self._images = None

    @staticmethod
    def _ordered_images(paths: list[Path]) -> list[Path]:
        """Keep 01.* first; shuffle the rest stably for a given file set."""
        lead = [p for p in paths if p.stem.lower() == "01"]
        rest = [p for p in paths if p.stem.lower() != "01"]
        lead.sort(key=lambda p: p.name.lower())
        # Same set of filenames → same random order across restarts
        seed = sha256(
            "\n".join(sorted(p.name.lower() for p in rest)).encode("utf-8")
        ).hexdigest()
        rng = random.Random(seed)
        rng.shuffle(rest)
        return lead + rest

    def _load_images(self) -> list[Path]:
        if self._images is not None:
            return self._images

        if not self._dir.exists():
            self._dir.mkdir(parents=True, exist_ok=True)
            self._images = []
            return self._images

        found = [
            path
            for path in self._dir.iterdir()
            if path.is_file() and path.suffix.lower() in PORTFOLIO_EXTENSIONS
        ]
        self._images = self._ordered_images(found)
        return self._images

    def get_image_at(self, index: int) -> tuple[Path | None, int, int]:
        """Get image path by index, clamped to bounds."""
        images = self._load_images()
        total = len(images)
        if total == 0:
            return None, 0, 0
        index = max(0, min(index, total - 1))
        return images[index], index, total

    def get_media(self, index: int) -> str | FSInputFile:
        """Return cached file_id or local file for upload."""
        path, index, _ = self.get_image_at(index)
        if path is None:
            raise ValueError("No image at index")
        cached = self._cache.get(self._cache_key(path))
        if cached:
            return cached
        return FSInputFile(path)

    async def remember_file_id(self, index: int, file_id: str) -> None:
        """Persist the uploaded file_id so restarts don't re-upload the photo."""
        path, _, _ = self.get_image_at(index)
        if path is None:
            return
        await self._cache.remember(self._cache_key(path), file_id)

    @property
    def has_images(self) -> bool:
        return bool(self._load_images())

    @property
    def count(self) -> int:
        return len(self._load_images())
