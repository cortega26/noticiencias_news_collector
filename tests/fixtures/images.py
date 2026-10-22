"""Small decoded raster fixtures for upload and publication boundary tests."""

from __future__ import annotations

from io import BytesIO

from PIL import Image


def raster_bytes(format_name: str = "PNG", *, color: str = "green") -> bytes:
    output = BytesIO()
    Image.new("RGB", (24, 16), color).save(output, format=format_name)
    return output.getvalue()
