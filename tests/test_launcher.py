"""Input, display ownership, and startup boundary tests without Pi hardware."""

import importlib.util
import sys
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
import unittest

from PIL import Image


LAUNCHER = Path(__file__).resolve().parents[1] / "payload/opt/dino/launcher.py"
sys.path.insert(0, str(LAUNCHER.parent))
spec = importlib.util.spec_from_file_location("dino_launcher", LAUNCHER)
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class Pins:
    KEY_UP, KEY_DOWN, KEY_PRESS, KEY1, KEY2, KEY3 = range(6)
    KEY_LEFT, KEY_RIGHT = 6, 7
    ALL_KEYS = list(range(8))


class FakeTime:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, duration):
        self.now += duration
        if self.now > 8.0:
            raise AssertionError("Gate failed to return")


class FakeButtons:
    def __init__(self, clock, trace):
        self.clock, self.trace = clock, trace
        self.GPIO = SimpleNamespace(LOW=0, input=self.input)
        self.cur_input = Pins.KEY1
        self.cur_input_started = 10
        self.override_ind = True
        self.updated = 0

    def input(self, pin):
        return 0 if pin in self.trace(self.clock()) else 1

    def update_last_input_time(self):
        self.updated += 1


class FakeDisplay:
    def __init__(self):
        self.blits = []

    def blit_buffer(self, data, x, y, width, height):
        assert len(data) == width * height * 2
        self.blits.append((x, y, width, height))


def renderer(width=320):
    return SimpleNamespace(canvas_width=width, canvas_height=240,
                           canvas=Image.new("RGB", (width, 240)),
                           lock=Lock(), disp=FakeDisplay())


class FakeGame:
    def __init__(self, width, height):
        self.width, self.height = width, height
        self.inputs = []

    def update(self, dt, jump, duck):
        self.inputs.append((dt, jump, duck))

    def render(self):
        return Image.new("RGB", (self.width, self.height), "white")


class HoldGateTests(unittest.TestCase):
    def test_chord_requires_continuous_hold_and_release(self):
        gate = launcher.HoldReleaseGate()
        self.assertFalse(gate.update(0, True, True))
        self.assertFalse(gate.update(1.99, True, True))
        self.assertFalse(gate.update(2, True, True))
        self.assertTrue(gate.latched)
        self.assertFalse(gate.update(3, False, False))
        self.assertFalse(gate.update(3.07, False, False))
        self.assertTrue(gate.update(3.081, False, False))

    def test_partial_chord_resets_timer(self):
        gate = launcher.HoldReleaseGate()
        gate.update(0, True, True)
        gate.update(1.9, False, True)
        gate.update(2, True, True)
        gate.update(3.99, True, True)
        self.assertFalse(gate.latched)
        gate.update(4, True, True)
        self.assertTrue(gate.latched)

    def test_any_key_interrupts_release_debounce(self):
        gate = launcher.HoldReleaseGate()
        gate.update(0, True, True)
        gate.update(2, True, True)
        gate.update(3, False, False)
        gate.update(3.05, False, True)
        self.assertFalse(gate.update(3.1, False, False))
        self.assertFalse(gate.update(3.17, False, False))
        self.assertTrue(gate.update(3.181, False, False))

    def test_clock_regression_resets_latched_gesture(self):
        gate = launcher.HoldReleaseGate()
        gate.update(0, True, True)
        gate.update(2, True, True)
        self.assertTrue(gate.latched)
        self.assertFalse(gate.update(1, False, False))
        self.assertFalse(gate.latched)


class HardwareIntegrationTests(unittest.TestCase):
    @staticmethod
    def chord_trace(now):
        return {Pins.KEY1, Pins.KEY3} if now < 2.15 else set()

    def test_game_owns_one_display_then_releases_cleanly(self):
        timer = FakeTime()
        buttons = FakeButtons(timer.clock, self.chord_trace)
        screen = renderer()
        gate = launcher.DinoGate(screen, buttons, Pins, FakeGame, timer.clock, timer.sleep)
        gate.run()
        self.assertGreaterEqual(timer.now, 2.23)
        self.assertEqual(screen.disp.blits[0], (0, 0, 320, 240))
        self.assertTrue(all(blit == (0, 45, 320, 150) for blit in screen.disp.blits[1:]))
        self.assertIsNone(buttons.cur_input)
        self.assertIsNone(buttons.cur_input_started)
        self.assertFalse(buttons.override_ind)
        self.assertEqual(buttons.updated, 1)
        count = len(screen.disp.blits)
        timer.sleep(0.2)
        self.assertEqual(len(screen.disp.blits), count)

    def test_game_exception_stays_inside_gate_until_explicit_chord(self):
        timer = FakeTime()
        buttons = FakeButtons(timer.clock, lambda now: (
            {Pins.KEY1, Pins.KEY3} if 1 <= now < 3.2 else set()
        ))

        class FailingGame(FakeGame):
            def update(self, *args, **kwargs):
                raise RuntimeError("do not display this exception")

        gate = launcher.DinoGate(renderer(), buttons, Pins, FailingGame, timer.clock, timer.sleep)
        gate.run()
        self.assertTrue(gate.game_failed)
        self.assertGreaterEqual(timer.now, 3.28)

    def test_gpio_failure_cannot_count_as_release(self):
        timer = FakeTime()

        class FailingGPIO(FakeButtons):
            def input(self, pin):
                if 2.1 <= self.clock() < 2.3:
                    raise IOError("GPIO unavailable")
                return super().input(pin)

        buttons = FailingGPIO(timer.clock, lambda now: (
            {Pins.KEY1, Pins.KEY3} if now < 4.5 else set()
        ))
        gate = launcher.DinoGate(renderer(), buttons, Pins, FakeGame, timer.clock, timer.sleep)
        gate.run()
        self.assertGreaterEqual(timer.now, 4.58)

    def test_display_write_failure_does_not_select_signer_or_break_game(self):
        timer = FakeTime()
        buttons = FakeButtons(timer.clock, self.chord_trace)
        screen = renderer()

        def failed_write(*args):
            raise IOError("SPI unavailable")

        screen.disp.blit_buffer = failed_write
        gate = launcher.DinoGate(screen, buttons, Pins, FakeGame, timer.clock, timer.sleep)
        gate.run()
        self.assertTrue(gate.display_failed)
        self.assertFalse(gate.game_failed)
        self.assertGreaterEqual(timer.now, 2.23)

    def test_background_change_updates_full_screen(self):
        screen = renderer()
        gate = launcher.DinoGate(screen, None, Pins)
        gate._show(Image.new("RGB", (320, 150), "white"))
        gate._show(Image.new("RGB", (320, 150), "white"))
        gate._show(Image.new("RGB", (320, 150), "black"))
        self.assertEqual(screen.disp.blits, [
            (0, 0, 320, 240), (0, 45, 320, 150), (0, 0, 320, 240),
        ])

    def test_rgb565_matches_known_primary_colors(self):
        image = Image.new("RGB", (3, 1))
        image.putdata([(255, 0, 0), (0, 255, 0), (0, 0, 255)])
        self.assertEqual(launcher.rgb565_bytes(image), bytes.fromhex("f80007e0001f"))

    def test_regular_fallback_fits_screen_and_custom_gesture_suppresses_jump(self):
        from dino_config import EntryConfig
        timer = FakeTime()
        buttons = FakeButtons(timer.clock, lambda now: (
            {Pins.KEY_UP, Pins.KEY_PRESS} if now < 1.15 else set()))
        screen = renderer(240)
        gate = launcher.DinoGate(screen, buttons, Pins, FakeGame, timer.clock, timer.sleep,
                                 entry_config=EntryConfig(("UP", "CENTER"), 1.0))
        gate.run()
        self.assertGreaterEqual(timer.now, 1.23)
        self.assertLess(timer.now, 1.3)
        self.assertEqual(screen.disp.blits[0], (0, 0, 240, 240))
        self.assertTrue(all(blit == (0, 45, 240, 150) for blit in screen.disp.blits[1:]))
        self.assertFalse(any(jump for _, jump, _ in gate.game.inputs))


class StartupHookTests(unittest.TestCase):
    def test_gate_precedes_original_start_and_suppresses_toasts(self):
        events = []

        class Controller:
            def start(self, initial_destination=None):
                events.append(("signer", initial_destination))

            def activate_toast(self, toast):
                events.append(("toast", toast))

        class Gate:
            def __init__(self, *args):
                pass

            def run(self):
                events.append("game")
                controller.activate_toast("hidden")

        singleton = SimpleNamespace(get_instance=lambda: object())
        launcher.install_controller_hooks(Controller, singleton, singleton, Pins, Gate)
        controller = Controller()
        controller.activate_toast("startup hidden")
        controller.start()
        controller.activate_toast("visible")
        self.assertEqual(events, ["game", ("signer", None), ("toast", "visible")])
        # An application restart creates a new controller and enters the same gate.
        controller = Controller()
        controller.start()
        self.assertEqual(events[-2:], ["game", ("signer", None)])

    def test_unexpected_gate_failure_never_calls_original_start(self):
        events = []

        class Controller:
            def start(self, initial_destination=None):
                events.append("signer")

            def activate_toast(self, toast):
                events.append("toast")

        class Gate:
            def __init__(self, *args):
                pass

            def run(self):
                raise RuntimeError("gate failure")

        singleton = SimpleNamespace(get_instance=lambda: object())
        launcher.install_controller_hooks(Controller, singleton, singleton, Pins, Gate)
        controller = Controller()
        with self.assertRaises(RuntimeError):
            controller.start()
        controller.activate_toast("hidden")
        self.assertEqual(events, [])
        self.assertTrue(controller._dino_gate_active)

    def test_upstream_flow_test_destination_bypasses_game(self):
        events = []

        class Controller:
            def start(self, initial_destination=None):
                events.append(initial_destination)

            def activate_toast(self, toast):
                pass

        def unexpected_gate(*args):
            raise AssertionError("Flow tests must not run the game")

        singleton = SimpleNamespace(get_instance=lambda: object())
        launcher.install_controller_hooks(Controller, singleton, singleton, Pins, unexpected_gate)
        Controller().start(initial_destination="test destination")
        self.assertEqual(events, ["test destination"])

    def test_display_profile_and_actual_delays_precede_driver_commands(self):
        events = []

        class Driver:
            def init(self, commands):
                events.append(("commands", self.spi.max_speed_hz))

        module = SimpleNamespace(ST7789=Driver)
        settings = SimpleNamespace(_data={"display_config": "st7789_240x240"})
        constants = SimpleNamespace(SETTING__DISPLAY_CONFIGURATION="display_config")
        launcher.configure_plus_display(settings, constants, module, sleep=lambda dt: events.append(("sleep", dt)))
        module.sleep_ms(120)
        driver = Driver()
        driver.spi = SimpleNamespace(max_speed_hz=40_000_000)
        driver.init([])
        self.assertEqual(settings._data["display_config"], "st7789_320x240")
        self.assertEqual(events, [("sleep", 0.12), ("commands", 25_000_000)])


if __name__ == "__main__":
    unittest.main()
