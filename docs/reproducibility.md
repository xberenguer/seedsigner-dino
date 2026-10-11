# Reproducibility and review

The target is an independent build that produces the same bytes from the same published inputs. This preview distinguishes that target from what has actually been demonstrated.

## Current boundary

The image assembly process verifies the exact official SeedSigner 0.8.7 Pi Zero base, then adds a deterministic overlay and the profile's boot settings. It preserves the underlying upstream image as a trusted binary input. The project does not claim to rebuild the complete upstream operating system, kernel, or firmware.

Historical development used a SeedConsole-extracted gpSP binary and Dino ROM. The public build recipe instead compiles the project's frontend and gpSP/open BIOS from pinned source using a pinned cross-toolchain. The historical game ROM remains an externally supplied, hash-checked local input; source coverage and redistribution are unresolved. A newly compiled gpSP core should not be described as byte-identical to the historical extracted core unless that comparison is established.

The Bootlin cross-toolchain and Debian container/packages are trusted prebuilt build inputs. This project does not bootstrap its compiler from source or eliminate compiler trust.

No independent third party has yet reproduced and attested to a complete final image. A previous private development image was rebuilt byte-identically from the same prebuilt inputs. That is evidence of repeatable assembly, not a complete source-to-binary proof for this release.

## Inputs that must remain explicit

- The release source commit and version.
- The official base image, size, SHA-256, and verified upstream signature where available.
- The gpSP source commit and its required submodule content.
- The compiler/toolchain archive and hash, container recipe, and package snapshot.
- The locally supplied ROM's hash and provenance.
- The profile, configuration template, build flags, and normalized timestamps.
- The exact commands used and final source, overlay, and image hashes.

Image assembly normalizes archive ownership, permissions, order, and timestamps. The pinned build environment reduces host-dependent differences. Pinning an input makes it identifiable; it does not itself establish that the input is trustworthy.

## Independent verification procedure

1. Review the tagged source and all pinned input URLs/hashes.
2. Fetch the inputs in a fresh environment and verify the official base's provenance.
3. Build according to [building](building.md), retaining the container/build identity and logs.
4. Repeat in a second clean environment; compare the complete image and overlay hashes.
5. If a published binary release exists, compare against its signed checksums. Investigate any difference instead of ignoring metadata mismatches.
6. Publish the source commit, environment, commands, input hashes, output hashes, and any discrepancies. Do not publish ROMs or other inputs without the required rights.

The maintainers should obtain at least one independent matching rebuild before labeling a downloadable image reproducible. A release signature authenticates the release publisher; the upstream signature authenticates the unmodified base only.

## Security review is separate

A matching rebuild shows that the reviewed inputs produce the distributed bytes. Code review assesses behavior. Review the small startup overlay first: entry configuration, subprocess invocation, input handling, display writes, game termination, and the transition into the signer. Then inspect the emulator/game inputs and trusted base. See [SECURITY.md](../SECURITY.md).
