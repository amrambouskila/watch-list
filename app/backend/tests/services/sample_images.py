"""Byte samples for the formats a hero image may and may not be, headers first."""

from __future__ import annotations

from typing import Final

PNG: Final[bytes] = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
JPEG: Final[bytes] = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
GIF87: Final[bytes] = b"GIF87a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
GIF89: Final[bytes] = b"GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00"
WEBP: Final[bytes] = b"RIFF\x1a\x00\x00\x00WEBPVP8L\x0e\x00\x00\x00/\x00\x00\x00\x10\x07\x10\x11\x11\x88\x88\xfe"

SVG_DOCUMENT: Final[bytes] = (
    b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"><script>fetch("/")</script></svg>'
)
SVG_BARE: Final[bytes] = b'<svg xmlns="http://www.w3.org/2000/svg" width="8" height="8"></svg>'
HTML_PAGE: Final[bytes] = b"<!doctype html><html><body>Not an image at all.</body></html>"
RIFF_AUDIO: Final[bytes] = b"RIFF\x24\x00\x00\x00WAVEfmt \x10\x00\x00\x00"
TRUNCATED_PNG: Final[bytes] = b"\x89PNG\r\n"
