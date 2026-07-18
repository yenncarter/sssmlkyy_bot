"""Portfolio images with in-memory cache."""

from pathlib import Path

from aiogram.types import FSInputFile

from config.constants import PORTFOLIO_EXTENSIONS
from config.settings import settings


class PortfolioService:
    """Load portfolio images and cache Telegram file_id for fast swipe."""

    def __init__(self, portfolio_dir: Path | None = None) -> None:
        self._dir = portfolio_dir or settings.portfolio_dir
        self._images: list[Path] | None = None
        self._file_ids: dict[int, str] = {}

    def _load_images(self) -> list[Path]:
        if self._images is not None:
            return self._images

        if not self._dir.exists():
            self._dir.mkdir(parents=True, exist_ok=True)
            self._images = []
            return self._images

        self._images = [
            path
            for path in sorted(self._dir.iterdir())
            if path.is_file() and path.suffix.lower() in PORTFOLIO_EXTENSIONS
        ]
        return self._images

    def get_all_images(self) -> list[Path]:
        """Return sorted image paths."""
        return list(self._load_images())

    def get_image_at(self, index: int) -> tuple[Path | None, int, int]:
        """Get image by index."""
        images = self._load_images()
        total = len(images)
        if total == 0:
            return None, 0, 0
        index = max(0, min(index, total - 1))
        return images[index], index, total

    def get_media(self, index: int) -> str | FSInputFile:
        """Return cached file_id or local file."""
        if index in self._file_ids:
            return self._file_ids[index]
        path, index, _ = self.get_image_at(index)
        if path is None:
            raise ValueError("No image at index")
        return FSInputFile(path)

    def remember_file_id(self, index: int, file_id: str) -> None:
        """Cache uploaded file_id for instant re-use."""
        self._file_ids[index] = file_id

    @property
    def has_images(self) -> bool:
        return bool(self._load_images())

    @property
    def count(self) -> int:
        return len(self._load_images())
