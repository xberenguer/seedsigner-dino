# SeedSigner Dino

Play Dino at startup, then hold a configurable button combination to enter SeedSigner. The original SeedSigner splash screen remains.

This is an independent community modification, inspired by [SeedConsole](https://github.com/DesobedienteTecnologico/seedconsole). It is not an official SeedSigner release. The button combination is an interface shortcut, not authentication.

**Status: experimental flashable beta.** Download an image below for your screen. Software, ARM runtime, and image-integrity checks are recorded with the release; final physical testing on both screens and an independent security review remain pending. Use disposable test seeds while evaluating this build. See [release status](docs/release-status.md).

## Download and flash

| Screen | Flashable image |
| --- | --- |
| Regular, 240 × 240 | [Download regular IMG](https://github.com/xberenguer/seedsigner-dino/releases/download/v0.1.1-beta/seedsigner-v0.8.7-dino-v0.1.1-beta-regular-pi0.img) |
| Plus, 320 × 240 | [Download Plus IMG](https://github.com/xberenguer/seedsigner-dino/releases/download/v0.1.1-beta/seedsigner-v0.8.7-dino-v0.1.1-beta-plus-pi0.img) |

1. Download the IMG matching your screen and verify it against the release's [SHA256SUMS](https://github.com/xberenguer/seedsigner-dino/releases/download/v0.1.1-beta/SHA256SUMS).
2. In Raspberry Pi Imager, choose **Use custom**, select the IMG, and write it to the intended microSD card. Writing erases that card. Let write verification finish.
3. Boot your Pi Zero. Hold **KEY1 + KEY3 for two seconds**, then release every button to enter SeedSigner through its original splash screen.

[Release assets, source, and verification reports](https://github.com/xberenguer/seedsigner-dino/releases/tag/v0.1.1-beta). The earlier [0.1.0-beta](https://github.com/xberenguer/seedsigner-dino/releases/tag/v0.1.0-beta) remains a source-only preview.

## What it does

```text
Power on → Dino → hold combination, release all buttons
         → original SeedSigner splash → SeedSigner
```

- Uses a native libretro frontend for the GBA Dino game and gpSP emulator.
- Includes a separate Python fallback game if native startup fails.
- Releases game hardware before starting the upstream signer application.
- Keeps game progress in memory; restarting returns to Dino.
- Provides separate regular and Plus screen profiles from one source tree.

Early development used a game and emulator extracted from SeedConsole 4.8.1. This release instead uses the licensed upstream Dino 1.1 ROM and a gpSP core and open BIOS compiled from pinned sources. Their authors retain their respective rights. See [credits](CREDITS.md) and [licensing](docs/licensing.md).

## Versions and hardware

This development target is **SeedSigner 0.8.7 + Dino 0.1.1-beta on Raspberry Pi Zero v1.3**. Other Pi models are unverified.

| Profile | Display | Image name |
| --- | --- | --- |
| `regular` | Original ST7789, 240 × 240 | `seedsigner-v0.8.7-dino-v0.1.1-beta-regular-pi0.img` |
| `plus` | Plus ST7789, 320 × 240 | `seedsigner-v0.8.7-dino-v0.1.1-beta-plus-pi0.img` |

[Hardware details](docs/supported-hardware.md).

## Controls

Button names follow the SeedSigner HAT: `CENTER` is the pressed joystick; `KEY1`, `KEY2`, and `KEY3` are the three side buttons from top to bottom in the normal upright orientation.

| Action | Default native-game control |
| --- | --- |
| Start / jump | `UP` or `KEY1` |
| Duck | `DOWN` |
| Restart after a crash | Wait briefly, then press and release `UP` or `KEY1` |
| Enter SeedSigner | Hold `KEY1` + `KEY3` for 2 seconds, then release **all** buttons |
| Return to Dino | Use SeedSigner's Restart action |

The native game uses Google Dino Advance 1.1 in single-player mode. The fallback game has its own game controls; the SeedSigner entry combination is shared. Completion requires an 80 ms release of every button. A failed or missing native component does not automatically enter SeedSigner.

## Change the entry combination

Edit `dino-config.ini` in the root of the SD card's visible boot partition:

```ini
[dino]
enter_buttons = KEY1+KEY3
hold_seconds = 2
```

Choose 2–8 distinct named buttons and a hold of 1–10 seconds. Save, safely eject, then boot. Configuration is read at startup; no code changes or reflashing are needed. Missing configuration uses defaults. Invalid configuration displays a warning and uses defaults. [Configuration reference](docs/configuration.md).

## Build, review, and test

- [Build instructions](docs/building.md)
- [Reproducibility and review boundary](docs/reproducibility.md)
- [Physical hardware checklist](docs/hardware-testing.md)
- [Troubleshooting and restoration](docs/troubleshooting.md)

The image builder takes a hash-pinned official SeedSigner base and adds an inspectable overlay. Repeated packaging of identical inputs is deterministic. This does **not yet establish** that every executable can be rebuilt independently from its corresponding source, nor that the complete upstream operating system has been reproduced.

Matching build hashes verifies correspondence to the reviewed inputs. It does not replace a security review. See [SECURITY.md](SECURITY.md).

## License and credits

Original project code is GPL-2.0-or-later; see [LICENSE](LICENSE). Third-party components keep their own licenses and notices. The root license does not grant rights to omitted game binaries or relicense upstream components. See [NOTICE](NOTICE), [CREDITS.md](CREDITS.md), and [licensing details](docs/licensing.md).

Contributions are welcome through issues and pull requests. Please read [CONTRIBUTING.md](CONTRIBUTING.md) before changing hardware or signer integration.
