# Licenses and distributed inputs

Original SeedSigner Dino code is GPL-2.0-or-later. Third-party material retains its own license. The root `LICENSE` is not a blanket license for a complete IMG.

| Component | License / release boundary |
| --- | --- |
| Original frontend, launcher, bridge, configuration, build tooling | GPL-2.0-or-later |
| libretro API header | Embedded MIT notice |
| Chromium fallback material | BSD-3-Clause; full notice and exact provenance retained in the payload |
| Adapted ST7789 initialization | MIT; retained in `native/NOTICE.txt` |
| gpSP and open BIOS | GPL-2.0-or-later with upstream credits; compiled from pinned source |
| libtonc headers for the BIOS | MIT; pinned devkitPro source |
| Google-Dino-GBA 1.1 game code | MIT; official upstream ROM is a trusted binary input, with source and notices supplied |
| GBA game asset notices | Chromium / ChromiumOS BSD-3-Clause texts distributed by upstream 1.1 |
| Game runtime / libraries | gba-toolchain zlib, tonclib MIT, Maxmod ISC |
| SeedSigner 0.8.7 application | MIT; application source and notices supplied |
| OS / firmware / fonts | Separately licensed components; see the OS source collection's manifests and notices |

## Public game version

Public 0.1.1-beta images use [Google-Dino-GBA 1.1](https://github.com/fritzem/Google-Dino-GBA/releases/tag/1.1), source commit `dca6780d60aa7816da89b797c5a64a77f9bfd334`. This version includes Ethan Fritz's MIT license and Chromium/ChromiumOS BSD notices. Their retention does not imply Google endorsement.

```text
Google-Dino-Advance.gba — official upstream 1.1 release
Size: 109084 bytes
SHA-256: d08239bea3044af0b0224cb5436221fec59e1ea3ba811ed0ec17212683a2cb81
```

The ROM is copied from the verified official release, not rebuilt here. The licensed source and pinned build-submodule reference are supplied for inspection. An independent source-to-ROM match and the exact versions of all libraries in that prebuilt ROM have not been demonstrated. The root notices retain the known runtime/library credits.

Early private development used 1.0.1, whose archived source lacks a license file. That historical ROM is not distributed by the public images. The earlier source-only 0.1.0-beta tag remains a separate snapshot.

## Source and notices

Download the source assets alongside the IMG, including the separate [OS corresponding-source bundle](corresponding-source.md). The Dino source/build recipe does not replace sources and notices for Linux, BusyBox, glibc, or other OS components.

The [consolidated stock OS, application and font notices](third-party-notices.txt) are also included inside each IMG at `/opt/dino/licenses/OS-and-font-notices.txt`. They retain target package license texts, application/translation notices, and the full OFL/Apache font licenses. The OS bundle preserves Buildroot's original warnings together with supplemental license files resolving its missing license-file declarations.

Retain archives, applied patches, configurations, build scripts, and applicable notices if redistributing an image. Review the collector's manifest and warnings rather than treating its output as a legal certification. Experimental hardware status and pending independent reproducibility do not change component licenses.
