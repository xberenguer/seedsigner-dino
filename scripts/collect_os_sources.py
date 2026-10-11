#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
"""Collect the pinned SeedSigner OS package sources/notices in a new container.

This does not rebuild the OS or access a physical device. The legal-info output
must be reviewed for warnings; collection alone is not a legal/security audit.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
INPUTS = {
    "seedsigner-os-source.tar.gz": {
        "url": "https://codeload.github.com/SeedSigner/seedsigner-os/tar.gz/d13859392660fe512a753bc14ecd0edc86c35510",
        "sha256": "a1e5b9820956b3ad2ba4853c3fdfa6cc5030f203cc3301f5a7309bdde88607ec",
        "commit": "d13859392660fe512a753bc14ecd0edc86c35510",
    },
    "buildroot-source.tar.gz": {
        "url": "https://codeload.github.com/SeedSigner/buildroot/tar.gz/bf2a2858aa675a14b60f1f9142c65b32652609c1",
        "sha256": "80cb79818c0fbda6cd87bd6b86925525818439201958eb47ad274cbdc7fbadbd",
        "commit": "bf2a2858aa675a14b60f1f9142c65b32652609c1",
    },
    "seedsigner-app-source.tar.gz": {
        "url": "https://codeload.github.com/SeedSigner/seedsigner/tar.gz/e0a80d4b33b8eb7fb1e9fd14a27b7cd11c7d2cd6",
        "sha256": "6e445b52e0732cfca6273511a10e29c19e1d2e707c77f2095040fe5e1f6ce01c",
        "commit": "e0a80d4b33b8eb7fb1e9fd14a27b7cd11c7d2cd6",
    },
    "seedsigner-translations-source.tar.gz": {
        "url": "https://codeload.github.com/SeedSigner/seedsigner-translations/tar.gz/708961a4163b1bd43eb15c4a26713649c63f6ccd",
        "sha256": "1d8c6bf89d45f1ec396810b467e32e8d6da55d45a389e71f1cdcc9bad1fa0326",
        "commit": "708961a4163b1bd43eb15c4a26713649c63f6ccd",
    },
}
COLLECT = r'''#!/bin/bash
set -euo pipefail
export FORCE_UNSAFE_CONFIGURE=1 TZ=UTC LC_ALL=C SOURCE_DATE_EPOCH=1672531200
apt-get -o Acquire::Check-Valid-Until=false update
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  wget patch rsync unzip bzip2 cpio file bc perl git g++ locales
mkdir -p /work/os/opt/buildroot /work/bundle/recipes /work/bundle/upstream-app
tar -xzf /work/inputs/seedsigner-os-source.tar.gz --strip-components=1 -C /work/os
tar -xzf /work/inputs/buildroot-source.tar.gz --strip-components=1 -C /work/os/opt/buildroot
make -C /work/os/opt/buildroot O=/work/os/output BR2_EXTERNAL=/work/os/opt/pi0 pi0_defconfig
make -C /work/os/output legal-info
cp -a /work/os/output/legal-info /work/bundle/legal-info
cp /work/inputs/seedsigner-os-source.tar.gz /work/inputs/buildroot-source.tar.gz /work/bundle/recipes/
cp /work/inputs/seedsigner-app-source.tar.gz /work/inputs/seedsigner-translations-source.tar.gz /work/bundle/upstream-app/
cp /work/inputs/source-inputs.json /work/bundle/
dpkg-query -W '-f=${Package}=${Version}\n' > /work/bundle/collector-debian-packages.txt
cd /work/bundle
find . -type f -print0 | sort -z | xargs -0 sha256sum > /work/bundle-files.sha256
cp /work/bundle-files.sha256 /work/bundle/bundle-files.sha256
tar --sort=name --mtime=@1672531200 --owner=0 --group=0 --numeric-owner -cf - . | gzip -n -9 > /work/seedsigner-v0.8.7-os-corresponding-source.tar.gz
'''


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def run(args, **kwargs):
    print("+ " + " ".join(map(str, args)), flush=True)
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker-context")
    parser.add_argument("--builder-image", default="seedsigner-dino-builder:0.1.0-beta")
    parser.add_argument("--output", type=Path, default=ROOT / "dist/os-source-collection")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise ValueError("Choose a new output directory; existing results are preserved")
    output.mkdir(parents=True)
    inputs = output / "inputs"
    inputs.mkdir()
    for name, item in INPUTS.items():
        target = inputs / name
        request = urllib.request.Request(item["url"], headers={"User-Agent": "seedsigner-dino-source-collector"})
        with urllib.request.urlopen(request, timeout=120) as incoming, target.open("wb") as outgoing:
            while block := incoming.read(1024 * 1024):
                outgoing.write(block)
        if sha(target) != item["sha256"]:
            raise ValueError("Pinned source hash mismatch: " + name)
        print("Verified " + name, flush=True)
    (inputs / "source-inputs.json").write_text(json.dumps(INPUTS, indent=2) + "\n")
    collector = output / "collect.sh"
    collector.write_text(COLLECT)
    docker = ["docker"] + (["--context", args.docker_context] if args.docker_context else [])
    identity = subprocess.check_output(docker + ["image", "inspect", args.builder_image, "--format", "{{.Id}}"], text=True).strip()
    container = subprocess.check_output(docker + ["create", "--platform", "linux/amd64", args.builder_image,
                                                "sleep", "infinity"], text=True).strip()
    try:
        run(docker + ["cp", str(inputs), container + ":/work/inputs"])
        run(docker + ["cp", str(collector), container + ":/work/collect.sh"])
        run(docker + ["start", container])
        log_path = output / "collection.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(docker + ["exec", container, "bash", "/work/collect.sh"],
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
            for line in process.stdout:
                log.write(line)
                log.flush()
                print(line, end="", flush=True)
            result = process.wait()
        if result:
            # Preserve diagnostic material when possible without claiming success.
            subprocess.run(docker + ["cp", container + ":/work/os/output/legal-info", str(output / "partial-legal-info")],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            raise RuntimeError("OS source collection failed; inspect collection.log")
        archive = output / "seedsigner-v0.8.7-os-corresponding-source.tar.gz"
        run(docker + ["cp", container + ":/work/seedsigner-v0.8.7-os-corresponding-source.tar.gz", str(archive)])
        run(docker + ["cp", container + ":/work/bundle/legal-info/README", str(output / "legal-info-README")])
        run(docker + ["cp", container + ":/work/bundle/legal-info/manifest.csv", str(output / "manifest.csv")])
        manifest = {"schema": 1, "kind": "upstream-os-source-collection", "seedsigner_version": "0.8.7",
                    "archive": archive.name, "sha256": sha(archive), "size_bytes": archive.stat().st_size,
                    "collector_image": identity, "inputs": INPUTS, "os_rebuilt": False,
                    "review_warnings": (output / "legal-info-README").read_text()}
        (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (output / "SHA256SUMS").write_text(sha(archive) + "  " + archive.name + "\n")
        print(json.dumps({key: value for key, value in manifest.items() if key not in ("inputs", "review_warnings")}, indent=2))
    finally:
        subprocess.run(docker + ["rm", "-f", container], check=True, stdout=subprocess.DEVNULL)


if __name__ == "__main__":
    main()
