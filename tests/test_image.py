"""Packaging tests use tiny mock application payloads; never touch an SD card."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unittest

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts/build_image.py"
spec = importlib.util.spec_from_file_location("dino_build_image", MODULE_PATH)
image = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image)
UPSTREAM = Path(os.environ.get("DINO_BASE_IMAGE", MODULE_PATH.parents[1] / "downloads/seedsigner_os.0.8.7.pi0.img"))


def fixture(root, profile="plus"):
    (root / "opt/dino/assets").mkdir(parents=True)
    (root / "start.sh").write_text("#!/bin/sh\ncd /opt/src\nexec /usr/bin/python3 /opt/dino/launcher.py\n")
    (root / "opt/dino/launcher.py").write_text("print('test fixture')\n")
    (root / "opt/dino/display-profile.json").write_text(json.dumps({"profile": profile}) + "\n")
    (root / "opt/dino/assets/sprite.bin").write_bytes(bytes(range(256)))
    (root / "opt/dino/native").mkdir()
    (root / "opt/dino/native/dino-native").write_bytes(b"native executable fixture")
    (root / "opt/dino/native/gpsp_libretro.so").write_bytes(b"core shared library fixture")


class PackagingTests(unittest.TestCase):
    def test_cpio_is_deterministic_and_independently_decodes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            records = image.collect_payload(root)
            first = image.pack_newc(records)
            second = image.pack_newc(image.collect_payload(root))
            self.assertEqual(first, second)
            decoded = image.inspect_newc(first)
            self.assertEqual(set(decoded), set(records))
            for name, (mode, data) in records.items():
                self.assertEqual(decoded[name]["mode"], mode)
                self.assertEqual(decoded[name]["content"], data)
            self.assertEqual(decoded["start.sh"]["mode"], stat.S_IFREG | 0o755)
            self.assertEqual(decoded["opt/dino/native/dino-native"]["mode"], stat.S_IFREG | 0o755)
            self.assertEqual(decoded["opt/dino/native/gpsp_libretro.so"]["mode"], stat.S_IFREG | 0o644)

    def test_rejects_links_and_unapproved_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fixture(root)
            (root / "opt/dino/link").symlink_to("launcher.py")
            with self.assertRaisesRegex(ValueError, "Links"):
                image.collect_payload(root)
            (root / "opt/dino/link").unlink()
            (root / "etc").mkdir()
            with self.assertRaisesRegex(ValueError, "allowlist"):
                image.collect_payload(root)
            (root / "etc").rmdir()
            (root / "opt/dino/__pycache__").mkdir()
            with self.assertRaisesRegex(ValueError, "Host caches"):
                image.collect_payload(root)

    def test_rejects_path_traversal_and_corrupt_archive(self):
        for name in ("/etc/shadow", "../escape", "opt/../escape", "opt//dino", ""):
            with self.assertRaises(ValueError):
                image.safe_name(name)
        good = image.pack_newc({"start.sh": (stat.S_IFREG | 0o755, b"abc")})
        with self.assertRaises(ValueError):
            image.inspect_newc(good[:100])
        with self.assertRaises(ValueError):
            image.inspect_newc(good + b"unexpected")

    def test_refuses_device_and_existing_output(self):
        with self.assertRaises(ValueError):
            image.regular(Path("/dev/null"))
        with self.assertRaises(ValueError):
            image.new_path(Path("/dev/nonexistent-dino-test"))
        with tempfile.TemporaryDirectory() as temporary:
            existing = Path(temporary) / "existing.img"
            existing.write_bytes(b"keep")
            with self.assertRaises(ValueError):
                image.new_path(existing)
            self.assertEqual(existing.read_bytes(), b"keep")

    @unittest.skipUnless(UPSTREAM.is_file() and shutil.which("mcopy"), "Pinned upstream and mtools required")
    def test_full_image_preserves_upstream_and_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload"
            payload.mkdir()
            fixture(payload)
            first, second = root / "first.img", root / "second.img"
            a = image.build(UPSTREAM, payload, first)
            b = image.build(UPSTREAM, payload, second)
            self.assertEqual(a["sha256"], b["sha256"])
            self.assertEqual(a["image_size_bytes"], image.BASE_SIZE)
            self.assertGreater(a["preserved_upstream_file_count"], 300)
            self.assertEqual(image.inspect_image(first, UPSTREAM)["sha256"], a["sha256"])
            with self.assertRaises(ValueError):
                image.build(UPSTREAM, payload, first)

    @unittest.skipUnless(UPSTREAM.is_file() and shutil.which("mcopy"), "Pinned upstream and mtools required")
    def test_regular_profile_and_portable_manifest(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = root / "payload"
            payload.mkdir()
            fixture(payload, "regular")
            output = root / "regular.img"
            report = image.build(UPSTREAM, payload, output, profile="regular")
            self.assertEqual(report["image"], "regular.img")
            self.assertEqual(report["display_profile"], "regular")
            fat = image.Fat16(output.read_bytes())
            self.assertEqual(json.loads(fat.files["settings.json"])["display_config"], "st7789_240x240")
            self.assertEqual(fat.files["dino-config.ini"], image.DEFAULT_DINO_CONFIG)
            with self.assertRaisesRegex(ValueError, "profile"):
                image.inspect_image(output, UPSTREAM, "plus")


if __name__ == "__main__":
    unittest.main()
