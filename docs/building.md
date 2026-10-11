# Build and test

The 0.1.1-beta release includes experimental regular and Plus IMG downloads. These instructions assemble images locally from the pinned inputs in `build/inputs.lock.json`. The included game is the official Google Dino Advance 1.1 release, with its MIT and BSD notices; the historical unlicensed development ROM is not accepted.

Use a clean checkout of the intended source commit. Python 3.11, Git, and a Docker-compatible Linux container runtime are recommended. The pinned container targets `linux/amd64`; on another host architecture, the runtime must support that platform. The build does not write to a raw device or flash an SD card.

## Review the pinned inputs

Read [`build/inputs.lock.json`](../build/inputs.lock.json) and [`build/Dockerfile`](../build/Dockerfile) before fetching or executing inputs. The lock records the exact SeedSigner base, source archives, cross-toolchain, signing material, licensed ROM release and hash, and package snapshot. Do not silently replace a failing pinned input with a newer release.

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

## Source archive and images

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

Build both images, including the locked official 1.1 ROM:

```sh
python3 scripts/release.py build --output dist/local-build
```

An optional `--rom PATH` accepts only the exact licensed 1.1 ROM hash. The build runner creates the pinned Docker builder if absent, copies verified inputs into a temporary container, runs the compilation with networking disabled, and copies artifacts into the requested new output directory.

The published beta reuses an already verified native build. To reproduce that packaging step with the exact cached native bundle and its source snapshot available:

```sh
python3 scripts/release.py verify
python3 scripts/release.py package \
  --native-dir dist/native-check-final \
  --output dist/images-v0.1.1-beta
```

This packaging path checks the pinned native cache hashes and corresponding source before assembly. It requires local `mcopy` (mtools) and GnuPG. If you do not have that exact native cache, use `build` to compile from the pinned source instead.

To select a nondefault Docker context, add `--docker-context NAME` to `native` or `build`. To recreate the builder environment, add `--rebuild-builder`. Creating the builder can require network access for the pinned container/packages; the compilation container itself has no network. The runtime must already be installed and running.

The local image build produces separate regular and Plus artifacts, with the upstream and modification versions embedded in their filenames. Preserve the manifests and checksums alongside each image. Publish experimental results with their [release status](release-status.md), license/source material and test limitations. To test repeatability, build again into a different output directory and compare the complete output hashes. An independent second builder is needed before claiming independent reproducibility; it is not claimed for this beta.

## Physical validation

A completed build and passing software tests are not device qualification. Write only to the intended test SD card, complete the write tool's verification, then follow the [hardware checklist](hardware-testing.md) separately for each profile.
