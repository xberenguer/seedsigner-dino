# Release status

## 0.1.1-beta experimental images — 2026-10-11

The release provides flashable Pi Zero images for the regular and Plus displays:

```text
seedsigner-v0.8.7-dino-v0.1.1-beta-regular-pi0.img
seedsigner-v0.8.7-dino-v0.1.1-beta-plus-pi0.img
```

Download them from the [0.1.1-beta release](https://github.com/xberenguer/seedsigner-dino/releases/tag/v0.1.1-beta). Match the image to your display and verify its SHA-256 checksum before writing it to a test microSD card.

| Area | Status |
| --- | --- |
| Upstream target | Official SeedSigner 0.8.7 Pi Zero image, checked against its pinned hash and signature |
| Startup / splash | Explicit hold-and-release transition; original SeedSigner splash retained |
| Regular / Plus profiles | Implemented; physical qualification pending for these exact images |
| Boot configuration | Editable `dino-config.ini`; mount wait and defaults covered by software tests |
| Native executables | ARMv6 frontends, gpSP and open BIOS built from pinned sources; build evidence accompanies the release |
| Game | Official Google Dino Advance 1.1 binary; MIT and BSD notices and corresponding tagged source included |
| Image assembly | Deterministic overlay assembly and image readback checks; see the attached manifests and validation evidence |
| Full OS rebuild | Not performed; the official signed OS image is a trusted binary input |
| Independent clean rebuild | Pending |
| Hardware checklist | Pending for both profiles |
| Independent security audit | Not performed |

This is an experimental beta for review and disposable test seeds. Passing software checks does not establish that the device boots, displays correctly, runs at full speed, or signs transactions safely on physical hardware. Complete the [hardware checklist](hardware-testing.md) before relying on either profile.

Source archives, license notices, input pins, checksums, and build/inspection evidence are published alongside the images. See [licensing](licensing.md) and [reproducibility](reproducibility.md) for what is supplied and which binary inputs are trusted.

The earlier [0.1.0-beta release](https://github.com/xberenguer/seedsigner-dino/releases/tag/v0.1.0-beta) remains a source-only preview. Its lack of IMG assets is intentional; use 0.1.1-beta for flashing.
