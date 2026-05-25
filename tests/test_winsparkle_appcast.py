from __future__ import annotations

import base64
from pathlib import Path
from xml.etree import ElementTree as ET

from cryptography.hazmat.primitives.asymmetric import ed25519
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption

from scripts.generate_winsparkle_appcast import SPARKLE_NS, main


def test_generate_winsparkle_appcast_signs_artifact(tmp_path: Path):
    artifact = tmp_path / "FoxPort-v1.2.3-windows-x64.zip"
    artifact.write_bytes(b"fake zip bytes")
    private_key = ed25519.Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.PKCS8,
        NoEncryption(),
    )
    encoded_key = base64.b64encode(private_pem).decode("ascii")
    out = tmp_path / "appcast.xml"

    rc = main([
        "--artifact", str(artifact),
        "--version", "1.2.3",
        "--download-url", "https://github.com/SysAdminDoc/FoxPort/releases/download/v1.2.3/FoxPort-v1.2.3-windows-x64.zip",
        "--release-notes-url", "https://github.com/SysAdminDoc/FoxPort/releases/tag/v1.2.3",
        "--private-key-base64", encoded_key,
        "--output", str(out),
    ])

    assert rc == 0
    root = ET.fromstring(out.read_bytes())
    enclosure = root.find("./channel/item/enclosure")
    assert enclosure is not None
    assert enclosure.attrib["length"] == str(len(b"fake zip bytes"))
    assert enclosure.attrib["type"] == "application/zip"
    assert enclosure.attrib[f"{{{SPARKLE_NS}}}version"] == "1.2.3"
    assert enclosure.attrib[f"{{{SPARKLE_NS}}}shortVersionString"] == "1.2.3"
    assert enclosure.attrib[f"{{{SPARKLE_NS}}}os"] == "windows"

    signature = base64.b64decode(enclosure.attrib[f"{{{SPARKLE_NS}}}edSignature"])
    public_key = private_key.public_key()
    public_key.verify(signature, artifact.read_bytes())
