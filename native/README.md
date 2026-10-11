# Native Dino frontend

The frontend loads a gpSP libretro core and a locally supplied GBA ROM. Its
game clock runs at the core's 59.7275 Hz independently from LCD updates, which
are capped at 30 Hz. Dirty rectangles compare with the last displayed frame;
skipped LCD presentations do not skip emulated game frames. Audio is discarded.

## Build and test

Host-only frontend and mock-core checks:

```sh
make -C native test
python3 -m pip install -r requirements-test.txt
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest tests
```

Pi Zero builds use the pinned Bootlin ARMv6/VFPv2 hard-float toolchain in
`build/inputs.lock.json`. No SeedConsole compiler or extracted emulator binary
is used. The offline container compiles this frontend for both screen sizes,
gpSP from its pinned source, and its embedded open BIOS from source with the
pinned Debian ARM7TDMI compiler and libtonc headers. It deletes the upstream
prebuilt BIOS before rebuilding. The compiler/sysroot and signed SeedSigner
OS remain trusted binary inputs; this is not a complete OS/toolchain rebuild.

```sh
python3 scripts/release.py fetch
python3 scripts/release.py native --docker-context YOUR_CONTEXT --output dist/native-check
```

`native` requires no ROM. It checks ARM ELF attributes and runs the frontend
self-tests and a core loading check under ARM1176 QEMU with libraries extracted
from the verified stock OS. See `docs/building.md` for optional local images.
The historical ROM's redistribution rights remain pending. A matching hash
proves identity, not permission to publish it.

## Profiles and hardware

The compile-time define `DINO_LCD_WIDTH` is 240 (regular) or 320 (Plus), with a
240-pixel display height. Regular presents the original 240x160 frame centered
at y=40; Plus scales with nearest sampling to 320x213 centered at y=13.
`/opt/dino/display-profile.json` selects the matching upstream display driver.
The launcher passes `--display-width 240|320`; a mismatched binary is rejected.

Production starts `/usr/bin/python3 /opt/dino/launcher.py`. Python owns the
upstream GPIO/SPI driver and native owns emulation, scaling, dirty tiles and
RGB565 packing. The pipe protocol is `INP1` plus a one-byte button reply, or
`FRM1` plus a big-endian rectangle count, x/y/w/h headers and packed RGB565.
The parent acknowledges each displayed frame, preventing queued LCD work.

Controls are UP/DOWN/LEFT/RIGHT, KEY1=A, KEY2=B, CENTER=SELECT, KEY3=START.
The default entry gesture is to hold KEY1+KEY3 for two seconds, then release
all buttons for 80 ms. The boot partition's `dino-config.ini` can change the
chord and hold duration. The launcher validates the settings and supplies
`--enter-buttons KEY1+KEY3 --hold-seconds 2` to native and fallback paths.
Only the completed gesture returns status 42 and opens SeedSigner. Python
releases display/input hardware first; SeedSigner's original splash remains.
Errors return to the Python game. Saves and states are not persisted.

## Optional headless execution

```sh
./native/dino-native --headless --core /path/to/gpsp_libretro.so \
  --rom /path/to/Google-Dino-Advance.gba --frames 600 \
  --script input.csv --capture-dir captures --capture-every 60
```

CSV rows are `start_frame,end_frame,buttons`, zero-based and end-exclusive.
Buttons are `UP|DOWN|LEFT|RIGHT|CENTER|KEY1|KEY2|KEY3` or `NONE`.
Without `--realtime`, simulated time derives from frame count. With it, the
hardware deadline logic is used. JSON reports frame/audio counts, hashes,
timing and estimated SPI traffic. Captures are explicit P6 PPM writes.
QEMU and mock-driver checks do not establish physical speed, SPI behavior,
camera operation or signing safety. Both screen profiles need device tests.
