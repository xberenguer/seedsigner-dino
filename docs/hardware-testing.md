# Physical release checklist

Run this checklist separately for `regular` and `plus` on the intended Pi Zero hardware. Use a disposable test seed and test transactions, never a wallet holding funds. Do not publish seed phrases, secret QR codes, or identifying wallet data with the results.

## Record first

- Source commit, image filename, image SHA-256, and build manifest.
- Board model/revision, HAT, display, and camera model.
- SD-card write tool/version and its completed verification result.
- Tester, date, and any configuration changes.

## Test

- [ ] Cold boot reaches a visible playable Dino game.
- [ ] Correct orientation, full screen bounds, and expected centered viewport.
- [ ] Every button works; controls do not leave stuck inputs.
- [ ] Gameplay speed remains consistent during visible LCD updates.
- [ ] Short holds and incomplete combinations do not enter SeedSigner.
- [ ] Default combination requires the full hold followed by release of every button.
- [ ] A custom combination and duration work after reboot, in both native and fallback paths.
- [ ] Missing configuration uses defaults; invalid configuration visibly warns and uses defaults.
- [ ] Native startup failure visibly enters the fallback game without starting SeedSigner.
- [ ] Entry stops the game, releases hardware, and shows the original SeedSigner splash before the main menu.
- [ ] Menus render correctly and all buttons work in SeedSigner after entry.
- [ ] Camera preview and QR scanning work.
- [ ] A disposable seed loads and the test wallet's addresses match an independent reference.
- [ ] An independently prepared test PSBT can be scanned, reviewed, signed, exported, and verified by the coordinator.
- [ ] SeedSigner's Restart returns to Dino; repeated game-to-signer cycles remain functional.
- [ ] Power off / cold boot works repeatedly, including after a longer gameplay session.
- [ ] The SD card contains no unexpected game saves or persistent diagnostic data after use.

## Report

Mark every item pass, fail, or not tested. Include visible failure symptoms, repeat steps, and nonsecret logs where useful. A successful build, matching checksum, completed flash, emulated frame-rate test, and working physical device are distinct milestones. Do not substitute one for another.

If signing, camera, or hardware cleanup fails, withhold the affected profile from binary release until resolved and retested.
