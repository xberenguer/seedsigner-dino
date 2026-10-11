# Credits

SeedSigner Dino combines existing open-source work with a lightweight frontend and startup integration. It is not an official release of any upstream project, and these credits do not imply endorsement.

| Project / people | Contribution and provenance |
| --- | --- |
| [SeedConsole — DesobedienteTecnologico and contributors](https://github.com/DesobedienteTecnologico/seedconsole) | Inspiration and the original known-working game/emulator setup. The private development image used the unchanged gpSP binary and `Google-Dino-Advance.gba` extracted from SeedConsole 4.8.1. That extraction is acknowledged; the historical binaries are not included in this source preview. |
| [Google-Dino-GBA — Ethan Fritz (`fritzem`)](https://github.com/fritzem/Google-Dino-GBA) | Author of the GBA recreation of Chromium's Dino game. Historical development used release 1.0.1. Its archived source has no license file; later upstream source carries an MIT license. Coverage of the older release and third-party assets remains to be resolved before redistribution. |
| [gpSP — Exophase, libretro, and contributors](https://github.com/libretro/gpsp) | GBA emulator. Development used the libretro core identified as v0.91 / commit `e554360dd3ed283696fc607877024a219248b735`, under GPL-2.0-or-later. Matching source is an input to the source build; an independent match to the historical extracted binary has not been established. |
| Normmatt and the VBA / VBA-M teams | Contributors credited by gpSP's embedded open BIOS. No proprietary Nintendo BIOS is supplied by this project. |
| [devkitPro / libtonc contributors](https://github.com/devkitPro/libtonc) | MIT-licensed headers used to rebuild the open BIOS. The exact source is a pinned build input. |
| The RetroArch team | The libretro API header, with its embedded MIT notice preserved in `native/libretro.h`. SeedConsole's RetroArch frontend is not used at runtime. |
| [SeedSigner and contributors](https://github.com/SeedSigner/seedsigner/tree/0.8.7) | The signer application and hardware/display infrastructure. The project targets upstream SeedSigner 0.8.7, under its MIT license. |
| Russ Hughes and Ivan Belokobylskiy | ST7789 display code and initialization material, under MIT terms. Copyright and permission notices are retained in `native/NOTICE.txt` and the upstream source. |
| [The Chromium Authors](https://chromium.googlesource.com/chromium/src/+/2fb66b0ec4fa231bd675448bb9b4ea9c743d444b) | The separate Python fallback adapts Chromium Dino logic and sprite material. BSD-3-Clause notices and the exact source manifest are retained under `payload/opt/dino/`. |

SeedSigner Dino's original work comprises its native frontend, Python hardware bridge, fallback integration, configuration handling, deterministic overlay assembly, and the transition into SeedSigner. Each third-party component retains its own authorship and license.

The documented build uses a hash-pinned [Bootlin toolchain](https://toolchains.bootlin.com/) and a pinned Debian container/package snapshot. These are trusted build inputs, not components this project has independently rebuilt. Their upstream notices remain applicable.
