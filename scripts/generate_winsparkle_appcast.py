"""Generate a signed WinSparkle appcast for a release artifact.

WinSparkle expects the enclosure to carry a base64 Ed25519 signature in
``sparkle:edSignature`` plus the artifact length. The private key is supplied
at release time; no signing material is checked into the repository.
"""

from __future__ import annotations

import argparse
import base64
import sys
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import load_pem_private_key


SPARKLE_NS = "http://www.andymatuschak.org/xml-namespaces/sparkle"
ET.register_namespace("sparkle", SPARKLE_NS)


def load_private_key(*, path: Path | None, raw_base64: str | None) -> ed25519.Ed25519PrivateKey:
    if path is not None:
        payload = path.read_bytes()
        key = load_pem_private_key(payload, password=None)
        if not isinstance(key, ed25519.Ed25519PrivateKey):
            raise ValueError("private key is not an Ed25519 key")
        return key
    if raw_base64:
        raw = base64.b64decode(raw_base64.strip())
        if len(raw) == 32:
            return ed25519.Ed25519PrivateKey.from_private_bytes(raw)
        key = load_pem_private_key(raw, password=None)
        if not isinstance(key, ed25519.Ed25519PrivateKey):
            raise ValueError("decoded private key is not an Ed25519 key")
        return key
    raise ValueError("pass --private-key or --private-key-base64")


def artifact_signature(artifact: Path, key: ed25519.Ed25519PrivateKey) -> str:
    return base64.b64encode(key.sign(artifact.read_bytes())).decode("ascii")


def build_appcast_xml(
    *,
    title: str,
    version: str,
    artifact: Path,
    download_url: str,
    release_notes_url: str,
    signature: str,
    published: datetime,
) -> bytes:
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = release_notes_url
    ET.SubElement(channel, "description").text = "Most recent FoxPort Windows release."
    ET.SubElement(channel, "language").text = "en"

    item = ET.SubElement(channel, "item")
    ET.SubElement(item, "title").text = f"{title} {version}"
    ET.SubElement(item, "pubDate").text = format_datetime(published, usegmt=True)
    ET.SubElement(item, "link").text = release_notes_url
    ET.SubElement(item, f"{{{SPARKLE_NS}}}version").text = version
    ET.SubElement(item, f"{{{SPARKLE_NS}}}shortVersionString").text = version
    ET.SubElement(
        item,
        "enclosure",
        {
            "url": download_url,
            "length": str(artifact.stat().st_size),
            "type": "application/zip",
            f"{{{SPARKLE_NS}}}version": version,
            f"{{{SPARKLE_NS}}}shortVersionString": version,
            f"{{{SPARKLE_NS}}}os": "windows",
            f"{{{SPARKLE_NS}}}edSignature": signature,
        },
    )
    return ET.tostring(rss, encoding="utf-8", xml_declaration=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a signed WinSparkle appcast.xml")
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--download-url", required=True)
    parser.add_argument("--release-notes-url", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--title", default="FoxPort")
    parser.add_argument("--private-key", type=Path, default=None)
    parser.add_argument("--private-key-base64", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.artifact.is_file():
        print(f"error: artifact not found: {args.artifact}", file=sys.stderr)
        return 2
    try:
        key = load_private_key(path=args.private_key, raw_base64=args.private_key_base64)
        signature = artifact_signature(args.artifact, key)
        xml = build_appcast_xml(
            title=args.title,
            version=args.version,
            artifact=args.artifact,
            download_url=args.download_url,
            release_notes_url=args.release_notes_url,
            signature=signature,
            published=datetime.now(timezone.utc),
        )
    except Exception as exc:  # noqa: BLE001 - CLI tool should report a short error
        print(f"error: {exc}", file=sys.stderr)
        return 1
    args.output.write_bytes(xml)
    print(f"Wrote signed appcast: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
