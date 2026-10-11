#!/usr/bin/env python3
"""Verify locked bytes and SeedSigner's signed checksum, using an empty keyring."""
import json
from pathlib import Path
import subprocess
import tempfile

from release import ROOT, checked, fetch, load_lock, sha


def verify_signature():
    lock = load_lock()
    paths = {name: checked(ROOT / "downloads" / item["file"], item["sha256"])
             for name, item in lock["inputs"].items()}
    expected = lock["signer_primary_fingerprint"]
    with tempfile.TemporaryDirectory(prefix="dino-gpg-") as temporary:
        Path(temporary).chmod(0o700)
        gpg = ["gpg", "--no-options", "--homedir", temporary, "--batch"]
        subprocess.run(gpg + ["--import", str(paths["seedsigner_key"])], check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        fingerprints = subprocess.check_output(gpg + ["--with-colons", "--fingerprint", "--list-keys"], text=True)
        if expected not in [line.split(":")[9] for line in fingerprints.splitlines() if line.startswith("fpr:")]:
            raise ValueError("SeedSigner public-key primary fingerprint differs")
        result = subprocess.run(gpg + ["--status-fd", "1", "--verify", str(paths["seedsigner_signature"]),
                                      str(paths["seedsigner_sums"])], text=True, capture_output=True)
        valid = [line.split() for line in result.stdout.splitlines() if line.startswith("[GNUPG:] VALIDSIG ")]
        bad = ("BADSIG", "ERRSIG", "EXPSIG", "EXPKEYSIG", "REVKEYSIG")
        if result.returncode or any(word in result.stdout for word in bad) or not any(expected in fields for fields in valid):
            raise ValueError("SeedSigner detached signature did not validate against the pinned primary key")
    matches = [line.split() for line in paths["seedsigner_sums"].read_text().splitlines()
               if len(line.split()) == 2 and line.split()[1].lstrip("*") == paths["seedsigner_os"].name]
    if len(matches) != 1 or matches[0][0] != sha(paths["seedsigner_os"]):
        raise ValueError("Pinned OS does not match its signed checksum record")
    return {"valid": True, "primary_fingerprint": expected,
            "signed_image": paths["seedsigner_os"].name, "sha256": matches[0][0]}


if __name__ == "__main__":
    fetch(offline=True)
    print(json.dumps(verify_signature(), indent=2))
