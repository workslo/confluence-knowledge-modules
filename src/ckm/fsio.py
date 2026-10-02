"""Filesystem writes that are atomic, idempotent, and tolerant of Windows/OneDrive locks."""

import hashlib
import os
import shutil
import tempfile
import time
from pathlib import Path

_LOCK_RETRIES = 3
_LOCK_DELAY_S = 0.5


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def write_text(path: Path, text: str, *, dry_run: bool = False) -> bool:
    """Write UTF-8 text with LF endings. Returns True when the file changed."""
    return write_bytes(path, text.encode("utf-8"), dry_run=dry_run)


def write_bytes(path: Path, data: bytes, *, dry_run: bool = False) -> bool:
    """Atomic write (temp file + replace). Skips the write when content is identical."""
    if path.is_file() and path.read_bytes() == data:
        return False
    if dry_run:
        return True
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        _replace_with_retry(Path(tmp), path)
    finally:
        Path(tmp).unlink(missing_ok=True)
    return True


def copy_file(src: Path, dst: Path, *, dry_run: bool = False) -> bool:
    """Copy when the destination is missing or differs byte-for-byte."""
    return write_bytes(dst, src.read_bytes(), dry_run=dry_run)


def move_file(src: Path, dst: Path, *, dry_run: bool = False) -> None:
    if dry_run:
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))


def _replace_with_retry(tmp: Path, target: Path) -> None:
    for attempt in range(_LOCK_RETRIES):
        try:
            os.replace(tmp, target)
            return
        except PermissionError:
            if attempt == _LOCK_RETRIES - 1:
                raise
            time.sleep(_LOCK_DELAY_S)
