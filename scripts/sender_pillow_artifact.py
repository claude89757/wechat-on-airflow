"""Stage the single approved Pillow wheel without using a host package catalog."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import os
import re
import stat
import struct
import sys
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path

WHEEL_NAME = "pillow-13.0.0-cp311-cp311-linux_armv7l.whl"
WHEEL_URL = "https://www.piwheels.org/simple/pillow/" + WHEEL_NAME
WHEEL_SHA256 = "49eb06898ec42888e47c1cf1a97cb64b29af2b5d2773be60db1b1ecbbf92c3a6"
WHEEL_SIZE = 1_317_640
WHEEL_TAG = "cp311-cp311-linux_armv7l"
PILLOW_REQUIREMENT = "Pillow==13.0.0"
FAILURE_KINDS = frozenset(
    {
        "lock_mismatch",
        "missing",
        "not_regular",
        "size_mismatch",
        "copy_failed",
        "sha256_mismatch",
        "metadata_mismatch",
        "tag_mismatch",
        "tag_inventory_failed",
        "download_failed",
        "unclassified",
    }
)


class ArtifactError(RuntimeError):
    """Only fixed, non-sensitive failure kinds may leave the staging boundary."""


def verify_lock(lock_text: str) -> None:
    requirements = re.findall(r"(?mi)^\s*pillow\b[^\r\n]*", lock_text)
    if [line.strip() for line in requirements] != [PILLOW_REQUIREMENT]:
        raise ArtifactError("lock_mismatch")


def verify_wheel(path: Path) -> None:
    # The caller owns this private copy. Never hash a public path and install it later.
    with path.open("rb") as wheel:
        data = wheel.read(WHEEL_SIZE + 1)
    if len(data) != WHEEL_SIZE:
        raise ArtifactError("size_mismatch")
    if hashlib.sha256(data).hexdigest() != WHEEL_SHA256:
        raise ArtifactError("sha256_mismatch")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as wheel:
            metadata = BytesParser().parsebytes(wheel.read("pillow-13.0.0.dist-info/METADATA"))
            wheel_metadata = BytesParser().parsebytes(wheel.read("pillow-13.0.0.dist-info/WHEEL"))
        if (
            metadata.get_all("Name") != ["pillow"]
            or metadata.get_all("Version") != ["13.0.0"]
            or metadata.get_all("Requires-Python") != [">=3.11"]
            or wheel_metadata.get_all("Wheel-Version") != ["1.0"]
            or wheel_metadata.get_all("Tag") != [WHEEL_TAG]
        ):
            raise ArtifactError("metadata_mismatch")
    except (KeyError, ValueError, zipfile.BadZipFile):
        raise ArtifactError("metadata_mismatch") from None


class FixedSourceRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A fixed HTTPS source must never redirect to an arbitrary host or plain HTTP.
        if newurl != WHEEL_URL:
            raise ArtifactError("download_failed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_wheel(path: Path, lock_text: str) -> None:
    verify_lock(lock_text)
    try:
        opener = urllib.request.build_opener(FixedSourceRedirect())
        with opener.open(WHEEL_URL, timeout=60) as response:
            data = response.read(WHEEL_SIZE + 1)
        if len(data) != WHEEL_SIZE:
            raise ArtifactError("size_mismatch")
        with path.open("xb") as wheel:
            wheel.write(data)
        verify_wheel(path)
    except ArtifactError:
        raise
    except Exception:
        raise ArtifactError("download_failed") from None


def arm32_tags() -> set[str] | None:
    if struct.calcsize("P") * 8 != 32:
        return None
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            from pip._internal.utils.compatibility_tags import get_supported

            supported = get_supported()
            if not any(tag.platform.endswith(("_armv6l", "_armv7l")) for tag in supported):
                return None
            return {str(tag) for tag in supported}
    except (Exception, SystemExit):
        raise ArtifactError("tag_inventory_failed") from None


def stage_wheel(lock: Path, artifact: str, directory: Path) -> bool:
    tags = arm32_tags()
    if tags is None:
        return False
    verify_lock(lock.read_text())
    if not artifact:
        raise ArtifactError("missing")
    try:
        # /tmp uploads are untrusted until copied. Reject links/devices/FIFOs and
        # bound the read even if another process changes the source while copying.
        descriptor = os.open(artifact, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            source_stat = os.fstat(source.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                raise ArtifactError("not_regular")
            if source_stat.st_size != WHEEL_SIZE:
                raise ArtifactError("size_mismatch")
            directory.mkdir(mode=0o700)
            private_wheel = directory / WHEEL_NAME
            with private_wheel.open("xb") as destination:
                destination.write(source.read(WHEEL_SIZE + 1))
            private_wheel.chmod(0o600)
        verify_wheel(private_wheel)
    except FileNotFoundError:
        raise ArtifactError("missing") from None
    except OSError:
        raise ArtifactError("copy_failed") from None
    if WHEEL_TAG not in tags:
        raise ArtifactError("tag_mismatch")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        verified = stage_wheel(args.lock, args.artifact, args.directory)
    except Exception as exc:
        kind = (
            str(exc)
            if isinstance(exc, ArtifactError) and str(exc) in FAILURE_KINDS
            else "unclassified"
        )
        print(kind, file=sys.stderr)
        raise SystemExit(1) from None
    print("true" if verified else "false")


if __name__ == "__main__":
    main()
