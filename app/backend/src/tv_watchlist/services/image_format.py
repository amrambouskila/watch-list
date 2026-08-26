"""What a downloaded image actually is, read from its own leading bytes."""

from __future__ import annotations

from typing import Final

PNG_SUFFIX: Final[str] = ".png"
JPEG_SUFFIX: Final[str] = ".jpg"
GIF_SUFFIX: Final[str] = ".gif"
WEBP_SUFFIX: Final[str] = ".webp"

PNG_MAGIC: Final[bytes] = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC: Final[bytes] = b"\xff\xd8\xff"
GIF87_MAGIC: Final[bytes] = b"GIF87a"
GIF89_MAGIC: Final[bytes] = b"GIF89a"
RIFF_MAGIC: Final[bytes] = b"RIFF"
WEBP_FORM_TYPE: Final[bytes] = b"WEBP"
# A RIFF container names its form type after the four magic bytes and the four length bytes.
WEBP_FORM_OFFSET: Final[int] = 8

_SUFFIX_BY_MAGIC: Final[tuple[tuple[bytes, str], ...]] = (
    (PNG_MAGIC, PNG_SUFFIX),
    (JPEG_MAGIC, JPEG_SUFFIX),
    (GIF87_MAGIC, GIF_SUFFIX),
    (GIF89_MAGIC, GIF_SUFFIX),
)


def image_suffix(data: bytes) -> str | None:
    """The suffix these bytes are, or None for anything but an accepted raster image."""
    # SVG is absent on purpose: it is scriptable XML, and this runs on bytes the open web handed
    # over on a model's say-so.
    form_type = data[WEBP_FORM_OFFSET : WEBP_FORM_OFFSET + len(WEBP_FORM_TYPE)]
    if data.startswith(RIFF_MAGIC) and form_type == WEBP_FORM_TYPE:
        return WEBP_SUFFIX
    return next((suffix for magic, suffix in _SUFFIX_BY_MAGIC if data.startswith(magic)), None)
