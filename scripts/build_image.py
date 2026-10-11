#!/usr/bin/env python3
"""Build/inspect the Dino-on-SeedSigner image, using regular files only.

The signed upstream image is the immutable base. A tiny, deterministic external
newc initramfs supplements its built-in RAM filesystem. No raw devices, mounts,
kernel rebuilds, network access, or private keys are involved.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import struct
import subprocess
import tempfile

BASE_SHA256 = "67f005c7ace26500a78be3f4d97eaf02d76d018550ec54df011741dde1933ce9"
BASE_SIZE = 52_428_800
EPOCH = 1_672_531_200  # 2023-01-01 00:00:00 UTC
OVERLAY_NAME = "dino-overlay.cpio"
INITRAMFS_LINE = "initramfs dino-overlay.cpio followkernel"
PROFILES = {"regular": "st7789_240x240", "plus": "st7789_320x240"}
SETTINGS = {"persistent_settings": "E", "display_config": PROFILES["plus"]}
DEFAULT_DINO_CONFIG = b"[dino]\nenter_buttons=KEY1+KEY3\nhold_seconds=2\n"
EXECUTABLES = {"start.sh", "opt/dino/native/dino-native"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Expected a regular file, not a link/device: {path}")
    return path


def new_path(path):
    path = Path(path)
    if path.exists() or path.is_symlink() or str(path).startswith("/dev/"):
        raise ValueError(f"Refusing existing or device output: {path}")
    parent = path.parent.resolve(strict=True)
    if parent == Path("/dev") or parent.is_relative_to(Path("/dev")):
        raise ValueError("Device outputs are forbidden")
    return parent / path.name


def safe_name(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or ".." in p.parts or str(p) != name or "\x00" in name:
        raise ValueError(f"Unsafe archive path: {name!r}")
    return name


def collect_payload(root):
    root = Path(root)
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Payload must be a real directory")
    records = {}
    for path in sorted(root.rglob("*")):
        name = safe_name(path.relative_to(root).as_posix())
        mode = path.lstat().st_mode
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo") or any(part.startswith(".") for part in PurePosixPath(name).parts):
            raise ValueError(f"Host caches and hidden files must not enter the payload: {name}")
        if not (name == "start.sh" or name == "opt" or name == "opt/dino" or name.startswith("opt/dino/")):
            raise ValueError(f"Payload path outside the allowlist: {name}")
        if stat.S_ISDIR(mode):
            records[name] = (stat.S_IFDIR | 0o755, b"")
        elif stat.S_ISREG(mode):
            records[name] = (stat.S_IFREG | (0o755 if name in EXECUTABLES else 0o644), path.read_bytes())
        else:
            raise ValueError(f"Links and special payload files are forbidden: {name}")
    if "start.sh" not in records or not records["start.sh"][1].startswith(b"#!/bin/sh\n"):
        raise ValueError("Payload needs a /bin/sh start.sh launcher")
    if "opt/dino/launcher.py" not in records:
        raise ValueError("Payload needs opt/dino/launcher.py")
    for name in list(records):
        for parent in PurePosixPath(name).parents:
            if str(parent) != ".":
                records.setdefault(str(parent), (stat.S_IFDIR | 0o755, b""))
    return dict(sorted(records.items(), key=lambda item: (len(PurePosixPath(item[0]).parts), item[0])))


def pack_newc(records):
    archive = bytearray()
    for ino, (name, (mode, content)) in enumerate(list(records.items()) + [("TRAILER!!!", (0, b""))], 1):
        encoded = name.encode("utf-8") + b"\0"
        values = [ino, mode, 0, 0, 2 if stat.S_ISDIR(mode) else 1, EPOCH,
                  len(content), 0, 0, 0, 0, len(encoded), 0]
        archive += b"070701" + "".join(f"{v:08x}" for v in values).encode("ascii")
        archive += encoded
        archive += b"\0" * (-len(archive) % 4)
        archive += content
        archive += b"\0" * (-len(archive) % 4)
    archive += b"\0" * (-len(archive) % 512)
    return bytes(archive)


def inspect_newc(data):
    """Independent strict decoder; does not extract or execute archive contents."""
    result = {}
    offset = 0
    while True:
        header = data[offset:offset + 110]
        if len(header) != 110 or header[:6] != b"070701":
            raise ValueError(f"Invalid newc header at {offset}")
        try:
            fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        except ValueError as error:
            raise ValueError("Non-hex newc field") from error
        _, mode, uid, gid, nlink, mtime, size, devmaj, devmin, rmaj, rmin, namesize, check = fields
        name_bytes = data[offset + 110:offset + 110 + namesize]
        if not namesize or len(name_bytes) != namesize or name_bytes[-1:] != b"\0":
            raise ValueError("Truncated or unterminated newc name")
        name = name_bytes[:-1].decode("utf-8")
        content_offset = (offset + 110 + namesize + 3) & ~3
        content = data[content_offset:content_offset + size]
        if len(content) != size:
            raise ValueError("Truncated newc content")
        offset = (content_offset + size + 3) & ~3
        if name == "TRAILER!!!":
            if size or any(data[offset:]):
                raise ValueError("Unexpected data after newc trailer")
            break
        safe_name(name)
        if name in result or uid or gid or devmaj or devmin or rmaj or rmin or check:
            raise ValueError("Duplicate path or unsafe newc metadata")
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError("Non-regular/non-directory newc entry")
        parent = str(PurePosixPath(name).parent)
        if parent != "." and (parent not in result or not stat.S_ISDIR(result[parent]["mode"])):
            raise ValueError("Archive parent directory must precede its children")
        result[name] = {"mode": mode, "uid": uid, "gid": gid, "mtime": mtime,
                        "size": size, "sha256": sha(content), "content": content}
    return result


class Fat16:
    """Read-only independent FAT16 walker for the verified upstream image."""
    def __init__(self, data):
        self.data = data
        if data[510:512] != b"\x55\xaa":
            raise ValueError("Invalid MBR")
        self.partition_start, self.partition_sectors = struct.unpack_from("<II", data, 454)
        self.offset = self.partition_start * 512
        b = data[self.offset:self.offset + 512]
        self.sector_bytes = struct.unpack_from("<H", b, 11)[0]
        self.cluster_sectors = b[13]
        self.reserved = struct.unpack_from("<H", b, 14)[0]
        self.fat_count = b[16]
        self.root_count = struct.unpack_from("<H", b, 17)[0]
        self.fat_sectors = struct.unpack_from("<H", b, 22)[0]
        if self.sector_bytes != 512 or not self.root_count or not self.fat_sectors or b[54:62] != b"FAT16   ":
            raise ValueError("Expected upstream FAT16 geometry")
        self.cluster_bytes = self.sector_bytes * self.cluster_sectors
        self.fat_offset = self.offset + self.reserved * self.sector_bytes
        self.root_offset = self.fat_offset + self.fat_count * self.fat_sectors * self.sector_bytes
        self.root_bytes = self.root_count * 32
        self.data_offset = self.root_offset + ((self.root_bytes + 511) // 512) * 512
        if self.offset + self.partition_sectors * 512 != len(data):
            raise ValueError("Unexpected upstream partition boundary")
        fat_size = self.fat_sectors * self.sector_bytes
        for index in range(1, self.fat_count):
            if data[self.fat_offset:self.fat_offset + fat_size] != data[self.fat_offset + index * fat_size:self.fat_offset + (index + 1) * fat_size]:
                raise ValueError("FAT table copies disagree")
        self.files, self.entries = {}, {}
        self.walk("", range(self.root_offset, self.root_offset + self.root_bytes, 32), set())

    def chain(self, first):
        result, seen = [], set()
        cluster = first
        while 2 <= cluster < 0xfff8:
            if cluster in seen:
                raise ValueError("FAT cluster cycle")
            seen.add(cluster)
            off = self.data_offset + (cluster - 2) * self.cluster_bytes
            if off + self.cluster_bytes > len(self.data):
                raise ValueError("FAT cluster outside partition")
            result.append(off)
            cluster = struct.unpack_from("<H", self.data, self.fat_offset + cluster * 2)[0]
        if cluster < 0xfff8:
            raise ValueError("Broken FAT chain")
        return result

    def walk(self, prefix, offsets, visited):
        fragments = {}
        for off in offsets:
            entry = self.data[off:off + 32]
            if entry[0] == 0:
                break
            if entry[0] == 0xe5:
                fragments.clear()
                continue
            if entry[11] == 0x0f:
                sequence = entry[0] & 0x1f
                chunks = entry[1:11] + entry[14:26] + entry[28:32]
                fragments[sequence] = chunks
                continue
            if entry[11] & 0x08:
                fragments.clear()
                continue
            if fragments:
                name = b"".join(fragments[i] for i in sorted(fragments)).decode("utf-16le").split("\0")[0].rstrip("\uffff")
            else:
                stem, ext = entry[:8].decode("ascii").rstrip(), entry[8:11].decode("ascii").rstrip()
                name = stem + ("." + ext if ext else "")
                if entry[12] & 8:
                    name = name[:len(stem)].lower() + name[len(stem):]
                if entry[12] & 16 and ext:
                    name = name[:-len(ext)] + ext.lower()
            fragments.clear()
            if name in (".", ".."):
                continue
            safe_name(name)
            name = prefix + name
            if name in self.entries:
                raise ValueError("Duplicate FAT path")
            self.entries[name] = off
            cluster = struct.unpack_from("<H", entry, 26)[0]
            size = struct.unpack_from("<I", entry, 28)[0]
            if entry[11] & 0x10:
                if cluster in visited:
                    raise ValueError("FAT directory cycle")
                sectors = self.chain(cluster)
                children = [p for c in sectors for p in range(c, c + self.cluster_bytes, 32)]
                self.walk(name + "/", children, visited | {cluster})
            else:
                content = b"".join(self.data[p:p + self.cluster_bytes] for p in self.chain(cluster)) if size else b""
                if len(content) < size:
                    raise ValueError("Truncated FAT file")
                self.files[name] = content[:size]


def normalized_metadata(image, names):
    data = bytearray(image)
    fat = Fat16(data)
    fixed_date = ((2023 - 1980) << 9) | (1 << 5) | 1
    for name in names:
        off = fat.entries[name]
        data[off + 13] = 0
        for at in (14, 22):
            struct.pack_into("<H", data, off + at, 0)
        for at in (16, 18, 24):
            struct.pack_into("<H", data, off + at, fixed_date)
    return bytes(data)


def config_with_overlay(original):
    text = original.decode("ascii")
    if any(line.strip().startswith(("initramfs ", "ramfsfile=", "os_prefix=")) for line in text.splitlines()):
        raise ValueError("Unexpected initramfs or OS prefix in upstream config")
    return (text.rstrip() + "\n\n# Dino launcher: same SeedSigner kernel and RAM filesystem.\n" + INITRAMFS_LINE + "\n").encode("ascii")


def inspect_image(path, base_path=None, profile=None):
    data = regular(path).read_bytes()
    fat = Fat16(data)
    required = ("bootcode.bin", "start_x.elf", "fixup_x.dat", "zImage", "bcm2708-rpi-zero.dtb", "config.txt", "settings.json", "dino-config.ini", OVERLAY_NAME)
    if any(name not in fat.files for name in required):
        raise ValueError("Candidate missing required firmware, settings or overlay")
    if fat.files["config.txt"].decode().splitlines().count(INITRAMFS_LINE) != 1:
        raise ValueError("Candidate initramfs directive differs")
    entries = inspect_newc(fat.files[OVERLAY_NAME])
    if "start.sh" not in entries or "opt/dino/launcher.py" not in entries:
        raise ValueError("Candidate archive missing launcher")
    installed = json.loads(entries["opt/dino/display-profile.json"]["content"])
    actual_profile = installed.get("profile")
    if actual_profile not in PROFILES or (profile and actual_profile != profile):
        raise ValueError("Installed display profile differs")
    if json.loads(fat.files["settings.json"]) != {"persistent_settings": "E", "display_config": PROFILES[actual_profile]}:
        raise ValueError("Candidate display settings differ from installed profile")
    if fat.files["dino-config.ini"] != DEFAULT_DINO_CONFIG:
        raise ValueError("Candidate default entry gesture differs")
    for name, record in entries.items():
        if not (name in ("start.sh", "opt", "opt/dino") or name.startswith("opt/dino/")):
            raise ValueError(f"Unexpected archive path: {name}")
        expected_mode = stat.S_IFDIR | 0o755 if stat.S_ISDIR(record["mode"]) else stat.S_IFREG | (0o755 if name in EXECUTABLES else 0o644)
        if record["mode"] != expected_mode or record["mtime"] != EPOCH:
            raise ValueError(f"Archive mode/timestamp differs: {name}")
    preserved = None
    if base_path:
        original = regular(base_path).read_bytes()
        if sha(original) != BASE_SHA256 or len(original) != BASE_SIZE:
            raise ValueError("Upstream image checksum differs")
        upstream = Fat16(original)
        if data[:fat.offset] != original[:fat.offset] or len(data) != len(original):
            raise ValueError("Candidate MBR/padding/layout differs from upstream")
        if set(fat.files) != set(upstream.files) | {OVERLAY_NAME, "settings.json", "dino-config.ini"}:
            raise ValueError("Unexpected FAT file additions/removals")
        for name, content in upstream.files.items():
            if name != "config.txt" and fat.files[name] != content:
                raise ValueError(f"Upstream file changed: {name}")
        if fat.files["config.txt"] != config_with_overlay(upstream.files["config.txt"]):
            raise ValueError("Candidate boot config changed unexpectedly")
        preserved = len(upstream.files) - 1
    return {"schema": 1, "image": Path(path).name, "display_profile": actual_profile, "image_size_bytes": len(data),
            "sha256": sha(data), "base_sha256": BASE_SHA256,
            "filesystem": "FAT16", "partition_start_sector": fat.partition_start,
            "partition_sectors": fat.partition_sectors,
            "preserved_upstream_file_count": preserved,
            "fat_files_sha256": {name: sha(content) for name, content in sorted(fat.files.items())},
            "overlay_sha256": sha(fat.files[OVERLAY_NAME]),
            "overlay_size_bytes": len(fat.files[OVERLAY_NAME]),
            "overlay_entries": {name: {k: v for k, v in record.items() if k != "content"} for name, record in entries.items()},
            "hardware_tested": False, "physical_device_written": False}


def build(base, payload, output, mcopy="mcopy", profile="plus"):
    if profile not in PROFILES:
        raise ValueError("Unknown display profile")
    base = regular(base)
    original = base.read_bytes()
    if len(original) != BASE_SIZE or sha(original) != BASE_SHA256:
        raise ValueError("Signed upstream image hash/size does not match the pinned Pi Zero release")
    upstream = Fat16(original)
    records = collect_payload(payload)
    installed = records.get("opt/dino/display-profile.json")
    if installed is None or json.loads(installed[1]) != {"profile": profile}:
        raise ValueError("Payload must explicitly declare the matching installed display profile")
    archive = pack_newc(records)
    if any(inspect_newc(archive)[name]["content"] != record[1] for name, record in records.items()):
        raise ValueError("CPIO readback mismatch")
    output = new_path(output)
    manifest_path = new_path(str(output) + ".manifest.json")
    checksum_path = new_path(str(output) + ".sha256")
    config = config_with_overlay(upstream.files["config.txt"])
    settings = (json.dumps({"persistent_settings": "E", "display_config": PROFILES[profile]}, indent=2) + "\n").encode()
    created = []
    with tempfile.TemporaryDirectory(prefix="dino-image-", dir=output.parent) as temporary:
        stage = Path(temporary)
        staged_image = stage / output.name
        staged_image.write_bytes(original)
        for name, content in ((OVERLAY_NAME, archive), ("config.txt", config), ("settings.json", settings), ("dino-config.ini", DEFAULT_DINO_CONFIG)):
            source = stage / name
            source.write_bytes(content)
            os.utime(source, (EPOCH, EPOCH))
            subprocess.run([mcopy, "-o", "-m", "-i", f"{staged_image}@@{upstream.offset}", str(source), "::/" + name],
                           check=True, env={**os.environ, "TZ": "UTC"})
        staged_image.write_bytes(normalized_metadata(staged_image.read_bytes(), (OVERLAY_NAME, "config.txt", "settings.json", "dino-config.ini")))
        report = inspect_image(staged_image, base, profile)
        report["image"] = output.name
        report["reproducibility"] = {"cpio_mtime": EPOCH, "cpio_owner": "0:0", "entry_order": "parent-before-child, sorted", "modified_fat_timestamps": "2023-01-01T00:00:00Z"}
        try:
            with output.open("xb") as stream:
                stream.write(staged_image.read_bytes())
                stream.flush()
                os.fsync(stream.fileno())
            created.append(output)
            with manifest_path.open("x") as stream:
                json.dump(report, stream, indent=2)
                stream.write("\n")
            created.append(manifest_path)
            checksum_path.write_text(f"{report['sha256']}  {output.name}\n")
            created.append(checksum_path)
        except Exception:
            for path in created:
                path.unlink()
            raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build_parser = sub.add_parser("build")
    build_parser.add_argument("--base", required=True, type=Path)
    build_parser.add_argument("--payload", required=True, type=Path)
    build_parser.add_argument("--output", required=True, type=Path)
    build_parser.add_argument("--mcopy", default="mcopy")
    build_parser.add_argument("--profile", choices=tuple(PROFILES), required=True)
    inspect_parser = sub.add_parser("inspect")
    inspect_parser.add_argument("image", type=Path)
    inspect_parser.add_argument("--base", type=Path)
    inspect_parser.add_argument("--profile", choices=tuple(PROFILES))
    args = parser.parse_args()
    report = build(args.base, args.payload, args.output, args.mcopy, args.profile) if args.command == "build" else inspect_image(args.image, args.base, args.profile)
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
