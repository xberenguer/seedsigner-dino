"""Hardware ownership, visible failure recovery, and signer entry boundaries."""
import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "payload/opt/dino"))
spec = importlib.util.spec_from_file_location(
    "native_launcher", Path(__file__).resolve().parents[1] / "payload/opt/dino/launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class FakeHardware:
    def __init__(self, events):
        self.events = events
        self.display = object()

    def __enter__(self):
        self.events.append("hardware open")
        return self

    def __exit__(self, *args):
        self.events.append("hardware closed")

    def read_mask(self):
        return 0

    def show_message(self, *message):
        self.events.append(message)


class NativeBoundaryTests(unittest.TestCase):
    def test_explicit_native_unlock_closes_hardware_without_fallback(self):
        events, commands = [], []

        def bridge(command, display, read_mask):
            commands.append(command)
            self.assertEqual(read_mask(), 0)
            events.append("native unlock")
            return 42

        def unexpected_fallback(hardware):
            raise AssertionError("Successful native game must not run fallback")

        launcher.run_native_gate(
            hardware_factory=lambda: FakeHardware(events), bridge_runner=bridge,
            fallback_factory=unexpected_fallback)
        self.assertEqual(commands, [[
            "/opt/dino/native/dino-native", "--bridge", "--core",
            "/opt/dino/native/gpsp_libretro.so", "--rom",
            "/opt/dino/native/Google-Dino-Advance.gba", "--display-width", "320",
            "--enter-buttons", "KEY1+KEY3", "--hold-seconds", "2"]])
        self.assertEqual(events, ["hardware open", ("Starting Dino...",),
                                  "native unlock", "hardware closed"])

    def test_every_ordinary_exit_and_failure_requires_fallback_gesture(self):
        for status in (0, 1, -11, FileNotFoundError("native missing"),
                       TimeoutError("native stuck")):
            with self.subTest(status=status):
                events, sleeps = [], []

                def bridge(*args):
                    if isinstance(status, Exception):
                        raise status
                    return status

                def fallback(hardware):
                    self.assertNotIn("hardware closed", events)
                    return SimpleNamespace(run=lambda: events.append("fallback gesture"))

                launcher.run_native_gate(
                    hardware_factory=lambda: FakeHardware(events),
                    bridge_runner=bridge, fallback_factory=fallback, sleep=sleeps.append)
                self.assertEqual(events, ["hardware open", ("Starting Dino...",),
                    ("Using fallback game", "Native game unavailable"),
                    "fallback gesture", "hardware closed"])
                self.assertEqual(sleeps, [0.75])

    def test_fallback_failure_cannot_start_signer(self):
        events = []

        def failure():
            raise RuntimeError("fallback interrupted before gesture")

        with self.assertRaises(RuntimeError):
            launcher.run_native_gate(
                hardware_factory=lambda: FakeHardware(events),
                bridge_runner=lambda *args: 1,
                fallback_factory=lambda hardware: SimpleNamespace(run=failure),
                sleep=lambda duration: None)
        self.assertEqual(events[-1], "hardware closed")

    def test_main_enters_gate_before_starting_signer(self):
        class BoundaryReached(Exception):
            pass

        def gate(**kwargs):
            raise BoundaryReached()

        with patch.object(launcher, "run_native_gate", gate):
            with self.assertRaises(BoundaryReached):
                launcher.main([])

    def test_native_release_then_plus_configuration_then_original_signer_splash(self):
        events = []
        settings = SimpleNamespace(_data={"display_config": "wrong"})

        class Splash:
            def run(self):
                events.append("original splash")

        original_splash = Splash.run

        class Driver:
            def init(self, commands):
                pass

        driver_module = SimpleNamespace(ST7789=Driver)
        settings_module = SimpleNamespace(
            Settings=SimpleNamespace(get_instance=lambda: settings),
            SettingsConstants=SimpleNamespace(
                SETTING__DISPLAY_CONFIGURATION="display_config"))

        def upstream_main(argv):
            events.append(("signer", argv, settings._data["display_config"]))
            self.assertTrue(Driver._dino_timing_installed)
            # Upstream startup keeps its original splash after hardware release.
            self.assertIs(Splash.run, original_splash)
            Splash().run()
            self.assertEqual(events[-1], "original splash")

        modules = {
            "seedsigner.models.settings": settings_module,
            "seedsigner.hardware.displays": SimpleNamespace(st7789_mpy=driver_module),
            "seedsigner.views.screensaver": SimpleNamespace(OpeningSplashView=Splash),
            "main": SimpleNamespace(main=upstream_main),
        }
        with patch.dict(sys.modules, modules), patch.object(sys, "path", list(sys.path)):
            with patch.object(launcher, "run_native_gate", lambda **kwargs: events.append("released")):
                launcher.main(["--loglevel", "WARNING"])
        self.assertEqual(events, ["released", (
            "signer", ["--loglevel", "WARNING"], "st7789_320x240"),
            "original splash"])
        self.assertIs(Splash.run, original_splash)

    def test_production_reads_custom_config_once_after_hardware_before_game(self):
        from dino_config import EntryConfig, REGULAR_PROFILE
        config = EntryConfig(("UP", "CENTER"), 3.0)
        events, commands = [], []
        def bridge(command, *args):
            commands.append(command)
            events.append("native game")
            return 42
        def read_config(**kwargs):
            self.assertEqual(events, ["hardware open", ("Reading Dino config...",)])
            return config, None
        with patch.object(launcher, "load_entry_config", side_effect=read_config) as entry:
            launcher.run_native_gate(hardware_factory=lambda: FakeHardware(events),
                                     bridge_runner=bridge, profile=REGULAR_PROFILE,
                                     entry_config=None)
        entry.assert_called_once_with(wait_for_mount=True)
        self.assertEqual(commands[0][-6:], ["--display-width", "240", "--enter-buttons",
                                          "UP+CENTER", "--hold-seconds", "3"])
        self.assertEqual(events[-3:], [("Starting Dino...",), "native game", "hardware closed"])

    def test_sd_mount_timeout_visibly_uses_default_gesture(self):
        from dino_config import DEFAULT_ENTRY, SD_NOT_READY_WARNING
        events, commands = [], []
        def bridge(command, *args):
            commands.append(command)
            return 42
        with patch.object(launcher, "load_entry_config", return_value=(DEFAULT_ENTRY, SD_NOT_READY_WARNING)):
            launcher.run_native_gate(hardware_factory=lambda: FakeHardware(events),
                                     bridge_runner=bridge, entry_config=None, sleep=lambda dt: None)
        self.assertIn(("SD card not ready", "Using default entry gesture"), events)
        self.assertEqual(commands[0][-4:], ["--enter-buttons", "KEY1+KEY3",
                                          "--hold-seconds", "2"])

    def test_warning_is_visible_and_custom_configuration_reaches_native(self):
        from dino_config import EntryConfig, REGULAR_PROFILE
        events, commands, sleeps = [], [], []
        def bridge(command, *args):
            commands.append(command)
            return 42
        launcher.run_native_gate(hardware_factory=lambda: FakeHardware(events),
                                 bridge_runner=bridge, sleep=sleeps.append,
                                 profile=REGULAR_PROFILE,
                                 entry_config=EntryConfig(("UP", "CENTER"), 1.5),
                                 config_warning="Invalid config")
        self.assertEqual(events[1], ("Invalid Dino config", "Using default entry gesture"))
        self.assertEqual(sleeps, [1.5])
        self.assertEqual(commands[0][-6:], ["--display-width", "240",
                                          "--enter-buttons", "UP+CENTER",
                                          "--hold-seconds", "1.5"])


if __name__ == "__main__":
    unittest.main()
