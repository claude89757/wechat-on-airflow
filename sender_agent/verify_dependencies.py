"""Credential-free verification of the sender's actually imported image dependency."""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path


def verify(lock_path: Path) -> str:
    import PIL
    from PIL import Image, ImageOps

    if sys.version_info[:2] != (3, 12):
        raise RuntimeError("sender requires Python 3.12")
    pins = [
        line.removeprefix("Pillow==")
        for line in lock_path.read_text().splitlines()
        if line.startswith("Pillow==")
    ]
    if len(pins) != 1 or PIL.__version__ != pins[0]:
        raise RuntimeError("imported Pillow does not match the sender lock")
    if not Path(PIL.__file__).resolve().is_relative_to(Path(sys.prefix).resolve()):
        raise RuntimeError("Pillow must be installed inside the sender interpreter prefix")
    original = Image.new("RGB", (12, 12), (0, 255, 0))
    encoded = BytesIO()
    original.save(encoded, format="PNG")
    encoded.seek(0)
    with Image.open(encoded) as screenshot:
        screenshot.load()
        crop = screenshot.convert("RGB").crop((1, 1, 11, 11))
        resized = crop.resize((20, 20), Image.Resampling.LANCZOS)
        grayscale = ImageOps.grayscale(resized)
        threshold = grayscale.point(lambda value: 255 if value > 128 else 0)
        if threshold.size != (20, 20):
            raise RuntimeError("Pillow OCR preprocessing regression")
        output = BytesIO()
        resized.save(output, format="PNG")
        output.seek(0)
        with Image.open(output) as decoded:
            decoded.load()
            if decoded.size != (20, 20) or decoded.getpixel((0, 0)) != (0, 255, 0):
                raise RuntimeError("Pillow screenshot processing regression")
    return PIL.__version__


if __name__ == "__main__":
    print(f"sender dependency verification: Pillow={verify(Path(sys.argv[1]))} ok")
