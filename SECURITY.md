# Security

SeedSigner Dino modifies the startup path of a signing device. This release is experimental and has not had an independent security audit or complete physical qualification. Test with disposable seeds and test transactions; do not use a wallet holding funds for validation.

## Intended boundary

- The game runs before the upstream signer UI and owns the display and buttons until an explicit entry gesture completes.
- The gesture is a navigation shortcut, not a password, access control, or protection against physical access.
- Native failure falls back to a local game rather than silently launching SeedSigner.
- The native child is stopped and GPIO/SPI ownership is released before upstream SeedSigner initialization.
- The original SeedSigner splash is retained.
- Game progress is volatile. The frontend does not persist save RAM or save states; explicit developer capture mode writes only to its requested capture directory.
- Configuration is local, read once at boot, and validated before use.

These describe intended behavior and software checks, not an assurance that an untested image is safe. Reviewers should inspect privileged startup, subprocess termination, GPIO/SPI cleanup, filesystem writes, input validation, and all code executed before and during signer startup. Also inspect downloaded components and the trusted upstream base.

## Reproducibility is not a security audit

An independently matching image hash establishes that the documented inputs and build process produce the distributed bytes. It does not prove that those inputs have safe behavior. Conversely, a hash mismatch needs investigation even if a local test appears to work. See [reproducibility](docs/reproducibility.md).

## Reporting a concern

Use the repository's **Security → Report a vulnerability** feature if available. If it is unavailable, open an issue asking for a private reporting channel without publishing exploit details. Never include a seed phrase, private key, signing QR, wallet backup, or other secret in an issue, pull request, screenshot, or build log.

Do not infer that a report has been received privately unless GitHub confirms submission. There is no promised response time for this community project.
