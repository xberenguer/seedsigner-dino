# Troubleshooting and restoration

These steps apply to the experimental regular and Plus images in [release 0.1.1-beta](https://github.com/xberenguer/seedsigner-dino/releases/tag/v0.1.1-beta), and to local builds from the same source.

## Black, skewed, or cropped display

Confirm the physical display and image profile match: regular is 240 × 240; Plus is 320 × 240. The configuration file does not switch drivers. Check power, HAT seating, and the image's completed SD-card write verification. Do not treat a successful flash as proof that the device has booted correctly.

## “Using fallback game”

The native frontend, emulator, ROM, or hardware bridge was unavailable or failed. The fallback is deliberate and does not automatically start SeedSigner. Check the local build manifest and component hashes. Developer diagnostics are kept in bounded RAM storage at `/tmp/dino-native.log`; never post sensitive signer data with logs.

## Entry combination does not work

Hold the top and bottom side buttons (`KEY1+KEY3`) continuously for two seconds, then release every button. If configuration is missing or invalid, those defaults apply. Confirm the file is plain text named exactly `dino-config.ini` in the boot partition root, with a `[dino]` section. Reboot after changes.

Avoid combinations that are difficult to press simultaneously. Changing the combination requires only editing the file; it is not an authentication mechanism.

## The splash takes time

The original SeedSigner splash, fade, and pause are intentionally retained. Signer initialization starts after the game relinquishes the hardware. A missing splash, stuck inputs, or a game still running behind the signer should be reported with the exact image hash and profile.

## Restore the original SeedSigner image

Download the appropriate official image and follow the [upstream SeedSigner instructions](https://github.com/SeedSigner/seedsigner/tree/0.8.7). Verify its provenance/checksum as instructed, then write it to the intended microSD card. Writing replaces the contents of that card.

Restoration removes the Dino startup overlay from that card. Preserve any intentional local settings before overwriting it. Do not copy wallet secrets into bug reports or repository files.
