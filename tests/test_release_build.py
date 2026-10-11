"""Release boundaries: licensed pinned ROM, accounted-for cache and portable source archives."""
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


def test_rom_verification_rejects_unknown_bytes_and_links(tmp_path):
    with pytest.raises(ValueError, match="ROM path required"):
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
    assert "local_rom" not in lock
    assert lock["licensed_rom"]["bytes"] == 109084
    assert lock["licensed_rom"]["archive_member"] == "Google-Dino-Advance 1.1/Google-Dino-Advance.gba"
    assert all(len(item["sha256"]) == 64 and item["url"].startswith("https://") for item in lock["inputs"].values())


def test_official_rom_selection_ignores_resource_forks_and_rejects_duplicates(tmp_path, monkeypatch):
    import hashlib
    import zipfile
    payload = b'licensed game fixture'
    archive = tmp_path / 'downloads/release.zip'
    archive.parent.mkdir()
    with zipfile.ZipFile(archive, 'w') as stream:
        stream.writestr('__MACOSX/._Google-Dino-Advance.gba', b'not a ROM')
        stream.writestr('release/game.gba', payload)
    lock = {'licensed_rom': {'file': 'game.gba', 'archive_input': 'game',
            'archive_member': 'release/game.gba', 'bytes': len(payload),
            'sha256': hashlib.sha256(payload).hexdigest()},
            'inputs': {'game': {'file': 'release.zip', 'sha256': release.sha(archive)}}}
    monkeypatch.setattr(release, 'ROOT', tmp_path)
    monkeypatch.setattr(release, 'load_lock', lambda: lock)
    assert release.prepare_rom().read_bytes() == payload
    (tmp_path / 'downloads/game.gba').unlink()
    with pytest.warns(UserWarning, match='Duplicate name'):
        with zipfile.ZipFile(archive, 'a') as stream:
            stream.writestr('release/game.gba', payload)
    lock['inputs']['game']['sha256'] = release.sha(archive)
    with pytest.raises(ValueError, match='duplicated'):
        release.prepare_rom()


def test_cache_reuse_rejects_modified_runtime_and_modified_native(tmp_path, monkeypatch):
    import shutil
    import sys
    sys.path.insert(0, str(ROOT / 'scripts'))
    import package_release
    native = ROOT / 'dist/native-check-final'
    archive = ROOT / 'downloads/seedsigner-dino-v0.1.0-beta-source.tar.gz'
    if not native.exists() or not archive.exists():
        pytest.skip('Verified local native cache and corresponding source required')
    package_release.verify_cached_native(native)
    original = package_release.runtime_sources
    changed = original()
    changed['native/dino_frontend.c'] = '0' * 64
    monkeypatch.setattr(package_release, 'runtime_sources', lambda: changed)
    with pytest.raises(ValueError, match='Runtime source changed'):
        package_release.verify_cached_native(native)
    monkeypatch.setattr(package_release, 'runtime_sources', original)
    shutil.copytree(native, tmp_path / 'native')
    (tmp_path / 'native/plus/dino-native').write_bytes(b'mystery executable')
    with pytest.raises(ValueError, match='does not match'):
        package_release.verify_cached_native(tmp_path / 'native')
