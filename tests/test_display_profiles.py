"""Real rectangle bounds and driver interface checks without physical hardware."""
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "payload/opt/dino"))
import launcher
from display_hardware import RegularDisplayAdapter


class RegularAdapterTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.spi = SimpleNamespace(writebytes2=lambda data: self.events.append(("pixels", bytes(data))))
        self.driver = SimpleNamespace(
            width=240, height=240, _spi=self.spi, _dc=22,
            SetWindows=lambda *window: self.events.append(("window", window)))
        self.gpio = SimpleNamespace(HIGH=1,
                                   output=lambda *args: self.events.append(("gpio", args)))
        self.display = RegularDisplayAdapter(self.driver, self.gpio, launcher.rgb565_bytes)

    def test_bottom_right_rectangle_uses_exclusive_ends_and_rgb565_bytes(self):
        self.display.blit_buffer(b"\xf8\x00", 239, 239, 1, 1)
        self.assertEqual(self.events, [("window", (239, 239, 240, 240)),
                                       ("gpio", (22, 1)), ("pixels", b"\xf8\x00")])
        self.assertIs(self.display.spi, self.spi)

    def test_bad_rectangles_never_write_hardware(self):
        for args in ((b"\0\0", 240, 0, 1, 1), (b"\0\0", -1, 0, 1, 1),
                     (b"\0\0", 0, 239, 1, 2), (b"\0", 0, 0, 1, 1),
                     (b"", 0, 0, 0, 1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.display.blit_buffer(*args)
        self.assertEqual(self.events, [])

    def test_full_image_is_regular_size_and_packs_primary_color(self):
        self.display.show_image(Image.new("RGB", (240, 240), "red"))
        self.assertEqual(self.events[0], ("window", (0, 0, 240, 240)))
        self.assertEqual(self.events[-1], ("pixels", b"\xf8\x00" * 240 * 240))
        self.events.clear()
        with self.assertRaises(ValueError):
            self.display.show_image(Image.new("RGB", (320, 240)))
        self.assertEqual(self.events, [])

    def test_regular_initialization_sets_clock_before_first_command(self):
        events = []

        class Driver:
            def init(self):
                events.append(self._spi.max_speed_hz)

        module = SimpleNamespace(ST7789=Driver)
        settings = SimpleNamespace(_data={})
        constants = SimpleNamespace(SETTING__DISPLAY_CONFIGURATION="display_config")
        launcher.configure_regular_display(settings, constants, module)
        driver = Driver()
        driver._spi = SimpleNamespace(max_speed_hz=40_000_000)
        driver.init()
        self.assertEqual(events, [25_000_000])
        self.assertEqual(settings._data["display_config"], "st7789_240x240")


if __name__ == "__main__":
    unittest.main()
