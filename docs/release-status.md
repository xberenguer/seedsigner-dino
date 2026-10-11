# Release status

## 0.1.0-beta source preview — 2026-10-11

The repository publishes source and build tooling for review. It does not provide a ready-to-use IMG. Intended future image names include both the upstream and modification versions:

```text
seedsigner-v0.8.7-dino-v0.1.0-beta-regular-pi0.img
seedsigner-v0.8.7-dino-v0.1.0-beta-plus-pi0.img
```

| Area | Status |
| --- | --- |
| Upstream target | Official SeedSigner 0.8.7 Pi Zero image, pinned by hash |
| Startup / splash | Explicit hold-and-release transition; original splash retained |
| Regular / Plus profiles | Implemented for software review; physical qualification pending |
| Boot configuration | Implemented for software review; physical qualification pending |
| Historical development validation | Earlier Plus revision recorded 50 passing software tests and a byte-identical assembly; this does not qualify the new source preview |
| Native executable builds | Recipe provided; final build evidence belongs to the exact reviewed commit |
| Complete independent image rebuild | Pending |
| Historical ROM redistribution | Unresolved; ROM not included |
| Hardware release checklist | Pending for both profiles |
| Independent security audit | Not performed |

## Before a binary release

1. Resolve the game ROM's licensing and third-party asset coverage, or use a demonstrably redistributable replacement built from pinned source.
2. Retain complete corresponding source, notices, and build information for distributed components, including the relevant OS/firmware obligations.
3. Run the software and image-inspection checks for the final commit.
4. Obtain an independent clean rebuild and compare output hashes.
5. Complete the physical checklist for each screen profile.
6. Publish source, manifests, checksums, build logs, and hardware test results with clearly scoped claims.

Source-only publication does not imply that these binary release gates have been met.
