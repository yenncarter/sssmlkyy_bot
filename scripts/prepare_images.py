"""Compress welcome cover (and oversized portfolio shots) for Telegram."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMAGES = ROOT / "images"
WELCOME_CANDIDATES = (
    IMAGES / "welcome" / "SS.JPG",
    IMAGES / "welcome" / "SS.jpg",
    IMAGES / "welcome" / "cover.png",
    IMAGES / "welcome" / "cover.jpg",
)
WELCOME_DST = IMAGES / "welcome" / "cover.jpg"
PORTFOLIO_DIR = IMAGES / "portfolio"
MAX_BYTES = 4_500_000


def compress(src: Path, dst: Path, max_side: int = 1600, quality: int = 82) -> None:
    img = Image.open(src)
    img = img.convert("RGB")
    w, h = img.size
    scale = min(1.0, max_side / max(w, h))
    if scale < 1:
        img = img.resize((int(w * scale), int(h * scale)), Image.Resampling.LANCZOS)
    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst, "JPEG", quality=quality, optimize=True)
    print(
        f"{src.name} {src.stat().st_size // 1024}KB -> "
        f"{dst.name} {dst.stat().st_size // 1024}KB {img.size}"
    )


def main() -> None:
    src = next((p for p in WELCOME_CANDIDATES if p.exists()), None)
    if src is None:
        print("No welcome source found in images/welcome/")
    else:
        compress(src, WELCOME_DST)

    if not PORTFOLIO_DIR.exists():
        return
    for path in sorted(PORTFOLIO_DIR.iterdir()):
        if path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        if path.stat().st_size <= MAX_BYTES:
            print(f"ok {path.name} {path.stat().st_size // 1024}KB")
            continue
        tmp = path.with_name(path.stem + "_tmp.jpg")
        compress(path, tmp)
        out = path if path.suffix.lower() in {".jpg", ".jpeg"} else path.with_suffix(".jpg")
        if out != path:
            path.unlink(missing_ok=True)
            tmp.rename(out)
        else:
            tmp.replace(path)


if __name__ == "__main__":
    main()
