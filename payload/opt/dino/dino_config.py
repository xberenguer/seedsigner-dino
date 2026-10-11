"""Bounded, read-once boot configuration shared by both game implementations."""

import configparser
import json
import math
import os
from pathlib import Path
import time
from typing import NamedTuple


BUTTON_NAMES = ("UP", "DOWN", "LEFT", "RIGHT", "CENTER", "KEY1", "KEY2", "KEY3")
BUTTON_ATTRIBUTES = ("KEY_UP", "KEY_DOWN", "KEY_LEFT", "KEY_RIGHT", "KEY_PRESS",
                     "KEY1", "KEY2", "KEY3")
ENTRY_CONFIG_PATH = Path("/mnt/microsd/dino-config.ini")
DISPLAY_PROFILE_PATH = Path("/opt/dino/display-profile.json")
MAX_CONFIG_BYTES = 4096
RELEASE_SECONDS = 0.08
MOUNT_TIMEOUT_SECONDS = 10.0
SD_NOT_READY_WARNING = "SD card not ready; using default entry gesture"


class EntryConfig(NamedTuple):
    buttons: tuple = ("KEY1", "KEY3")
    hold_seconds: float = 2.0

    @property
    def mask(self):
        return sum(1 << BUTTON_NAMES.index(name) for name in self.buttons)

    def native_arguments(self):
        return ["--enter-buttons", "+".join(self.buttons),
                "--hold-seconds", format(self.hold_seconds, ".17g")]

    def pin_set(self, pins):
        return frozenset(getattr(pins, BUTTON_ATTRIBUTES[BUTTON_NAMES.index(name)])
                         for name in self.buttons)


DEFAULT_ENTRY = EntryConfig()


class DisplayProfile(NamedTuple):
    name: str
    width: int
    height: int
    settings_value: str


REGULAR_PROFILE = DisplayProfile("regular", 240, 240, "st7789_240x240")
PLUS_PROFILE = DisplayProfile("plus", 320, 240, "st7789_320x240")
PROFILES = {profile.name: profile for profile in (REGULAR_PROFILE, PLUS_PROFILE)}


def _read_text(path):
    with Path(path).open("rb") as stream:
        data = stream.read(MAX_CONFIG_BYTES + 1)
    if len(data) > MAX_CONFIG_BYTES:
        raise ValueError("Configuration exceeds 4096 bytes")
    return data.decode("utf-8-sig")


def parse_entry_config(text):
    parser = configparser.ConfigParser(interpolation=None, strict=True,
                                       inline_comment_prefixes=("#", ";"))
    parser.read_string(text)
    if parser.defaults() or parser.sections() != ["dino"]:
        raise ValueError("Expected one [dino] section")
    if set(parser["dino"]) - {"enter_buttons", "hold_seconds"}:
        raise ValueError("Unknown Dino configuration key")
    names = tuple(part.strip().upper() for part in
                  parser["dino"].get("enter_buttons", "KEY1+KEY3").split("+"))
    if (not 2 <= len(names) <= 8 or len(set(names)) != len(names)
            or any(name not in BUTTON_NAMES for name in names)):
        raise ValueError("Use two to eight distinct supported button names")
    hold = float(parser["dino"].get("hold_seconds", "2"))
    if not math.isfinite(hold) or not 1 <= hold <= 10:
        raise ValueError("Hold duration must be between 1 and 10 seconds")
    # Canonical order gives native and Python the same immutable configuration.
    return EntryConfig(tuple(name for name in BUTTON_NAMES if name in names), hold)


def wait_for_sd_mount(mount_point=ENTRY_CONFIG_PATH.parent, *, timeout=MOUNT_TIMEOUT_SECONDS,
                      is_mount=os.path.ismount, clock=time.monotonic, sleep=time.sleep):
    """Wait for the stock asynchronous mdev mount, without mounting or writing."""
    deadline = clock() + timeout
    while True:
        try:
            if is_mount(mount_point):
                return True
        except OSError:
            pass
        remaining = deadline - clock()
        if remaining <= 0:
            return False
        sleep(min(0.05, remaining))


def load_entry_config(path=ENTRY_CONFIG_PATH, *, wait_for_mount=False, mount_waiter=None):
    """Return (configuration, warning); never write to the SD card."""
    path = Path(path)
    if wait_for_mount:
        mount_waiter = wait_for_sd_mount if mount_waiter is None else mount_waiter
        if not mount_waiter(path.parent):
            return DEFAULT_ENTRY, SD_NOT_READY_WARNING
    try:
        return parse_entry_config(_read_text(path)), None
    except FileNotFoundError:
        if wait_for_mount and not os.path.ismount(path.parent):
            return DEFAULT_ENTRY, SD_NOT_READY_WARNING
        return DEFAULT_ENTRY, None
    except (OSError, UnicodeError, ValueError, configparser.Error):
        return DEFAULT_ENTRY, "Invalid dino-config.ini; using defaults"


def resolve_profile(profile):
    if isinstance(profile, DisplayProfile) and profile in PROFILES.values():
        return profile
    if isinstance(profile, str) and profile in PROFILES:
        return PROFILES[profile]
    raise ValueError("Display profile must be regular or plus")


def load_display_profile(path=DISPLAY_PROFILE_PATH):
    try:
        data = json.loads(_read_text(path))
    except FileNotFoundError:
        # Retains compatibility with existing Plus payloads and host tests.
        return PLUS_PROFILE
    if not isinstance(data, dict) or set(data) != {"profile"}:
        raise ValueError("Invalid installed display profile")
    return resolve_profile(data["profile"])
