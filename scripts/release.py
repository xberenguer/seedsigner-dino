#!/usr/bin/env python3
"""Pinned inputs, isolated builds, image packaging and source archives.

No GitHub write or physical-device operation is performed. The official ROM1.1
is a declared trusted upstream binary; its source-to-binary build is not verified.
"""
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
LOCK = ROOT / "build/inputs.lock.json"
EPOCH = 1672531200
IMAGE_TAG = "seedsigner-dino-builder:0.1.1-beta"
SOURCE_NAME = "seedsigner-dino-v0.1.1-beta-source.tar.gz"


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def load_lock():
    return json.loads(LOCK.read_text())


def checked(path, expected):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or sha(path) != expected:
        raise ValueError("Input is missing, a link, or does not match its lock: " + path.name)
    return path


def fetch(offline=False):
    downloads = ROOT / "downloads"
    downloads.mkdir(exist_ok=True)
    for item in load_lock()["inputs"].values():
        target = downloads / item["file"]
        if not target.exists() and not offline:
            temporary = target.with_suffix(target.suffix + ".part")
            if temporary.is_symlink():
                raise ValueError("Refusing linked download temporary file")
            request = urllib.request.Request(item["url"], headers={"User-Agent": "seedsigner-dino-source-builder"})
            with urllib.request.urlopen(request, timeout=120) as incoming, temporary.open("wb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, 1024 * 1024)
            checked(temporary, item["sha256"])
            temporary.replace(target)
        checked(target, item["sha256"])
        print("Verified " + target.name, flush=True)


def verify_rom(path):
    if path is None:
        raise ValueError("ROM path required for verification; use prepare_rom for the locked official release")
    item = load_lock()["licensed_rom"]
    path = checked(path, item["sha256"])
    if path.stat().st_size != item["bytes"]:
        raise ValueError("ROM size does not match the licensed official1.1 input")
    return path


def prepare_rom(path=None):
    if path is not None:
        return verify_rom(path)
    lock = load_lock()
    item = lock["licensed_rom"]
    release_input = lock["inputs"][item["archive_input"]]
    archive = checked(ROOT / "downloads" / release_input["file"], release_input["sha256"])
    target = ROOT / "downloads" / item["file"]
    if target.exists() or target.is_symlink():
        return verify_rom(target)
    # Exact member only: upstream ZIP also contains macOS resource-fork .gba files.
    with zipfile.ZipFile(archive) as stream:
        matches = [entry for entry in stream.infolist() if entry.filename == item["archive_member"]]
        if len(matches) != 1 or matches[0].file_size != item["bytes"]:
            raise ValueError("Official release ROM member is missing, duplicated or wrong size")
        data = stream.read(matches[0])
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("Official release ROM member does not match its lock")
    with target.open("xb") as outgoing:
        outgoing.write(data)
    return verify_rom(target)


def source_files():
    directories = ("native", "payload", "scripts", "tests", "docs", "tools", ".github")
    files = [p for p in ROOT.iterdir() if p.is_file() and p.name in
             {"LICENSE", "README.md", "CREDITS.md", "NOTICE", "NOTICE.txt", "CHANGELOG.md", "SECURITY.md", "CONTRIBUTING.md", "requirements-test.txt", ".gitignore", ".gitattributes", ".dockerignore"}]
    for directory in directories:
        folder = ROOT / directory
        if folder.is_dir():
            files.extend(p for p in folder.rglob("*") if p.is_file() or p.is_symlink())
    files.extend(ROOT / "build" / name for name in ("Dockerfile", "inputs.lock.json", "native-cache.lock.json", "bios.ld"))
    approved = []
    for path in sorted(set(files)):
        relative = path.relative_to(ROOT)
        if path.is_symlink():
            raise ValueError("Source archive refuses symlinks: " + str(relative))
        if "__pycache__" in relative.parts or path.suffix in (".pyc", ".pyo", ".o", ".so", ".a", ".img", ".gba") or path.name == "dino-native":
            continue
        if path.name.endswith((".tar.gz", ".tar.xz", ".zip")) or path.name == ".DS_Store":
            continue
        approved.append(path)
    return approved


def source(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    archive_path = output / SOURCE_NAME
    if archive_path.exists():
        raise ValueError("Refusing existing source archive; choose a new output directory")
    hashes, buffer = {}, io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for path in source_files():
            name = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            info = tarfile.TarInfo("seedsigner-dino/" + name)
            info.size, info.mtime, info.mode = len(data), EPOCH, 0o644
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(data))
            hashes[name] = hashlib.sha256(data).hexdigest()
    compressed = bytearray(gzip.compress(buffer.getvalue(), compresslevel=9, mtime=0))
    compressed[9] = 255  # Normalize gzip OS byte across Python 3.11-3.14.
    archive_path.write_bytes(compressed)
    manifest = {"schema": 1, "version": load_lock()["project_version"], "kind": "project-source",
                "archive": archive_path.name, "sha256": sha(archive_path), "files": hashes,
                "ROM_included": False, "OS_image_included": False, "compiled_binaries_included": False}
    (output / (SOURCE_NAME + ".manifest.json")).write_text(json.dumps(manifest, indent=2) + "\n")
    (output / "SHA256SUMS").write_text(sha(archive_path) + "  " + archive_path.name + "\n")
    print(json.dumps({k: v for k, v in manifest.items() if k != "files"}, indent=2))
    return manifest


def run_container(context, rom, native_only, rebuild_builder=False, output=None):
    # Inputs are verified on both sides of this boundary. Docker cp deliberately
    # avoids depending on host/VM shared-directory configuration on macOS.
    fetch(offline=True)
    rom = None if native_only else prepare_rom(rom)
    docker = ["docker"] + (["--context", context] if context else [])
    target = Path(output) if output else ROOT / "dist/local-build"
    if target.exists():
        raise ValueError("Refusing existing build output directory; use --output with a new path")
    # Re-evaluate the pinned recipe every time; an existing mutable local tag
    # alone is not a verified builder. Docker may reuse matching build layers.
    subprocess.run(docker + ["build", "--platform", "linux/amd64"] +
                   (["--no-cache"] if rebuild_builder else []) +
                   ["-f", str(ROOT / "build/Dockerfile"), "-t", IMAGE_TAG, str(ROOT)], check=True)
    container = subprocess.check_output(docker + ["create", "--network", "none", "--platform", "linux/amd64",
                                                 IMAGE_TAG, "bash", "scripts/build_in_container.sh"] +
                                        (["--native-only"] if native_only else []), text=True).strip()
    try:
        for name in ("native", "payload", "scripts", "build", "downloads"):
            subprocess.run(docker + ["cp", str(ROOT / name), container + ":/work/" + name], check=True)
        with tempfile.TemporaryDirectory(prefix="dino-corresponding-source-") as temporary:
            source(temporary)
            subprocess.run(docker + ["cp", str(Path(temporary) / SOURCE_NAME),
                                    container + ":/work/project-source.tar.gz"], check=True)
        if rom:
            subprocess.run(docker + ["cp", str(rom.resolve()), container + ":/work/local-rom.gba"], check=True)
        subprocess.run(docker + ["start", "--attach", container], check=True)
        state = json.loads(subprocess.check_output(docker + ["inspect", container], text=True))[0]["State"]
        if state["ExitCode"]:
            raise RuntimeError("Isolated build failed; inspect build output above")
        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(docker + ["cp", container + ":/work/artifacts", str(target)], check=True)
    finally:
        subprocess.run(docker + ["rm", "-f", container], check=True, stdout=subprocess.DEVNULL)
    print("Local artifacts: " + str(target))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    download = sub.add_parser("fetch")
    download.add_argument("--offline", action="store_true")
    sub.add_parser("verify", help="Verify locked downloads and the OS signature (requires local gpg)")
    package = sub.add_parser("source")
    package.add_argument("--output", type=Path, default=ROOT / "dist/source-preview")
    cached = sub.add_parser("package", help="Assemble images using the pinned, verified native build cache (local gpg and mcopy required)")
    cached.add_argument("--native-dir", type=Path, required=True)
    cached.add_argument("--rom", type=Path)
    cached.add_argument("--output", type=Path, required=True)
    for name in ("native", "build"):
        build = sub.add_parser(name)
        build.add_argument("--docker-context")
        build.add_argument("--rom", type=Path)
        build.add_argument("--output", type=Path)
        build.add_argument("--rebuild-builder", action="store_true")
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.offline)
    elif args.command == "verify":
        from verify_inputs import verify_signature
        fetch(offline=True)
        print(json.dumps(verify_signature(), indent=2))
    elif args.command == "source":
        source(args.output)
    elif args.command == "package":
        from package_release import package_images
        package_images(args.native_dir, args.output, args.rom)
    else:
        # Validate local ROM before any Docker mutation.
        if args.command == "build":
            prepare_rom(args.rom)
        run_container(args.docker_context, args.rom, args.command == "native", args.rebuild_builder, args.output)


if __name__ == "__main__":
    main()
