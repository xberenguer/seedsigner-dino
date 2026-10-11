# Entry configuration

Edit `dino-config.ini` in the root of the flashed SD card's visible boot partition. The launcher reads it from `/mnt/microsd/dino-config.ini` once at startup. Save the file as plain UTF-8 text, safely eject the card, and restart the device to apply changes.

```ini
[dino]
enter_buttons = KEY1+KEY3
hold_seconds = 2
```

| Setting | Accepted values | Default |
| --- | --- | --- |
| `enter_buttons` | 2–8 distinct names separated by `+` | `KEY1+KEY3` |
| `hold_seconds` | A number from 1 through 10 seconds | `2` |

Button names are case-insensitive: `UP`, `DOWN`, `LEFT`, `RIGHT`, `CENTER`, `KEY1`, `KEY2`, `KEY3`. `CENTER` means pressing the joystick. The three side buttons are `KEY1` at the top, `KEY2` in the middle, and `KEY3` at the bottom in the normal upright orientation.

For example:

```ini
[dino]
enter_buttons = CENTER+KEY3
hold_seconds = 3
```

Hold every configured button continuously for the configured duration, then release **all eight buttons** for at least 80 ms. The release interval is fixed. The entry gesture is shared by the native and fallback games.

Missing configuration uses the default. Invalid configuration produces a brief visible warning and uses the default. Do not treat a typo as a new access restriction: this is a navigation shortcut, not authentication.

The display profile is selected when the image is built. It cannot be changed through this file. Use the regular image for a 240 × 240 screen and the Plus image for a 320 × 240 screen.

This source preview does not provide a flashable image. These instructions describe configuration in images produced by the documented local build.
