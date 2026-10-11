# Licensing and binary-release boundary

Original SeedSigner Dino code is GPL-2.0-or-later. Third-party material retains its own license. The root `LICENSE` is not a blanket license for every upstream input.

| Component | License / boundary |
| --- | --- |
| Original frontend, launcher, bridge, configuration, build tooling | GPL-2.0-or-later |
| libretro API header | MIT notice embedded in the header |
| Chromium fallback material | BSD-3-Clause; exact license and provenance retained in the payload |
| Adapted ST7789 initialization material | MIT; notices retained in `native/NOTICE.txt` |
| gpSP and embedded open BIOS | GPL-2.0-or-later with upstream component credits; downloaded and compiled as a separate pinned input |
| libtonc headers used by the BIOS build | MIT; pinned devkitPro source input |
| SeedSigner 0.8.7 application | MIT; upstream source and notices remain applicable |
| Official SeedSigner OS base / firmware | A collection of components with their own licenses; do not apply the application license to the entire disk image |
| Historical Google-Dino-GBA 1.0.1 ROM | Redistribution not established in this preview; omitted |

## Historical game input

Private development used the 1.0.1 game ROM extracted from SeedConsole. Its bytes match the upstream release:

```text
Google-Dino-Advance.gba
SHA-256: 5942beac698ecee57c4d93da042b37ce632121f3500804cf3679d5edd642663d
```

The archived 1.0.1 source lacks a license file. A later [MIT license](https://github.com/fritzem/Google-Dino-GBA/blob/dca6780d60aa7816da89b797c5a64a77f9bfd334/LICENSE) identifies Ethan Fritz, but this preview does not assume it resolves all historical source, artwork, audio, library, or binary rights. Attribution alone does not grant redistribution permission.

No ROM or historical game source archive is included here. The local image build can accept the known ROM as an external, hash-checked input. The ability to build locally is not permission to upload the resulting image publicly.

## Corresponding source

Before distributing a complete image, preserve the actual corresponding sources, patches, build scripts, and notices for every applicable distributed component. Compiling from a pinned source checkout improves provenance; claiming it reproduces a previously extracted binary additionally requires an actual byte comparison.

The public source preview avoids distributing the historical emulator and game binaries. It does not claim that its notices alone satisfy the obligations of a future complete OS image. See [CREDITS.md](../CREDITS.md) and [NOTICE](../NOTICE).
