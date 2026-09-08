"""Render the README's dashboard screenshot from the running dashboard.

The README used to carry no image of the platform at all. This captures the
real thing: the browser dashboard under ``dashboard/`` rendering the twin in
``instances/default/digital_twin/`` -- the model SHA-256, the scenario, the
grid-health figures and the ontology counts are all read from generated
artifacts, so the screenshot cannot drift from what the code produces without
the numbers visibly changing.

Committed like ``render_hero_network.py``'s output, so the README does not
depend on a local build.

**Prerequisites**, none of which are project dependencies:

1. The twin base must exist (it is generated, never committed)::

       uv run python gridalyn/projects/workflows/scripts/export_digital_twin_base.py

2. The dashboard dev server must be running, because it is what serves the
   twin's parquet files to the browser::

       cd dashboard && npm run dev

3. Playwright, in a throwaway environment -- it is deliberately NOT added to
   ``pyproject.toml``, since nothing in the SDK needs a browser::

       uv venv /tmp/shotenv && uv pip install --python /tmp/shotenv/bin/python playwright
       /tmp/shotenv/bin/python -m playwright install chromium

Then::

    /tmp/shotenv/bin/python tools/render_dashboard_shot.py

WebGL runs through SwiftShader so this works on a headless machine with no GPU.
That is slow: the waits below are generous on purpose, because deck.gl needs
several real frames and DuckDB-WASM has to parse the parquet before the map has
anything to draw. A short wait yields a black canvas that still screenshots
"successfully".
"""

from __future__ import annotations

import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = REPO_ROOT / "docs" / "assets" / "dashboard-twin.jpg"
DEFAULT_URL = "http://localhost:5173/"

# Wider than GitHub renders a README image, so it stays sharp on HiDPI.
WIDTH = 1280
HEIGHT = 800
SCALE = 2

# SwiftShader needs real time, not virtual time: headless Chromium's
# --virtual-time-budget advances a fake clock and screenshots a canvas that
# never received a painted frame.
CANVAS_TIMEOUT_MS = 60_000
RENDER_WAIT_MS = 30_000

SWIFTSHADER_ARGS = [
    "--use-gl=angle",
    "--use-angle=swiftshader",
    "--enable-unsafe-swiftshader",
    "--no-sandbox",
    "--disable-dev-shm-usage",
]


def render(url: str, out: Path, quality: int) -> Path:
    """Screenshot the dashboard and write an optimized JPEG.

    Args:
        url: Address of the running dashboard dev server.
        out: Destination image path.
        quality: JPEG quality. 92 with no chroma subsampling keeps the
            sidebar's small text legible while staying about a third the size
            of the equivalent PNG.

    Returns:
        The path written.

    Raises:
        SystemExit: If Playwright is not installed, with the install command.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError:  # pragma: no cover - operator tooling
        raise SystemExit(
            "playwright is not installed. It is not a project dependency; see "
            "this module's docstring for the throwaway-environment recipe."
        ) from None
    from io import BytesIO

    from PIL import Image

    with sync_playwright() as play:
        browser = play.chromium.launch(args=SWIFTSHADER_ARGS)
        page = browser.new_context(
            viewport={"width": WIDTH, "height": HEIGHT},
            device_scale_factor=SCALE,
        ).new_page()
        page.goto(url, wait_until="networkidle", timeout=90_000)
        page.wait_for_selector("canvas", timeout=CANVAS_TIMEOUT_MS)
        page.wait_for_timeout(RENDER_WAIT_MS)
        shot = page.screenshot()
        browser.close()

    image = Image.open(BytesIO(shot)).convert("RGB")
    image = image.resize((WIDTH, round(image.height * WIDTH / image.width)))
    out.parent.mkdir(parents=True, exist_ok=True)
    image.save(out, "JPEG", quality=quality, subsampling=0, optimize=True)
    return out


def main() -> int:
    """Parse arguments and render the screenshot.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL, help="Dashboard dev server URL.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="Output image.")
    parser.add_argument("--quality", type=int, default=92, help="JPEG quality.")
    args = parser.parse_args()
    written = render(args.url, args.out, args.quality)
    print(f"wrote {written.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
