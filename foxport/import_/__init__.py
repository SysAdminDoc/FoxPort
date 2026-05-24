"""Source-side adapters for non-browser bookmark exports.

ArchiveBox-style parsers that take a dropped file (Pocket JSON, Pinboard
JSON, OPML, Netscape HTML) and emit a flat list of bookmark entries the
forward bookmarks migrator can ingest.
"""

from foxport.import_.adapters import (
    BookmarkImport,
    detect_format,
    parse_file,
)

__all__ = ["BookmarkImport", "detect_format", "parse_file"]
