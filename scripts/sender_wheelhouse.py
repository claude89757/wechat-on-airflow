"""Stage the exact approved ARM32 CPython 3.11 lock as verified offline wheels."""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import stat
import struct
import sys
import tempfile
import urllib.parse
import urllib.request
import zipfile
from email.parser import BytesParser
from pathlib import Path

from pip._vendor.packaging.requirements import Requirement
from pip._vendor.packaging.specifiers import SpecifierSet
from pip._vendor.packaging.tags import parse_tag
from pip._vendor.packaging.utils import parse_wheel_filename

ARCHIVE_NAME = "sender-arm32-wheelhouse.zip"
MANIFEST_PATH = "config/sender-arm32-wheelhouse.json"
TARGET = {"implementation": "cp", "python": "3.11", "abi": "cp311", "platform": "linux_armv7l"}
MAX_WHEEL_SIZE = 32 * 1024 * 1024
MAX_TOTAL_SIZE = 64 * 1024 * 1024
PIN_PATTERN = re.compile(r"([A-Za-z0-9][A-Za-z0-9_.-]{0,79})==([A-Za-z0-9][A-Za-z0-9_.+!-]{0,39})")
FAILURE_KINDS = frozenset(
    {
        "lock_mismatch",
        "manifest_invalid",
        "archive_invalid",
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


def normalized_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()


def read_manifest(manifest_text: str, lock_text: str) -> list[dict]:
    pins = [line.strip() for line in lock_text.splitlines() if line.strip()]
    if not 1 <= len(pins) <= 64 or any(PIN_PATTERN.fullmatch(pin) is None for pin in pins):
        raise ArtifactError("lock_mismatch")
    names = [normalized_name(pin.split("==")[0]) for pin in pins]
    if len(set(names)) != len(names):
        raise ArtifactError("lock_mismatch")
    try:
        if len(manifest_text) > 128 * 1024:
            raise ValueError
        manifest = json.loads(manifest_text)
        if (
            set(manifest) != {"schema_version", "target", "wheels"}
            or type(manifest["schema_version"]) is not int
            or manifest["schema_version"] != 1
            or manifest["target"] != TARGET
        ):
            raise ValueError
        wheels = manifest["wheels"]
        if not isinstance(wheels, list) or len(wheels) != len(pins):
            raise ValueError
        filenames, requirements = set(), set()
        total_size = 0
        for wheel in wheels:
            if set(wheel) != {"requirement", "filename", "url", "sha256", "size", "tags"}:
                raise ValueError
            pin, filename = wheel["requirement"], wheel["filename"]
            if (
                not isinstance(pin, str)
                or pin not in pins
                or pin in requirements
                or not isinstance(filename, str)
                or re.fullmatch(r"[A-Za-z0-9_.+-]{1,200}\.whl", filename) is None
                or filename in filenames
            ):
                raise ValueError
            name, version = pin.split("==")
            parsed_name, parsed_version, _, parsed_tags = parse_wheel_filename(filename)
            tags = wheel["tags"]
            if (
                not isinstance(tags, list)
                or not 1 <= len(tags) <= 32
                or any(
                    not isinstance(tag, str)
                    or re.fullmatch(r"[A-Za-z0-9_]+-[A-Za-z0-9_]+-[A-Za-z0-9_]+", tag) is None
                    for tag in tags
                )
                or len(set(tags)) != len(tags)
            ):
                raise ValueError
            if (
                normalized_name(name) != parsed_name
                or str(parsed_version) != version
                or {str(tag) for tag in parsed_tags} != set(tags)
            ):
                raise ValueError
            if (
                type(wheel["size"]) is not int
                or not 0 < wheel["size"] <= MAX_WHEEL_SIZE
                or not isinstance(wheel["sha256"], str)
                or re.fullmatch(r"[0-9a-f]{64}", wheel["sha256"]) is None
            ):
                raise ValueError
            url = wheel["url"]
            if not isinstance(url, str) or len(url) > 2048:
                raise ValueError
            source = urllib.parse.urlsplit(url)
            if (
                source.scheme != "https"
                or source.username is not None
                or source.password is not None
                or source.port is not None
                or source.query
                or source.fragment
                or urllib.parse.unquote(source.path.rsplit("/", 1)[-1]) != filename
            ):
                raise ValueError
            if source.hostname != "files.pythonhosted.org" and not (
                pin == "Pillow==13.0.0"
                and url
                == "https://www.piwheels.org/simple/pillow/pillow-13.0.0-cp311-cp311-linux_armv7l.whl"
            ):
                raise ValueError
            total_size += wheel["size"]
            filenames.add(filename)
            requirements.add(pin)
        if requirements != set(pins) or total_size > MAX_TOTAL_SIZE:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ArtifactError("manifest_invalid") from None
    return wheels


def verify_wheel(path: Path, record: dict, native_tags: set[str] | None = None) -> None:
    # The caller owns this private copy. Never hash a public path and install it later.
    with path.open("rb") as wheel:
        data = wheel.read(record["size"] + 1)
    if len(data) != record["size"]:
        raise ArtifactError("size_mismatch")
    if hashlib.sha256(data).hexdigest() != record["sha256"]:
        raise ArtifactError("sha256_mismatch")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as wheel:
            metadata_paths = [
                name for name in wheel.namelist() if name.endswith(".dist-info/METADATA")
            ]
            if len(metadata_paths) != 1 or metadata_paths[0].count("/") != 1:
                raise ValueError
            metadata_path = metadata_paths[0]
            wheel_path = metadata_path.rsplit("/", 1)[0] + "/WHEEL"
            if (
                wheel.getinfo(metadata_path).file_size > 256 * 1024
                or wheel.getinfo(wheel_path).file_size > 16 * 1024
            ):
                raise ValueError
            metadata = BytesParser().parsebytes(wheel.read(metadata_path))
            wheel_metadata = BytesParser().parsebytes(wheel.read(wheel_path))
        name, version = record["requirement"].split("==")
        tags = {str(tag) for value in wheel_metadata.get_all("Tag", []) for tag in parse_tag(value)}
        if (
            len(metadata.get_all("Name", [])) != 1
            or normalized_name(metadata["Name"]) != normalized_name(name)
            or metadata.get_all("Version") != [version]
            or wheel_metadata.get_all("Wheel-Version") != ["1.0"]
            or tags != set(record["tags"])
        ):
            raise ValueError
        # --no-index does not prevent direct URL requirements. The fixed approved
        # wheels contain none, and each host independently verifies that invariant.
        if any(
            Requirement(value).url is not None for value in metadata.get_all("Requires-Dist", [])
        ):
            raise ValueError
        if native_tags is not None:
            if not tags.intersection(native_tags):
                raise ArtifactError("tag_mismatch")
            python = ".".join(map(str, sys.version_info[:3]))
            if any(
                not SpecifierSet(value).contains(python)
                for value in metadata.get_all("Requires-Python", [])
            ):
                raise ArtifactError("tag_mismatch")
    except (KeyError, ValueError, zipfile.BadZipFile):
        raise ArtifactError("metadata_mismatch") from None


class FixedSourceRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if newurl != req.full_url:
            raise ArtifactError("download_failed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download_wheelhouse(path: Path, lock_text: str, manifest_text: str) -> None:
    records = read_manifest(manifest_text, lock_text)
    try:
        opener = urllib.request.build_opener(FixedSourceRedirect())
        with tempfile.TemporaryDirectory(prefix=".sender-wheels-", dir=path.parent) as directory:
            with zipfile.ZipFile(
                path, "x", compression=zipfile.ZIP_STORED, allowZip64=False
            ) as archive:
                for record in records:
                    with opener.open(record["url"], timeout=60) as response:
                        data = response.read(record["size"] + 1)
                    if len(data) != record["size"]:
                        raise ArtifactError("size_mismatch")
                    wheel = Path(directory) / record["filename"]
                    with wheel.open("xb") as output:
                        output.write(data)
                    verify_wheel(wheel, record)
                    archive.write(wheel, record["filename"])
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
            tags = {str(tag) for tag in supported}
    except (Exception, SystemExit):
        raise ArtifactError("tag_inventory_failed") from None
    if sys.implementation.name != "cpython" or sys.version_info[:2] != (3, 11):
        raise ArtifactError("tag_mismatch")
    return tags


def verify_archive(path: Path, records: list[dict], directory: Path, tags: set[str]) -> None:
    # Check the small, non-ZIP64 central directory before ZipFile allocates entries.
    with path.open("rb") as source:
        source.seek(-22, os.SEEK_END)
        end = source.read(22)
    signature, disk, start_disk, count, total, size, offset, comment = struct.unpack(
        "<4s4H2LH", end
    )
    expected_directory_size = sum(
        46 + len(record["filename"].encode("utf-8")) for record in records
    )
    if (
        signature != b"PK\x05\x06"
        or disk
        or start_disk
        or comment
        or count != len(records)
        or total != count
        or size != expected_directory_size
        or offset + size + 22 != path.stat().st_size
    ):
        raise ArtifactError("archive_invalid")
    expected = {record["filename"]: record for record in records}
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) != len(records) or {entry.filename for entry in entries} != set(expected):
            raise ArtifactError("archive_invalid")
        for entry in entries:
            record = expected[entry.filename]
            if (
                entry.is_dir()
                or stat.S_IFMT(entry.external_attr >> 16) != stat.S_IFREG
                or entry.compress_type != zipfile.ZIP_STORED
                or entry.flag_bits
                or entry.extra
                or entry.comment
                or entry.file_size != record["size"]
                or entry.compress_size != entry.file_size
            ):
                raise ArtifactError("archive_invalid")
        # Never extract arbitrary member paths: only validated manifest basenames.
        for entry in entries:
            record = expected[entry.filename]
            wheel = directory / entry.filename
            with archive.open(entry) as source, wheel.open("xb") as output:
                output.write(source.read(record["size"] + 1))
            wheel.chmod(0o600)
            verify_wheel(wheel, record, tags)


def stage_wheelhouse(lock: Path, manifest: Path, artifact: str, directory: Path) -> bool:
    tags = arm32_tags()
    if tags is None:
        return False
    records = read_manifest(manifest.read_text(), lock.read_text())
    if not artifact:
        raise ArtifactError("missing")
    limit = sum(record["size"] for record in records) + len(records) * 512 + 22
    try:
        descriptor = os.open(artifact, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "rb") as source:
            source_stat = os.fstat(source.fileno())
            if not stat.S_ISREG(source_stat.st_mode):
                raise ArtifactError("not_regular")
            if not 22 <= source_stat.st_size <= limit:
                raise ArtifactError("size_mismatch")
            directory.mkdir(mode=0o700)
            private_archive = directory / ARCHIVE_NAME
            with private_archive.open("xb") as output:
                output.write(source.read(limit + 1))
            private_archive.chmod(0o600)
        if private_archive.stat().st_size > limit:
            raise ArtifactError("size_mismatch")
        verify_archive(private_archive, records, directory, tags)
        private_archive.unlink()
    except FileNotFoundError:
        raise ArtifactError("missing") from None
    except (zipfile.BadZipFile, struct.error):
        raise ArtifactError("archive_invalid") from None
    except OSError:
        raise ArtifactError("copy_failed") from None
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    try:
        verified = stage_wheelhouse(args.lock, args.manifest, args.artifact, args.directory)
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
