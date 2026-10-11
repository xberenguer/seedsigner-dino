# Contributing

This is a source preview. Small, reviewable changes are preferred, especially around startup and signer hardware ownership.

1. Describe the behavior being changed and the hardware/profile affected.
2. Keep upstream versions, URLs, and hashes explicit. Do not add opaque binaries or substitute a different component silently.
3. Preserve third-party licenses and identify the source of copied or adapted code/assets.
4. Run the relevant checks in [building](docs/building.md). Include command results and limitations in the pull request.
5. For hardware changes, report actual tests using the [hardware checklist](docs/hardware-testing.md). Separate software simulation, image assembly, SD-card verification, and physical operation.

Please do not upload game ROMs, proprietary BIOS files, wallet secrets, private paths, or unrelated device logs. The historical game redistribution question must be resolved before including it in a public release.

Display changes should work for both profiles or clearly retain the other profile's behavior. Entry configuration must behave identically in the native and fallback paths. Preserve hold-and-release semantics, the original SeedSigner splash, and the explicit transition into the signer.

New original contributions are submitted under GPL-2.0-or-later unless an existing file explicitly has another license. This does not alter the licenses of third-party files.
