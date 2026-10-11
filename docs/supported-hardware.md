# Hardware profiles

The initial target is a Raspberry Pi Zero v1.3 with one of the following ST7789 HAT screen configurations. Other Pi models, screens, and wiring are unverified.

| Profile | Logical display | Native GBA game viewport | Driver path |
| --- | --- | --- | --- |
| `regular` | 240 × 240 | 240 × 160, centered at y=40 | Original upstream ST7789 driver with a profile adapter |
| `plus` | 320 × 240 | 320 × 213, centered at y=13 | Upstream `st7789_mpy` driver |

The native game is rendered from its original 240 × 160 frame using nearest sampling. The profiles share source and controls, but use separate frontend builds and image settings. The original regular-screen driver matters: simply shrinking the Plus driver's dimensions is insufficient.

The standard button mapping is:

| Button | Physical header pin |
| --- | --- |
| UP | 31 |
| DOWN | 35 |
| LEFT | 29 |
| RIGHT | 37 |
| CENTER | 33 |
| KEY1 | 40 |
| KEY2 | 38 |
| KEY3 | 36 |

These are physical BOARD pin numbers, not BCM GPIO numbers. Display integration uses BCM25 for DC, BCM27 for RESET, and BCM24 for backlight, with SPI mode 0 at 25 MHz.

## Qualification status

- The earlier Plus development path was exercised during development, but the final splash-restored revision has no complete recorded physical qualification.
- Regular-profile and editable-configuration support are new in this source preview and require physical testing.
- Software tests and emulated timing checks cannot establish LCD appearance, camera operation, or signing reliability.

Record the exact board, HAT, display, image hash, and results using the [hardware checklist](hardware-testing.md) before recommending an image for use.
