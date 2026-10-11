"""Real subprocess IPC and the actual known-working upstream display driver."""
import importlib.util
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch


PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "payload/opt/dino"))
spec = importlib.util.spec_from_file_location(
    "test_bridge_module", PROJECT / "payload/opt/dino/hardware_bridge.py")
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)
launcher_spec = importlib.util.spec_from_file_location(
    "test_bridge_launcher", PROJECT / "payload/opt/dino/launcher.py")
launcher = importlib.util.module_from_spec(launcher_spec)
launcher_spec.loader.exec_module(launcher)


class Display:
    def __init__(self):
        self.rectangles = []

    def blit_buffer(self, *rectangle):
        self.rectangles.append(rectangle)


class ProtocolTests(unittest.TestCase):
    def run_child(self, code, display=None, read_buttons=lambda: 0, timeout=1.0):
        display = Display() if display is None else display
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "native.log"
            result = bridge.run_bridge(
                [sys.executable, "-u", "-c", code], display, read_buttons,
                timeout=timeout, diagnostic_path=log)
            return result, display, log.read_bytes()

    def test_inputs_rectangles_duplicate_frame_and_explicit_exit(self):
        code = r'''
import os,struct,sys
os.write(2,b"core diagnostic\n")
os.write(1,b"INP1")
assert os.read(0,1)==b"\xa1"
packet=b"FRM1"+struct.pack(">H4H",1,2,3,2,1)+bytes.fromhex("f80007e0")
for byte in packet: os.write(1,bytes([byte]))
assert os.read(0,1)==b"\0"
os.write(1,b"FRM1\0\0")
assert os.read(0,1)==b"\0"
sys.exit(42)
'''
        result, display, log = self.run_child(code, read_buttons=lambda: 0xa1)
        self.assertEqual(result, 42)
        self.assertEqual(display.rectangles, [(bytes.fromhex("f80007e0"), 2, 3, 2, 1)])
        self.assertIn(b"core diagnostic", log)
        self.assertIn(b"Native exit: 42", log)

    def test_non_unlock_status_is_preserved(self):
        for status in (0, 1, 7):
            with self.subTest(status=status):
                result, display, log = self.run_child("import sys;sys.exit(%d)" % status)
                self.assertEqual(result, status)
                self.assertEqual(display.rectangles, [])

    def test_malformed_out_of_bounds_oversized_and_truncated_frames_fail(self):
        packets = [b"oops", b"FRM1" + struct.pack(">H", 601),
                   b"FRM1" + struct.pack(">H4H", 1, 319, 0, 2, 1),
                   b"FRM1" + struct.pack(">H4H", 1, 0, 0, 0, 1),
                   b"FRM1" + struct.pack(">H4H", 1, 0, 0, 2, 1) + b"\0",
                   b"FRM1\0"]
        for packet in packets:
            with self.subTest(packet=packet):
                display = Display()
                with self.assertRaises(bridge.BridgeError):
                    self.run_child("import os;os.write(1,%r)" % packet, display=display)
                self.assertEqual(display.rectangles, [])

    def test_all_rectangles_validate_before_any_display_write(self):
        packet = (b"FRM1" + struct.pack(">H4H", 2, 0, 0, 1, 1) + b"\0\0"
                  + struct.pack(">4H", 320, 0, 1, 1))
        display = Display()
        with self.assertRaises(bridge.BridgeError):
            self.run_child("import os;os.write(1,%r)" % packet, display=display)
        self.assertEqual(display.rectangles, [])

    def test_total_frame_limit_prevents_many_full_screen_rectangles(self):
        # Construct in the child to avoid platform command-line argument limits.
        code = r'''
import os,struct
packet=b"FRM1"+struct.pack(">H4H",2,0,0,320,240)+b"\0"*(320*240*2)+struct.pack(">4H",0,0,1,1)
os.write(1,packet)
'''
        display = Display()
        with self.assertRaises(bridge.BridgeError):
            self.run_child(code, display=display)
        self.assertEqual(display.rectangles, [])

    def test_hung_child_is_terminated_and_diagnostics_retained(self):
        children = []

        def spawn(*args, **kwargs):
            process = subprocess.Popen(*args, **kwargs)
            children.append(process)
            return process

        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "native.log"
            started = time.monotonic()
            with self.assertRaises(bridge.BridgeError):
                bridge.run_bridge([sys.executable, "-u", "-c",
                    "import os,time;os.write(2,b'started');time.sleep(60)"],
                    Display(), lambda: 0, timeout=0.15, popen=spawn, diagnostic_path=log)
            self.assertLess(time.monotonic() - started, 3.0)
            self.assertIsNotNone(children[0].poll())
            self.assertIn(b"stopped responding", log.read_bytes())

    def test_stderr_flood_cannot_fill_memory_or_deadlock(self):
        result, _, log = self.run_child(
            "import os;os.write(2,b'x'*100000);os.write(2,b'END');raise SystemExit(1)")
        self.assertEqual(result, 1)
        self.assertLessEqual(len(log), bridge.MAX_DIAGNOSTIC_BYTES)
        self.assertIn(b"END", log)

    def test_final_diagnostics_are_captured_when_stdout_closes_first(self):
        # stdout EOF arrives before the child has written its final counters.
        # wait() must finish and drain stderr before saving the bounded log.
        code = "import os,time;os.close(1);time.sleep(.025);os.write(2,b'FINAL COUNTERS');raise SystemExit(42)"
        result, _, log = self.run_child(code)
        self.assertEqual(result, 42)
        self.assertIn(b"FINAL COUNTERS", log)
        self.assertTrue(log.endswith(b"Native exit: 42\n"))

    def test_button_or_display_failure_never_returns_unlock(self):
        def failed_buttons():
            raise OSError("GPIO unavailable")

        with self.assertRaises(bridge.BridgeError):
            self.run_child("import os;os.write(1,b'INP1');os.read(0,1)",
                           read_buttons=failed_buttons)
        display = Display()
        display.blit_buffer = lambda *args: (_ for _ in ()).throw(OSError("SPI unavailable"))
        packet = b"FRM1" + struct.pack(">H4H", 1, 0, 0, 1, 1) + b"\0\0"
        with self.assertRaises(bridge.BridgeError):
            self.run_child("import os;os.write(1,%r);os.read(0,1)" % packet, display=display)

    def test_small_headers_and_pixels_share_one_bounded_pipe_read(self):
        stdout_read, stdout_write = os.pipe()
        stderr_read, stderr_write = os.pipe()
        reader = None
        try:
            with os.fdopen(stdout_read, "rb", buffering=0) as stdout, \
                    os.fdopen(stderr_read, "rb", buffering=0) as stderr:
                process = SimpleNamespace(stdout=stdout, stderr=stderr)
                reader = bridge._Reader(process, bridge._Diagnostics(None))
                chunks = [b"FRM1", struct.pack(">H", 20)]
                for x in range(20):
                    chunks.extend([struct.pack(">4H", x, 0, 1, 1), b"\x12\x34"])
                chunks.append(b"INP1")
                os.write(stdout_write, b"".join(chunks))
                original_read = os.read
                with patch.object(bridge.os, "read", wraps=original_read) as read:
                    for chunk in chunks:
                        self.assertEqual(reader.read(len(chunk), time.monotonic() + 1), chunk)
                    self.assertEqual(read.call_count, 1)
                    self.assertEqual(read.call_args.args[1], bridge.PIPE_READ_BYTES)
        finally:
            if reader is not None:
                reader.close()
            os.close(stdout_write)
            os.close(stderr_write)

    def test_buffered_data_still_obeys_frame_deadline(self):
        reader = object.__new__(bridge._Reader)
        reader.buffer, reader.offset = b"already queued", 0
        with self.assertRaises(bridge.BridgeError):
            reader.read(1, time.monotonic() - 1)

    def test_regular_screen_bounds_and_rectangle_limit(self):
        display = Display()
        display.width, display.height = 240, 240
        good = (b"FRM1" + struct.pack(">H4H", 1, 239, 239, 1, 1) + b"\xf8\x00")
        status, _, _ = self.run_child(
            "import os;os.write(1,%r);assert os.read(0,1)==b'\\0';raise SystemExit(42)" % good,
            display=display)
        self.assertEqual(status, 42)
        self.assertEqual(display.rectangles, [(b"\xf8\x00", 239, 239, 1, 1)])
        for packet in (b"FRM1" + struct.pack(">H4H", 1, 240, 0, 1, 1),
                       b"FRM1" + struct.pack(">H", 451)):
            display.rectangles.clear()
            with self.assertRaises(bridge.BridgeError):
                self.run_child("import os;os.write(1,%r)" % packet, display=display)
            self.assertEqual(display.rectangles, [])


class ActualPythonHardwareTests(unittest.TestCase):
    def test_actual_regular_driver_adapter_messages_rectangles_and_cleanup(self):
        from dino_config import REGULAR_PROFILE
        helper_spec = importlib.util.spec_from_file_location(
            "regular_driver_helper", PROJECT / "tests/test_upstream_integration.py")
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)
        source = helper.UPSTREAM / "src/seedsigner/hardware/displays/ST7789.py"
        if not source.is_file():
            self.skipTest("Pinned SeedSigner source required; set SEEDSIGNER_SOURCE")
        events = []
        with helper.actual_driver_with_fake_hardware() as (plus_module, devices, gpio_events):
            gpio = plus_module.GPIO
            gpio.IN, gpio.PUD_UP = 1, 22
            gpio.setup = lambda *args, **kwargs: gpio_events.append(("setup", args))
            gpio.input = lambda pin: gpio.LOW if pin in (31, 40, 36) else gpio.HIGH
            gpio.cleanup = lambda pins: events.append(("cleanup", tuple(pins)))
            plus_module.spidev.SpiDev.writebytes = plus_module.spidev.SpiDev.writebytes2
            plus_module.spidev.SpiDev.close = lambda self: events.append("spi closed")
            name = "dino_actual_regular_ST7789"
            spec = importlib.util.spec_from_file_location(name, source)
            module = importlib.util.module_from_spec(spec)
            with patch.dict(sys.modules, {name: module}):
                spec.loader.exec_module(module)
                modules = {"seedsigner.hardware.displays": SimpleNamespace(ST7789=module)}
                with patch.dict(sys.modules, modules), patch.object(module.time, "sleep", lambda dt: None):
                    with launcher.PythonHardware(REGULAR_PROFILE) as hardware:
                        self.assertEqual(hardware.read_mask(), 161)
                        self.assertEqual((hardware.display.width, hardware.display.height), (240, 240))
                        hardware.show_message("Starting Dino...")
                        self.assertEqual(len(devices[0].writes[-1][1]), 240 * 240 * 2)
                        devices[0].writes.clear()
                        hardware.display.blit_buffer(b"\xf8\x00", 239, 239, 1, 1)
                        self.assertEqual([data for _, data in devices[0].writes], [
                            b"\x2a", b"\0", b"\xef", b"\0", b"\xef",
                            b"\x2b", b"\0", b"\xef", b"\0", b"\xef",
                            b"\x2c", b"\xf8\x00"])
                        self.assertTrue(all(speed == 25_000_000 for speed, _ in devices[0].writes))
                self.assertEqual(events, ["spi closed", ("cleanup",
                    launcher.PythonHardware.BUTTON_PINS + launcher.PythonHardware.OUTPUT_PINS)])

    def test_actual_upstream_driver_pin_mapping_messages_and_cleanup(self):
        helper_spec = importlib.util.spec_from_file_location(
            "bridge_actual_driver_tests", PROJECT / "tests/test_upstream_integration.py")
        helper = importlib.util.module_from_spec(helper_spec)
        helper_spec.loader.exec_module(helper)
        if not (helper.UPSTREAM / "src/seedsigner/hardware/displays/st7789_mpy.py").is_file():
            self.skipTest("Pinned SeedSigner source required; set SEEDSIGNER_SOURCE")
        events = []
        with helper.actual_driver_with_fake_hardware() as (driver_module, devices, gpio_events):
            gpio = driver_module.GPIO
            gpio.IN, gpio.PUD_UP = 1, 22
            gpio.setup = lambda *args, **kwargs: gpio_events.append(("setup", args))
            gpio.input = lambda pin: gpio.LOW if pin in (31, 40, 36) else gpio.HIGH
            gpio.cleanup = lambda pins: events.append(("cleanup", tuple(pins)))
            driver_module.spidev.SpiDev.close = lambda self: events.append("spi closed")
            def premature_settings():
                raise AssertionError("Settings must wait until signer handoff")

            modules = {
                "seedsigner.models.settings": SimpleNamespace(
                    Settings=SimpleNamespace(get_instance=premature_settings),
                    SettingsConstants=SimpleNamespace(SETTING__DISPLAY_CONFIGURATION="display_config")),
                "seedsigner.hardware.displays": SimpleNamespace(st7789_mpy=driver_module),
            }
            original_configure = launcher.configure_plus_display

            def configure(*args):
                original_configure(*args, sleep=lambda duration: None)

            with patch.dict(sys.modules, modules), patch.object(sys, "path", list(sys.path)), \
                    patch.object(launcher, "configure_plus_display", configure):
                with launcher.PythonHardware() as hardware:
                    self.assertEqual(hardware.read_mask(), 1 | 32 | 128)
                    self.assertEqual((hardware.display.width, hardware.display.height), (320, 240))
                    self.assertTrue(any(event == ("setup", (hardware.BUTTON_PINS, gpio.IN))
                                        for event in gpio_events))
                    hardware.show_message("Starting Dino...")
                    self.assertEqual(len(devices[0].writes[-1][1]), 320 * 240 * 2)
                    devices[0].writes.clear()
                    code = r'''
import os,struct
os.write(1,b"INP1")
assert os.read(0,1)==b"\xa1"
os.write(1,b"FRM1"+struct.pack(">H4H",1,2,3,2,1)+bytes.fromhex("f80007e0"))
assert os.read(0,1)==b"\0"
raise SystemExit(42)
'''
                    status, _, _ = ProtocolTests().run_child(
                        code, display=hardware.display, read_buttons=hardware.read_mask)
                    self.assertEqual(status, 42)
                    self.assertEqual([data for _, data in devices[0].writes], [
                        b"\x2a", bytes.fromhex("00020003"),
                        b"\x2b", bytes.fromhex("00030003"), b"\x2c",
                        bytes.fromhex("f80007e0")])
                    self.assertTrue(all(speed == 25_000_000
                                        for speed, _ in devices[0].writes))
                self.assertEqual(events, ["spi closed", (
                    "cleanup", launcher.PythonHardware.BUTTON_PINS + launcher.PythonHardware.OUTPUT_PINS)])


if __name__ == "__main__":
    unittest.main()
