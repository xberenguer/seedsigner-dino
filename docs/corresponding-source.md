# Corresponding source for the SeedSigner OS base

A complete IMG includes Linux, BusyBox, glibc, libraries, Python, firmware, fonts, and other components alongside the SeedSigner application. Their individual licenses remain applicable when the image is redistributed.

The separate `seedsigner-v0.8.7-os-corresponding-source.tar.gz` release asset is collected from the exact upstream 0.8.7 Pi Zero build configuration. It stays outside the IMG to avoid filling the boot partition with large archives.

## Pinned inputs

| Input | Commit |
| --- | --- |
| [SeedSigner OS v0.8.7](https://github.com/SeedSigner/seedsigner-os/tree/v0.8.7) | `d13859392660fe512a753bc14ecd0edc86c35510` |
| [Buildroot submodule](https://github.com/SeedSigner/buildroot/tree/bf2a2858aa675a14b60f1f9142c65b32652609c1) | `bf2a2858aa675a14b60f1f9142c65b32652609c1` |
| [SeedSigner application 0.8.7](https://github.com/SeedSigner/seedsigner/tree/0.8.7) | `e0a80d4b33b8eb7fb1e9fd14a27b7cd11c7d2cd6` |
| [Translations/font submodule](https://github.com/SeedSigner/seedsigner-translations/tree/708961a4163b1bd43eb15c4a26713649c63f6ccd) | `708961a4163b1bd43eb15c4a26713649c63f6ccd` |

Archive URLs/hashes are in [`scripts/collect_os_sources.py`](../scripts/collect_os_sources.py) and the produced manifest. The OS recipe identifies Raspberry Pi Linux commit `14b35093ca68bf2c81bbc90aace5007142b40b40`, with kernel and BusyBox configurations retained.

## Bundle contents

The collector configures `pi0_defconfig` and runs Buildroot's `make legal-info`:

- OS and Buildroot archives, including build recipes and patches.
- Expanded configuration and target/host package manifests.
- Selected package sources, applied patch series, and license texts.
- Application and translations/font source archives.
- Input pins, file checksums, environment versions, and collection warnings.

This downloads, extracts, and patches sources; it does not perform a complete OS build. Package declarations and warnings require review. Collection is not legal/security certification. The [upstream legal-info documentation](https://github.com/SeedSigner/buildroot/blob/bf2a2858aa675a14b60f1f9142c65b32652609c1/docs/manual/legal-notice.adoc) explains its scope.

## Recreate the collection

With the documented Docker builder available:

```sh
python3 scripts/collect_os_sources.py --output dist/os-source-collection
```

Add `--docker-context NAME` if needed. A new temporary container collects substantial source archives without changing existing containers or flashing a device. The output directory must be new. Keep its log, manifest, warnings, and checksums alongside the archive.

Dino frontend/core/game sources and their build information are separate release assets; this OS bundle does not replace them.
