"""Bundled data files (curated extension map, etc.)."""

from __future__ import annotations

from importlib import resources
from pathlib import Path


def data_file(name: str) -> Path:
    """Return the on-disk path of a bundled data file under foxport/data/."""
    return Path(__file__).resolve().parent / name
