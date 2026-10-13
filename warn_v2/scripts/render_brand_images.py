"""Regenerate the static brand images in frontend/public/ from warn_v2.api.og_cards.

    python -m warn_v2.scripts.render_brand_images

Writes og-image.png (the site-wide 1200x630 share card) and
apple-touch-icon.png (180x180), so they always match the live mark and the
per-state cards served by /og/states/{code}.png.
"""
from __future__ import annotations

from pathlib import Path

from warn_v2.api import og_cards

_PUBLIC = Path(__file__).parent.parent.parent / "frontend" / "public"


def main() -> None:
    (_PUBLIC / "og-image.png").write_bytes(og_cards.render_default_card())
    (_PUBLIC / "apple-touch-icon.png").write_bytes(og_cards.render_touch_icon())
    print(f"Wrote og-image.png and apple-touch-icon.png to {_PUBLIC}")


if __name__ == "__main__":
    main()
