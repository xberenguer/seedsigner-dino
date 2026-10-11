"""Portable IMG customization without changing executable code."""
import configparser
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "payload/opt/dino"))
from dino_config import (DEFAULT_ENTRY, PLUS_PROFILE, REGULAR_PROFILE,
                         SD_NOT_READY_WARNING, load_display_profile,
                         load_entry_config, parse_entry_config, wait_for_sd_mount)


class ConfigurationTests(unittest.TestCase):
    def test_defaults_and_custom_case_insensitive_chord(self):
        self.assertEqual(parse_entry_config("[dino]\n"), DEFAULT_ENTRY)
        entry = parse_entry_config("[dino]\nenter_buttons = center + up\nhold_seconds = 1.5\n")
        self.assertEqual(entry.buttons, ("UP", "CENTER"))
        self.assertEqual(entry.mask, 17)
        self.assertEqual(entry.native_arguments(),
                         ["--enter-buttons", "UP+CENTER", "--hold-seconds", "1.5"])

    def test_invalid_keys_sections_chords_and_durations_rejected(self):
        inputs = ["", "[other]\n", "[dino]\nunknown=yes\n", "[DEFAULT]\nx=y\n[dino]\n",
                  "[dino]\n[dino]\n", "[dino]\nenter_buttons=UP\n",
                  "[dino]\nenter_buttons=UP+UP\n", "[dino]\nenter_buttons=UP++CENTER\n",
                  "[dino]\nenter_buttons=UP+MISSING\n", "[dino]\nhold_seconds=nan\n",
                  "[dino]\nhold_seconds=inf\n", "[dino]\nhold_seconds=0.9\n",
                  "[dino]\nhold_seconds=10.1\n", "[dino]\nhold_seconds=string\n"]
        for text in inputs:
            with self.subTest(text=text), self.assertRaises((ValueError, configparser.Error)):
                parse_entry_config(text)

    def test_missing_bad_utf8_oversized_and_invalid_file_use_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dino-config.ini"
            self.assertEqual(load_entry_config(path), (DEFAULT_ENTRY, None))
            for data in (b"[dino]\nenter_buttons=UP\n", b"\xff", b"#" * 4097):
                path.write_bytes(data)
                before = path.read_bytes()
                entry, warning = load_entry_config(path)
                self.assertEqual(entry, DEFAULT_ENTRY)
                self.assertIsNotNone(warning)
                self.assertEqual(path.read_bytes(), before)

    def test_configuration_is_held_in_ram_after_sd_file_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dino-config.ini"
            path.write_text("[dino]\nenter_buttons=UP+CENTER\nhold_seconds=3\n")
            entry, warning = load_entry_config(path)
            path.unlink()
            self.assertIsNone(warning)
            self.assertEqual(entry.native_arguments(),
                             ["--enter-buttons", "UP+CENTER", "--hold-seconds", "3"])

    def test_profile_defaults_exact_profiles_and_invalid_profile_stops(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "display-profile.json"
            self.assertEqual(load_display_profile(path), PLUS_PROFILE)
            for name, expected in (("regular", REGULAR_PROFILE), ("plus", PLUS_PROFILE)):
                path.write_text(json.dumps({"profile": name}))
                self.assertEqual(load_display_profile(path), expected)
            for data in ({"profile": "other"}, {"profile": "regular", "extra": 1},
                         [], {"profile": ["regular"]}):
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    load_display_profile(path)

    def test_delayed_sd_mount_is_waited_for_before_configuration_read(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dino-config.ini"
            def mount_arrives(mount_point):
                self.assertEqual(mount_point, path.parent)
                # Models mdev mounting after launcher startup: file was absent before wait.
                self.assertFalse(path.exists())
                path.write_text("[dino]\nenter_buttons=UP+CENTER\nhold_seconds=4\n")
                return True
            entry, warning = load_entry_config(path, wait_for_mount=True, mount_waiter=mount_arrives)
            self.assertIsNone(warning)
            self.assertEqual(entry.buttons, ("UP", "CENTER"))
            self.assertEqual(entry.hold_seconds, 4)

    def test_mount_wait_is_bounded_and_directory_alone_is_not_readiness(self):
        timer = [0.0]
        def sleep(duration):
            timer[0] += duration
        self.assertFalse(wait_for_sd_mount("/unmounted/directory", is_mount=lambda path: False,
                                          clock=lambda: timer[0], sleep=sleep))
        self.assertAlmostEqual(timer[0], 10.0)
        timer[0] = 0.0
        self.assertTrue(wait_for_sd_mount("/late/mount", is_mount=lambda path: timer[0] >= 0.15,
                                         clock=lambda: timer[0], sleep=sleep))
        self.assertAlmostEqual(timer[0], 0.15)

    def test_unmounted_card_cannot_silently_supply_custom_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dino-config.ini"
            path.write_text("[dino]\nenter_buttons=UP+CENTER\n")
            self.assertEqual(load_entry_config(path, wait_for_mount=True, mount_waiter=lambda path: False),
                             (DEFAULT_ENTRY, SD_NOT_READY_WARNING))

    def test_mount_removed_during_read_warns_but_missing_file_on_mounted_card_uses_default(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "dino-config.ini"
            for mounted, expected in ((False, SD_NOT_READY_WARNING), (True, None)):
                with patch("dino_config.os.path.ismount", return_value=mounted):
                    self.assertEqual(load_entry_config(path, wait_for_mount=True,
                                                       mount_waiter=lambda path: True),
                                     (DEFAULT_ENTRY, expected))


if __name__ == "__main__":
    unittest.main()
