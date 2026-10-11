# Reproducibility and review

The target is an independent build producing identical bytes from published inputs. The experimental release distinguishes that target from its actual evidence.

## Current boundary

The builder verifies the official SeedSigner 0.8.7 Pi Zero image, then adds an inspectable overlay, display settings, and entry configuration. The signed OS remains a trusted binary input. Its upstream signature authenticates the unmodified base, not the resulting Dino image.

The frontend, gpSP core, and open BIOS are compiled from pinned source using a hash-pinned Bootlin toolchain and Debian environment. Compiler/sysroot and Debian tools are trusted prebuilt inputs; this project does not bootstrap its compiler or eliminate compiler trust.

**Google-Dino-GBA 1.1 is the verified official upstream ROM**, not a claimed source reproduction. Its licensed source and notices accompany the release. Historical SeedConsole-extracted game/core binaries are not the public 0.1.1-beta inputs.

The separate [OS source collection](corresponding-source.md) supplies pinned build recipes, package source archives, patches, configuration, and notices. Collection is not a new OS build or proof that every upstream byte was reproduced locally.

Repeated packaging from identical supplied inputs is deterministic. An independent third party has not yet attested to a complete final IMG match. ARM1176 QEMU checks establish specific software/ABI behavior, not physical screen, camera, or signing qualification. Exact results belong to the final release's manifests and logs.

## Inputs recorded for review

- Project source commit and release version.
- Official base size/hash, signature, and signing-key fingerprint.
- Core/BIOS/library source pins, compiler archive, and build flags.
- Official game ZIP, ROM hash, licensed source tag, and notices.
- Container recipe, package snapshot/versions, and output hashes.
- Screen profile, entry configuration template, and normalized metadata.

Pinning identifies an input; it does not establish safe behavior.

## Independent verification

1. Review tagged source, manifests, archives, and input URLs/hashes.
2. Fetch in a clean environment and verify the official base signature.
3. Follow [building](building.md), retaining container identity and logs.
4. Repeat in another clean environment and compare complete IMG/overlay hashes.
5. Compare with release `SHA256SUMS`; investigate every difference.
6. Publish the source commit, commands, input/output hashes, and discrepancies.

An independent matching rebuild would support a stronger claim. Until then, downloads remain explicitly experimental. A release signature, if supplied, identifies its publisher and does not replace review.

## Security review is separate

A rebuild shows that reviewed inputs produce distributed bytes. Code review assesses behavior: configuration, privileged startup, child processes, input validation, display writes, filesystem access, and signer transition. Also inspect the emulator/game inputs and trusted base. See [SECURITY.md](../SECURITY.md).
