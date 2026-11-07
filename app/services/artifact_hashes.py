"""Portable fingerprints for tracked UTF-8 text artifacts across Windows/Linux."""

import hashlib
from pathlib import Path


def text_sha256(path):
    return hashlib.sha256(Path(path).read_text(encoding='utf-8').encode('utf-8')).hexdigest()
