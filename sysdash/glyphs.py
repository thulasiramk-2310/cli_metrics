"""Drawing characters, with an ASCII fallback for terminals that cannot encode them.

A minimal Linux install, a bare virtual console, a slim Docker image or an SSH
session with LANG unset leaves Python choosing ASCII for stdout. Printing the
block characters there raises UnicodeEncodeError and takes the whole dashboard
down before it draws a single frame.

Rich substitutes ASCII for its own box borders when it detects this, but the
bars, the trend plot and the arrow hints are drawn by hand here, so they need
the same treatment. Picking a set the terminal can actually encode keeps the
dashboard usable instead of crashing, at the cost of blockier bars.
"""

import sys

UNICODE_GLYPHS = {
    "full": "█",      # full block, the filled part of a bar
    "empty": "░",     # light shade, the unfilled part
    "dot": "·",       # middle dot, the trend plot's background field
    "ellipsis": "…",
    "up": "↑",
    "down": "↓",
}

ASCII_GLYPHS = {
    "full": "#",
    "empty": "-",
    "dot": ".",
    "ellipsis": "~",
    "up": "^",
    "down": "v",
}


def supports_unicode(stream=None) -> bool:
    """Whether the stream's encoding can represent every glyph we draw.

    A stream with no encoding attribute at all (an io.StringIO in a test, a
    pipe opened in binary) is treated as capable: nothing is going to a
    terminal, so there is no encoder to fail.
    """
    if stream is None:
        stream = sys.stdout
    encoding = getattr(stream, "encoding", None)
    if not encoding:
        return True
    try:
        "".join(UNICODE_GLYPHS.values()).encode(encoding)
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def for_stream(stream=None) -> dict:
    """The glyph set that ``stream`` can print without raising."""
    return UNICODE_GLYPHS if supports_unicode(stream) else ASCII_GLYPHS


def enable_utf8(stream=None) -> bool:
    """Try to switch ``stream`` to UTF-8, reporting whether the glyphs now fit.

    Call this from an entry point, never from library code: it mutates the
    process's stdout.

    Almost every Linux terminal in use can display UTF-8. What is missing on a
    slim container image or an SSH session is the locale telling Python so, and
    Python then picks ASCII and raises on the first bar. Setting the encoding
    directly is what PYTHONIOENCODING=utf-8 would have done, which is the
    workaround rich itself suggests when this happens.

    If the encoding cannot be changed, fall back to replacing unencodable
    characters rather than raising. That covers the parts we do not draw
    ourselves, such as the ellipsis rich inserts when it truncates a cell.
    """
    if stream is None:
        stream = sys.stdout
    if supports_unicode(stream):
        return True

    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is None:
        return False

    try:
        reconfigure(encoding="utf-8")
        return True
    except (OSError, LookupError, ValueError):
        pass

    try:
        reconfigure(errors="replace")
    except (OSError, LookupError, ValueError):
        pass
    return False
