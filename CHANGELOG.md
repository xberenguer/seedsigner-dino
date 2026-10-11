# Changelog

## 0.1.1-beta — experimental flashable images — 2026-10-11

- Provide separate regular and Plus Pi Zero IMG downloads with SHA-256 checksums and image inspection manifests.
- Replace the historical 1.0.1 ROM with the author's licensed Dino 1.1 release, retaining its MIT and BSD notices and pinned source.
- Package the verified ARM frontends, rebuilt gpSP core and open BIOS with the signed SeedSigner 0.8.7 base.
- Preserve the original splash, independent game clock, editable entry combination, and bounded SD mount wait.
- Include source and build provenance for review. Physical qualification and an independent security audit remain pending.

## 0.1.0-beta — source preview — 2026-10-11

- Publish the native libretro frontend, Python hardware bridge, fallback game, and SeedSigner startup integration for review.
- Retain the original SeedSigner splash after the explicit hold-and-release entry gesture.
- Keep the emulated game clock independent of slower LCD presentations.
- Introduce regular 240 × 240 and Plus 320 × 240 display profiles.
- Add an editable boot-partition entry combination and hold duration.
- Document attribution, build inputs, security boundaries, and the hardware release checklist.

No flashable IMG is provided by this source preview. Hardware qualification, historical ROM redistribution, and independent end-to-end reproducibility remain pending.
