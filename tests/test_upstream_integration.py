"""Regression checks against the actual pinned upstream app and display driver.

Native QR image extraction is deliberately unavailable in the host harness.
Any accidental call into that stub fails instead of pretending to decode images.
"""

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import random
import subprocess
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image


PROJECT = Path(__file__).resolve().parents[1]
UPSTREAM = Path(os.environ.get("SEEDSIGNER_SOURCE", PROJECT / "build/inputs/seedsigner-app"))
sys.path.insert(0, str(PROJECT / "payload/opt/dino"))
spec = importlib.util.spec_from_file_location("dino_regression_launcher", PROJECT / "payload/opt/dino/launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


@contextmanager
def actual_driver_with_fake_hardware():
    gpio = ModuleType("RPi.GPIO")
    gpio.BOARD, gpio.OUT, gpio.HIGH, gpio.LOW = 10, 0, 1, 0
    gpio_events = []
    for method in ("setmode", "setwarnings", "setup", "output"):
        setattr(gpio, method, lambda *args, method=method: gpio_events.append((method, args)))
    rpi = ModuleType("RPi")
    rpi.GPIO = gpio
    devices = []

    class SpiDev:
        def __init__(self, *args):
            self.writes = []
            self.max_speed_hz = None
            devices.append(self)

        def writebytes2(self, data):
            self.writes.append((self.max_speed_hz, bytes(data)))

    spidev = ModuleType("spidev")
    spidev.SpiDev = SpiDev
    module_name = "dino_test_actual_st7789_driver"
    driver_spec = importlib.util.spec_from_file_location(
        module_name, UPSTREAM / "src/seedsigner/hardware/displays/st7789_mpy.py",
    )
    module = importlib.util.module_from_spec(driver_spec)
    with patch.dict(sys.modules, {"RPi": rpi, "RPi.GPIO": gpio,
                                 "spidev": spidev, module_name: module}):
        with patch.object(sys, "path", [str(UPSTREAM / "src")] + sys.path):
            driver_spec.loader.exec_module(module)
            yield module, devices, gpio_events


UPSTREAM_TESTS = [
    "tests/test_controller.py", "tests/test_settings.py", "tests/test_seed.py",
    "tests/test_psbt_parser.py", "tests/test_encodepsbtqr.py",
    "tests/test_decodepsbtqr.py", "tests/test_flows_psbt.py", "tests/test_main.py",
]


def run_upstream_regression(enable_hooks=True):
    code = r'''
import importlib.util, json, sys, types
from pathlib import Path
root = Path(sys.argv[1])
enable_hooks = sys.argv[2] == "true"
sys.path.insert(0, str(Path.cwd() / "src"))
sys.path.insert(0, str(Path.cwd() / "tests"))
# No native zbar exists in this Mac venv. Pure payload-decoding/signing tests must
# never call image extraction; this stub fails loudly if they do.
stub = types.ModuleType("pyzbar.pyzbar")
class Symbol:
    QRCODE = 64
stub.ZBarSymbol = Symbol
def decode_unavailable(*args, **kwargs):
    raise AssertionError("Native QR image extraction is outside this host regression")
stub.decode = decode_unavailable
sys.modules["pyzbar.pyzbar"] = stub
import base
from seedsigner.controller import Controller
from seedsigner.gui.renderer import Renderer
from seedsigner.hardware.buttons import HardwareButtons, HardwareButtonsConstants
spec = importlib.util.spec_from_file_location("dino_host_launcher", root / "payload/opt/dino/launcher.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
gate_calls = []
class Gate:
    def __init__(self, renderer, buttons, pins):
        pass
    def run(self):
        assert Controller.get_instance()._dino_gate_active is True
        gate_calls.append("entered")
if enable_hooks:
    launcher.install_controller_hooks(Controller, Renderer, HardwareButtons,
                                      HardwareButtonsConstants, gate_factory=Gate)
import pytest
class Summary:
    counts = {}
    def pytest_terminal_summary(self, terminalreporter):
        self.counts = {name: len(items) for name, items in terminalreporter.stats.items()
                       if name in ("passed", "failed", "error", "skipped", "warnings")}
summary = Summary()
selected = json.loads(sys.argv[3])
exit_code = pytest.main(["-q", "-p", "no:cacheprovider",
                        "-W", "error::pytest.PytestUnhandledThreadExceptionWarning"] + selected,
                       plugins=[summary])
print("DINO_REGRESSION_JSON=" + json.dumps({"exit_code": int(exit_code),
      "counts": summary.counts, "gate_calls": len(gate_calls),
      "hooks_enabled": enable_hooks, "native_qr_image_extraction": "not tested"}))
sys.exit(exit_code)
'''
    process = subprocess.run(
        [sys.executable, "-B", "-c", code, str(PROJECT),
         "true" if enable_hooks else "false", json.dumps(UPSTREAM_TESTS)],
        cwd=UPSTREAM, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, timeout=120,
    )
    marker = "DINO_REGRESSION_JSON="
    summary = next((json.loads(line[len(marker):]) for line in process.stdout.splitlines()
                    if line.startswith(marker)), None)
    return process, summary


@unittest.skipUnless((UPSTREAM / "src/seedsigner/hardware/displays/st7789_mpy.py").is_file(),
                     "Optional pinned upstream sources not fetched; see docs/building.md")
class ActualDriverTests(unittest.TestCase):
    def test_reset_delays_speed_and_full_frame_window(self):
        sleeps = []
        with actual_driver_with_fake_hardware() as (module, devices, gpio_events):
            launcher.configure_plus_display(
                SimpleNamespace(_data={}),
                SimpleNamespace(SETTING__DISPLAY_CONFIGURATION="display_config"),
                module, sleep=sleeps.append,
            )
            display = module.ST7789(_width=240, _height=320)
            self.assertEqual((display.width, display.height), (320, 240))
            self.assertEqual(sleeps[:3], [0.01, 0.01, 0.12])
            self.assertTrue(all(speed == 25_000_000 for speed, _ in devices[0].writes))
            self.assertGreater(len(gpio_events), 0)
            display.spi.writes.clear()
            display.show_image(Image.new("RGB", (320, 240), "white"))
            writes = [data for _, data in display.spi.writes]
            self.assertEqual(writes[:5], [b"\x2a", bytes.fromhex("0000013f"),
                                          b"\x2b", bytes.fromhex("000000ef"), b"\x2c"])
            self.assertEqual(writes[5], b"\xff\xff" * 320 * 240)
            self.assertEqual(len(writes[5]), 153_600)
            for mode, color in (("RGBA", (255, 0, 0, 128)), ("L", 255)):
                display.spi.writes.clear()
                display.show_image(Image.new(mode, (320, 240), color))
                pixel_data = display.spi.writes[-1][1]
                expected_pixel = bytes.fromhex("f800") if mode == "RGBA" else b"\xff\xff"
                self.assertEqual(pixel_data, expected_pixel * 320 * 240)
            display.spi.writes.clear()
            with self.assertRaises(ValueError):
                display.show_image(Image.new("RGB", (240, 240)))
            self.assertEqual(display.spi.writes, [])

    def test_rgb565_packer_matches_independent_reference_random_frame(self):
        rng = random.Random(0xD1A0)
        image = Image.frombytes("RGB", (320, 240), rng.randbytes(320 * 240 * 3))
        reference = bytearray()
        for red, green, blue in image.getdata():
            pixel = ((red >> 3) << 11) | ((green >> 2) << 5) | (blue >> 3)
            reference.extend(pixel.to_bytes(2, "big"))
        self.assertEqual(launcher.rgb565_bytes(image), bytes(reference))


@unittest.skipUnless((UPSTREAM / "tests/test_controller.py").is_file(),
                     "Optional pinned upstream sources and test dependencies required")
class HookedUpstreamRegressionTests(unittest.TestCase):
    def test_upstream_controller_settings_seed_psbt_suite_with_hooks(self):
        process, summary = run_upstream_regression(enable_hooks=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        self.assertIsNotNone(summary, process.stdout)
        self.assertGreaterEqual(summary["counts"].get("passed", 0), 42)
        self.assertGreater(summary["gate_calls"], 0)
        self.assertEqual(summary["native_qr_image_extraction"], "not tested")


if __name__ == "__main__":
    unittest.main()
