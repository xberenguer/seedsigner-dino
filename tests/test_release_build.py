"""Release boundaries: external ROM, pinned inputs and portable source archives."""
import importlib.util
import json
from pathlib import Path
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release_builder", ROOT / "scripts/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def test_source_archive_is_repeatable_and_has_no_local_binaries(tmp_path):
    first = release.source(tmp_path / "first")
    second = release.source(tmp_path / "second")
    assert first == second
    archive = tmp_path / "first" / release.SOURCE_NAME
    assert archive.read_bytes()[9] == 255
    with tarfile.open(archive) as stream:
        names = stream.getnames()
        assert "seedsigner-dino/build/inputs.lock.json" in names
        assert "seedsigner-dino/scripts/container_build.py" in names
        assert "seedsigner-dino/payload/opt/dino/dino_config.py" in names
        for member in stream.getmembers():
            assert member.isfile()
            assert member.uid == member.gid == 0
            assert member.mtime == release.EPOCH
        assert not any(name.endswith((".img", ".gba", ".so", "/dino-native", ".pyc")) for name in names)
        assert not any("/downloads/" in name or "/dist/" in name or "__pycache__" in name for name in names)
    text = (tmp_path / "first" / (release.SOURCE_NAME + ".manifest.json")).read_text()
    assert str(ROOT) not in text
    assert json.loads(text)["ROM_included"] is False


def test_local_rom_is_explicit_and_rejects_unknown_bytes(tmp_path):
    with pytest.raises(ValueError, match="explicit local --rom"):
        release.verify_rom(None)
    rom = tmp_path / "mystery.gba"
    rom.write_bytes(b"not a reviewed input")
    with pytest.raises(ValueError, match="does not match"):
        release.verify_rom(rom)
    link = tmp_path / "linked.gba"
    link.symlink_to(rom)
    with pytest.raises(ValueError, match="link"):
        release.verify_rom(link)


def test_locks_include_no_private_paths_and_armv6_toolchain():
    lock = release.load_lock()
    assert lock["inputs"]["toolchain"]["file"].startswith("armv6-eabihf")
    assert "amd64" in lock["build_environment"]["platform"]
    assert "/Users/" not in json.dumps(lock)
    assert "local_rom" in lock and "local_rom" not in lock["inputs"]
    assert all(len(item["sha256"]) == 64 and item["url"].startswith("https://") for item in lock["inputs"].values())
