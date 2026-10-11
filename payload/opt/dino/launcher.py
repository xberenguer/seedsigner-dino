#!/usr/bin/env python3
"""Original SeedConsole ROM gate for the SeedSigner 0.8.7 application.

This is an interface gate, not authentication. No game state is written to disk.
The unique entrypoint also makes upstream's execv-based Restart return to Dino.
"""

import sys
import time
from pathlib import Path
from threading import Lock
from types import SimpleNamespace

from dino_config import (DEFAULT_ENTRY, PLUS_PROFILE, RELEASE_SECONDS,
                         load_display_profile, load_entry_config, resolve_profile)
from display_hardware import RegularDisplayAdapter

DISPLAY_PROFILE = "st7789_320x240"
SPI_SPEED_HZ = 25_000_000
VIEWPORT_WIDTH = 320
VIEWPORT_HEIGHT = 150
FRAME_INTERVAL = 1.0 / 20.0
POLL_INTERVAL = 0.01
NATIVE_ROOT = Path("/opt/dino/native")
NATIVE_UNLOCK_EXIT = 42


def run_native_gate(hardware_factory=None, bridge_runner=None,
                    fallback_factory=None, sleep=time.sleep, *, profile=PLUS_PROFILE,
                    entry_config=DEFAULT_ENTRY, config_warning=None):
    """Own known-working HAT hardware until an explicit native/fallback gesture.

    Native failure returns to the first image's playable game on the same driver.
    It never automatically starts the signer or leaves a silent retry loop.
    """
    profile = resolve_profile(profile)
    if hardware_factory is None:
        hardware_factory = lambda: PythonHardware(profile)
    if bridge_runner is None:
        from hardware_bridge import run_bridge
        bridge_runner = run_bridge
    if fallback_factory is None:
        fallback_factory = lambda hardware: DinoGate(
            hardware.renderer, hardware.buttons, hardware.pins,
            entry_config=entry_config)
    command = [str(NATIVE_ROOT / "dino-native"),
               "--bridge",
               "--core", str(NATIVE_ROOT / "gpsp_libretro.so"),
               "--rom", str(NATIVE_ROOT / "Google-Dino-Advance.gba"),
               "--display-width", str(profile.width)] + entry_config.native_arguments()
    with hardware_factory() as hardware:
        if config_warning:
            hardware.show_message("Invalid Dino config", "Using default entry gesture")
            sleep(1.5)
        hardware.show_message("Starting Dino...")
        try:
            result = bridge_runner(command, hardware.display, hardware.read_mask)
        except Exception:
            # The bridge has already stopped the child. Its bounded diagnostics
            # remain in /tmp/dino-native.log, never the SD card.
            result = None
        if result == NATIVE_UNLOCK_EXIT:
            return
        hardware.show_message("Using fallback game", "Native game unavailable")
        sleep(0.75)
        fallback_factory(hardware).run()


class PythonHardware:
    """A single ST7789/GPIO owner without signer UI singletons or threads."""

    BUTTON_PINS = (31, 35, 29, 37, 33, 40, 38, 36)
    OUTPUT_PINS = (22, 13, 18)

    def __init__(self, profile=PLUS_PROFILE):
        self.profile = resolve_profile(profile)
        self.display, self.gpio = None, None
        self.pins = SimpleNamespace(
            KEY_UP=31, KEY_DOWN=35, KEY_LEFT=29, KEY_RIGHT=37,
            KEY_PRESS=33, KEY1=40, KEY2=38, KEY3=36,
            ALL_KEYS=self.BUTTON_PINS)

    def __enter__(self):
        from PIL import Image
        upstream_path = str(Path("/opt/src"))
        if upstream_path not in sys.path:
            sys.path.insert(0, upstream_path)
        # Direct construction needs only the existing driver. Real Settings,
        # Controller, Renderer and HardwareButtons wait until explicit entry.
        if self.profile == PLUS_PROFILE:
            from seedsigner.hardware.displays import st7789_mpy as driver_module
            configure = configure_plus_display
        else:
            from seedsigner.hardware.displays import ST7789 as driver_module
            configure = configure_regular_display
        configure(SimpleNamespace(_data={}),
                  SimpleNamespace(SETTING__DISPLAY_CONFIGURATION="display_config"),
                  driver_module)
        self.gpio = driver_module.GPIO
        try:
            if self.profile == PLUS_PROFILE:
                self.display = driver_module.ST7789(_width=240, _height=320)
            else:
                original = driver_module.ST7789(_width=240, _height=240)
                self.display = RegularDisplayAdapter(original, self.gpio, rgb565_bytes)
            self.gpio.setup(self.BUTTON_PINS, self.gpio.IN,
                            pull_up_down=self.gpio.PUD_UP)
            self.buttons = SimpleNamespace(
                GPIO=self.gpio, cur_input=None, cur_input_started=None,
                override_ind=False, update_last_input_time=lambda: None)
            self.renderer = SimpleNamespace(
                canvas_width=self.profile.width, canvas_height=self.profile.height,
                canvas=Image.new("RGB", (self.profile.width, self.profile.height)),
                lock=Lock(), disp=self.display)
            return self
        except BaseException:
            self.close()
            raise

    def read_mask(self):
        return sum(1 << bit for bit, pin in enumerate(self.BUTTON_PINS)
                   if self.gpio.input(pin) == self.gpio.LOW)

    def show_message(self, message, detail=None):
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (self.profile.width, self.profile.height), "black")
        draw = ImageDraw.Draw(image)
        draw.text((24, 100), message, fill="white")
        if detail:
            draw.text((24, 124), detail, fill="white")
        self.display.show_image(image)

    def close(self):
        if self.display is not None:
            try:
                self.display.spi.close()
            except Exception:
                pass
        if self.gpio is not None:
            try:
                self.gpio.output(18, self.gpio.LOW)
            except Exception:
                pass
            try:
                self.gpio.cleanup(self.BUTTON_PINS + self.OUTPUT_PINS)
            except Exception:
                pass

    def __exit__(self, exc_type, exc, traceback):
        self.close()


class HoldReleaseGate:
    """Accept a continuous chord followed by a debounced release of every key."""

    def __init__(self, hold_seconds=2.0, release_seconds=RELEASE_SECONDS):
        self.hold_seconds = hold_seconds
        self.release_seconds = release_seconds
        self.reset()

    def reset(self):
        self.hold_started = None
        self.release_started = None
        self.latched = False
        self.complete = False
        self.previous = None

    def update(self, now, combo_held, any_held):
        if self.previous is not None and now < self.previous:
            self.reset()
        self.previous = now
        if self.complete:
            return True
        if not self.latched:
            if not combo_held:
                self.hold_started = None
            elif self.hold_started is None:
                self.hold_started = now
            elif now - self.hold_started >= self.hold_seconds:
                self.latched = True
        if self.latched:
            if any_held:
                self.release_started = None
            elif self.release_started is None:
                self.release_started = now
            elif now - self.release_started >= self.release_seconds:
                self.complete = True
        return self.complete


def read_pressed(buttons, pins):
    """Read simultaneous inputs directly; upstream wait_for is intentionally unused."""
    gpio = buttons.GPIO
    return frozenset(pin for pin in pins.ALL_KEYS if gpio.input(pin) == gpio.LOW)


def reset_button_state(buttons):
    buttons.cur_input = None
    buttons.cur_input_started = None
    buttons.override_ind = False
    buttons.update_last_input_time()


def rgb565_bytes(image):
    """Pack RGB565 in SPI byte order using native Pillow operations.

    The deprecated BGR;16 image mode is unavailable in newer Pillow releases.
    Lookup tables avoid both that dependency and a slow Python per-pixel loop.
    """
    from PIL import Image, ImageChops
    red, green, blue = image.split()
    high = ImageChops.add(red.point(_RED_HIGH), green.point(_GREEN_HIGH))
    low = ImageChops.add(green.point(_GREEN_LOW), blue.point(_BLUE_LOW))
    return Image.merge("LA", (high, low)).tobytes()


_RED_HIGH = [value & 0xf8 for value in range(256)]
_GREEN_HIGH = [value >> 5 for value in range(256)]
_GREEN_LOW = [(value & 0x1c) << 3 for value in range(256)]
_BLUE_LOW = [value >> 3 for value in range(256)]


class DinoGate:
    """One synchronous game/display owner, relinquished before signer startup."""

    def __init__(self, renderer, buttons, pins, game_factory=None,
                 clock=time.monotonic, sleep=time.sleep, *, entry_config=DEFAULT_ENTRY):
        self.renderer = renderer
        self.buttons = buttons
        self.pins = pins
        self.game_factory = game_factory
        self.clock = clock
        self.sleep = sleep
        self.entry_config = entry_config
        self.entry_pins = entry_config.pin_set(pins)
        if (renderer.canvas_width, renderer.canvas_height) not in ((240, 240), (320, 240)):
            raise ValueError("Unsupported game display dimensions")
        self.viewport_width = renderer.canvas_width
        self.viewport_height = VIEWPORT_HEIGHT
        self.viewport_y = (renderer.canvas_height - self.viewport_height) // 2
        self.gate = HoldReleaseGate(hold_seconds=entry_config.hold_seconds)
        self.game = None
        self.game_failed = False
        self.display_failed = False
        self.background = None

    def _new_game(self):
        if self.game_factory is None:
            from dino_game import DinoGame
            self.game_factory = DinoGame
        self.game = self.game_factory(width=self.viewport_width, height=self.viewport_height)
        self.game_failed = False

    def _error_image(self):
        from PIL import Image, ImageDraw
        image = Image.new("RGB", (self.viewport_width, self.viewport_height), "white")
        draw = ImageDraw.Draw(image)
        draw.text((self.viewport_width // 2 - 48, 55), "Game unavailable", fill="black")
        draw.text((self.viewport_width // 2 - 60, 78), "Press UP to try again", fill="black")
        return image

    def _show(self, image):
        if image.mode != "RGB" or image.size != (self.viewport_width, self.viewport_height):
            raise ValueError("Unexpected game viewport")
        if (self.renderer.canvas_width, self.renderer.canvas_height) != (self.viewport_width, 240):
            raise ValueError("Unexpected display dimensions")
        background = image.getpixel((0, 0))
        with self.renderer.lock:
            full_frame = background != self.background
            if full_frame:
                self.renderer.canvas.paste(background, (0, 0, self.viewport_width, 240))
            self.renderer.canvas.paste(image, (0, self.viewport_y))
            if full_frame:
                frame, y = self.renderer.canvas, 0
            else:
                frame, y = image, self.viewport_y
            self.renderer.disp.blit_buffer(
                rgb565_bytes(frame), 0, y, frame.width, frame.height,
            )
            self.background = background

    def run(self):
        try:
            self._new_game()
        except Exception:
            self.game_failed = True
        previous = self.clock()
        next_frame = previous
        jump_was_held = False
        while True:
            now = self.clock()
            dt = max(0.0, min(now - previous, 0.25))
            previous = now
            try:
                pressed = read_pressed(self.buttons, self.pins)
            except Exception:
                # Never infer a release or an unlock from failed GPIO reads.
                self.gate.reset()
                self.sleep(POLL_INTERVAL)
                continue
            combo_held = self.entry_pins <= pressed
            if self.gate.update(now, combo_held=combo_held, any_held=bool(pressed)):
                reset_button_state(self.buttons)
                return
            gameplay_pressed = (pressed - self.entry_pins
                                if combo_held or self.gate.latched else pressed)
            jump = (self.pins.KEY_UP in gameplay_pressed
                    or self.pins.KEY_PRESS in gameplay_pressed)
            duck = self.pins.KEY_DOWN in gameplay_pressed
            if self.game_failed:
                if jump and not jump_was_held:
                    try:
                        self._new_game()
                    except Exception:
                        self.game_failed = True
            else:
                try:
                    self.game.update(dt, jump=jump, duck=duck)
                except Exception:
                    # A game failure cannot select the signing interface.
                    self.game_failed = True
            jump_was_held = jump
            if now >= next_frame:
                if not self.game_failed:
                    try:
                        image = self.game.render()
                    except Exception:
                        self.game_failed = True
                if self.game_failed:
                    image = self._error_image()
                try:
                    self._show(image)
                except Exception:
                    # A failed display write is separate from a game failure. Retry
                    # drawing on subsequent frames and never change the unlock state.
                    self.display_failed = True
                else:
                    self.display_failed = False
                next_frame = now + FRAME_INTERVAL
            self.sleep(POLL_INTERVAL)


def configure_plus_display(settings, settings_constants, driver_module, sleep=time.sleep):
    # Override only RAM, before Renderer construction. set_value() would write settings.
    settings._data[settings_constants.SETTING__DISPLAY_CONFIGURATION] = DISPLAY_PROFILE
    # The upstream CPython compatibility fallback is a no-op, including the documented
    # 120ms reset delay. Restore actual hardware timing before initialization.
    driver_module.sleep_ms = lambda milliseconds: sleep(milliseconds / 1000.0)
    driver = driver_module.ST7789
    if not getattr(driver, "_dino_timing_installed", False):
        original_init = driver.init

        def initialize_at_safe_speed(self, commands):
            # __post_init__ creates SPI before hard_reset and calls init twice. This
            # assignment precedes its first SPI command and retains the existing driver.
            self.spi.max_speed_hz = SPI_SPEED_HZ
            return original_init(self, commands)

        def show_full_image(self, image, x_start=0, y_start=0):
            if image.size != (self.width, self.height):
                raise ValueError("Image must match display dimensions")
            if x_start != 0 or y_start != 0:
                raise ValueError("Full display image must start at the origin")
            # Original show_image passes width/height as inclusive end coordinates,
            # selecting 321x241 pixels for a 320x240 frame. blit_buffer correctly
            # subtracts one and is already used for the game's rectangular updates.
            self.blit_buffer(rgb565_bytes(image.convert("RGB")),
                             x_start, y_start, self.width, self.height)

        driver.init = initialize_at_safe_speed
        driver.show_image = show_full_image
        driver._dino_timing_installed = True


def configure_regular_display(settings, settings_constants, driver_module, sleep=time.sleep):
    """Use upstream's regular driver, with a bounded SPI speed before commands."""
    settings._data[settings_constants.SETTING__DISPLAY_CONFIGURATION] = "st7789_240x240"
    driver = driver_module.ST7789
    if not getattr(driver, "_dino_regular_timing_installed", False):
        original_init = driver.init

        def initialize_at_safe_speed(self):
            self._spi.max_speed_hz = SPI_SPEED_HZ
            return original_init(self)

        driver.init = initialize_at_safe_speed
        driver._dino_regular_timing_installed = True


def install_controller_hooks(controller_class, renderer_class, buttons_class,
                             pins, gate_factory=DinoGate):
    if getattr(controller_class, "_dino_hooks_installed", False):
        return
    original_start = controller_class.start
    original_activate_toast = controller_class.activate_toast
    # The SD watcher starts during configure_instance, before start() is entered.
    controller_class._dino_gate_active = True

    def start_with_game(self, initial_destination=None):
        if initial_destination is None:
            self._dino_gate_active = True
            gate_factory(
                renderer_class.get_instance(), buttons_class.get_instance(), pins,
            ).run()
        self._dino_gate_active = False
        return original_start(self, initial_destination=initial_destination)

    def activate_toast_after_game(self, toast_manager_thread):
        if self._dino_gate_active:
            return
        return original_activate_toast(self, toast_manager_thread)

    controller_class.start = start_with_game
    controller_class.activate_toast = activate_toast_after_game
    controller_class._dino_hooks_installed = True


def main(argv=None):
    profile = load_display_profile()
    entry_config, warning = load_entry_config()
    run_native_gate(profile=profile, entry_config=entry_config, config_warning=warning)
    upstream_path = str(Path("/opt/src"))
    if upstream_path not in sys.path:
        sys.path.insert(0, upstream_path)
    from seedsigner.models.settings import Settings, SettingsConstants
    if profile == PLUS_PROFILE:
        from seedsigner.hardware.displays import st7789_mpy
        configure_plus_display(Settings.get_instance(), SettingsConstants, st7789_mpy)
    else:
        from seedsigner.hardware.displays import ST7789
        configure_regular_display(Settings.get_instance(), SettingsConstants, ST7789)
    import main as upstream_main
    upstream_main.main(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    main()
