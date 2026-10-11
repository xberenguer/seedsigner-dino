# Credits

SeedSigner Dino combines existing open-source work with a lightweight frontend and startup integration. It is not an official upstream release, and these credits do not imply endorsement.

| Project / people | Contribution and provenance |
| --- | --- |
| [SeedConsole — DesobedienteTecnologico and contributors](https://github.com/DesobedienteTecnologico/seedconsole) | Inspiration and original known-working game/emulator setup. Early development used binaries extracted from SeedConsole 4.8.1. Public 0.1.1-beta images use a newly compiled emulator and the official Google-Dino-GBA 1.1 ROM instead. |
| [Google-Dino-GBA — Ethan Fritz](https://github.com/fritzem/Google-Dino-GBA/tree/1.1) | GBA Dino game. The official 1.1 ROM is a hash-verified binary input. Its source tag is `dca6780d60aa7816da89b797c5a64a77f9bfd334`, with MIT and Chromium/ChromiumOS BSD notices retained. No source-to-ROM match is claimed. Historical 1.0.1 is not distributed. |
| [gpSP — Exophase, libretro, and contributors](https://github.com/libretro/gpsp) | GBA emulator compiled from pinned commit `e554360dd3ed283696fc607877024a219248b735`, under GPL-2.0-or-later. The source and build recipe accompany the release. No byte-for-byte match to the earlier SeedConsole binary is claimed. |
| Normmatt and the VBA / VBA-M teams | Authors credited by gpSP's embedded open BIOS. No proprietary Nintendo BIOS is supplied. |
| [devkitPro / libtonc contributors](https://github.com/devkitPro/libtonc) | MIT-licensed headers used to rebuild the open BIOS; tonclib is also a dependency of the upstream game's build. |
| [gba-toolchain — Felix Jones and contributors](https://github.com/felixjones/gba-toolchain/tree/be72565d4bd6302cf85555d45d22a02325c63281) | Game build integration and ROM runtime, under the zlib license. The 1.1 source pins this submodule. |
| [Maxmod — Mukunda Johnson and contributors](https://github.com/devkitPro/maxmod) | GBA sound runtime used by the upstream game, with ISC permission notices. The precise linked version in the prebuilt upstream ROM is not recorded. |
| The RetroArch team | libretro API header; its embedded MIT notice is preserved in `native/libretro.h`. SeedConsole's RetroArch frontend is not used at runtime. |
| [SeedSigner and contributors](https://github.com/SeedSigner/seedsigner/tree/0.8.7) | Signer application and hardware/display infrastructure, targeting upstream 0.8.7 under MIT terms. |
| Russ Hughes and Ivan Belokobylskiy | ST7789 display code and initialization material under MIT terms. Full notices remain in `native/NOTICE.txt` and upstream sources. |
| [The Chromium Authors](https://chromium.googlesource.com/chromium/src/+/2fb66b0ec4fa231bd675448bb9b4ea9c743d444b) | The separate Python fallback adapts Chromium Dino logic and sprites. BSD-3-Clause notices and exact provenance remain under `payload/opt/dino/`. The GBA game's release separately retains Chromium/ChromiumOS asset notices. |

Original project work includes the frontend, hardware bridge, configuration, image overlay tooling, fallback integration, and transition into SeedSigner. Third-party components retain their own authorship and licenses.

The build uses a hash-pinned [Bootlin toolchain](https://toolchains.bootlin.com/) and Debian container/package snapshot. These are trusted build inputs, not independently rebuilt compilers. The complete OS also includes Linux, BusyBox, glibc, Python, firmware, fonts, and other packages; see the [corresponding-source guide](docs/corresponding-source.md).
