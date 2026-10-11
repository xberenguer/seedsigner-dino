# Build and test

This repository is a source preview. It does not ship a game ROM, emulator binary, or flashable IMG. Local image assembly requires the external inputs in `build/inputs.lock.json`; a locally successful build does not resolve permission to redistribute the bundled game.

Use a clean checkout of the intended source commit. Python 3.11, Git, and a Docker-compatible Linux container runtime are recommended. The pinned container targets `linux/amd64`; on another host architecture, the runtime must support that platform. The build does not write to a raw device or flash an SD card.

## Review the pinned inputs

Read [`build/inputs.lock.json`](../build/inputs.lock.json) and [`build/Dockerfile`](../build/Dockerfile) before fetching or executing inputs. The lock records the exact SeedSigner base, source archives, cross-toolchain, signing material, local-ROM hash, and package snapshot. Do not silently replace a failing pinned input with a newer release.

The build's trusted inputs include the official SeedSigner binary OS base and the prebuilt Bootlin cross-toolchain. Neither is rebuilt from source here. See [reproducibility](reproducibility.md) for the complete boundary.

## Software checks

The Python tests use fake hardware. Native tests compile a test-only mock core; they do not require a game ROM or actual Pi hardware.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements-test.txt
PYTHONDONTWRITEBYTECODE=1 python3 -B -m pytest tests -q
make -C native test
```

Run the checks on Linux with a C compiler and `make`. If invoking only the native tests on macOS, platform behavior differs from the target runtime; the Linux container remains the reference build environment. Host test dependencies installed through pip are for local checks, not the pinned release build environment. Some upstream integration and full-image tests skip when their external inputs are absent; report skipped checks explicitly rather than counting them as passes.

## Source archive and local images

Create a deterministic source archive without downloading external inputs:

```sh
python3 scripts/release.py source
```

The default output is `dist/source-preview/`, containing the source archive, its file manifest, and `SHA256SUMS`. The command refuses to replace an existing archive. Use `--output PATH` to select a new output directory.

Fetch the locked public inputs, then verify the local cache:

```sh
python3 scripts/release.py fetch
python3 scripts/release.py fetch --offline
```

Build the ARM frontends and gpSP/open BIOS without the historical ROM:

```sh
python3 scripts/release.py native --output dist/native-check
```

For a local image build, supply your own ROM:

```sh
python3 scripts/release.py build \
  --rom /path/to/Google-Dino-Advance.gba \
  --output dist/local-build
```

The script never automatically fetches the historical game ROM. Supply it locally only if you have the necessary rights; its bytes must match the locked hash. The build runner creates the pinned Docker builder if absent, copies verified inputs into a temporary container, runs the compilation with networking disabled, and copies artifacts into the requested new output directory.

To select a nondefault Docker context, add `--docker-context NAME` to `native` or `build`. To recreate the builder environment, add `--rebuild-builder`. Creating the builder can require network access for the pinned container/packages; the compilation container itself has no network. The runtime must already be installed and running.

The local image build produces separate regular and Plus artifacts, with the upstream and modification versions embedded in their filenames. Preserve the manifests and checksums alongside each image. Do not publish those images until the [binary release gates](release-status.md) are met. To test repeatability, build again into a different output directory and compare the complete output hashes. An independent second builder is still required for the stronger public reproducibility claim.

## Physical validation

A completed build and passing software tests are not device qualification. Write only to the intended test SD card, complete the write tool's verification, then follow the [hardware checklist](hardware-testing.md) separately for each profile.
