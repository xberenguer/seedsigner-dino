#!/usr/bin/env python3
"""Black-box host tests; actual ARM gpSP validation is an additional build step."""
import json
import os
from pathlib import Path
import platform
import subprocess
import select
import struct
import tempfile
import time
import unittest

NATIVE = Path(__file__).resolve().parents[1]


class FrontendTest(unittest.TestCase):
    LCD_WIDTH = 320

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix="dino-native-tests-")
        cls.root = Path(cls.tmp.name)
        cls.binary = cls.root / "dino-native"
        cls.view_height = cls.LCD_WIDTH * 160 // 240
        cls.view_y = (240 - cls.view_height) // 2
        subprocess.run([os.environ.get("CC", "cc"), "-O2", "-std=c11",
                        "-Wall", "-Wextra", "-Werror", "-fno-strict-aliasing",
                        "-DDINO_LCD_WIDTH=%d" % cls.LCD_WIDTH,
                        str(NATIVE / "dino_frontend.c"), "-ldl", "-o", str(cls.binary)],
                       check=True)
        cls.core = cls.root / "mock_core.so"
        shared = "-dynamiclib" if platform.system() == "Darwin" else "-shared"
        subprocess.run([os.environ.get("CC", "cc"), shared, "-fPIC", "-O2", "-std=c99",
                        "-Wall", "-Wextra", "-Werror", str(NATIVE / "tests/mock_core.c"),
                        "-o", str(cls.core)], check=True)
        cls.rom = cls.root / "fake.gba"
        cls.rom.write_bytes(b"frontend-test-only")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def run_host(self, script=None, frames=200, capture=None, extra_env=None, extra_args=()):
        args = [str(self.binary), "--headless", "--core", str(self.core),
                "--rom", str(self.rom), "--frames", str(frames)]
        args.extend(extra_args)
        if script is not None:
            path = self.root / "input.csv"
            path.write_text(script)
            args += ["--script", str(path)]
        if capture:
            args += ["--capture-dir", str(capture)]
        env = dict(os.environ, **(extra_env or {}))
        proc = subprocess.run(args, capture_output=True, text=True, env=env)
        stats = json.loads(proc.stdout) if proc.stdout else None
        return proc, stats

    def test_core_callbacks_and_determinism(self):
        first, a = self.run_host("0,200,UP\n")
        second, b = self.run_host("0,200,UP\n")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(a["frames"], 200)
        self.assertEqual(a["video_frames"], 200)
        self.assertEqual(a["audio_frames"], 1600)
        self.assertEqual(a["option_reads"], 1023)
        for key in ("frame_hash", "raw_frame_hash", "dirty_rects", "spi_bytes_estimate"):
            self.assertEqual(a[key], b[key])
        self.assertLess(a["max_steady_frame_bytes"], 2048)
        self.assertLessEqual(a["p95_steady_frame_bytes"], a["max_steady_frame_bytes"])
        self.assertEqual(a["steady_frames"], 199)
        self.assertEqual(a["frames_over_wire_budget"], 0)

    def test_native_self_test_for_compiled_profile(self):
        proc = subprocess.run([str(self.binary), "--self-test"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["self_test"], "PASS")

    def test_exact_hold_and_release_required(self):
        for script in ("0,200,KEY3\n", "0,200,CENTER|KEY3\n",
                       "0,119,KEY1|KEY3\n", "0,200,KEY1|KEY3\n",
                       "0,119,KEY1|KEY3\n119,120,KEY1\n120,200,KEY1|KEY3\n"):
            proc, stats = self.run_host(script)
            self.assertEqual(proc.returncode, 0, (script, proc.stderr))
            self.assertEqual(stats["frames"], 200)
        proc, stats = self.run_host("0,121,KEY1|KEY3\n")
        self.assertEqual(proc.returncode, 42, proc.stderr)
        self.assertEqual(stats["frames"], 126)
        self.assertEqual(stats["exit_code"], 42)

    def test_every_key_must_release_and_debounce(self):
        proc, stats = self.run_host("0,121,KEY1|KEY3\n121,160,UP\n162,163,KEY2\n")
        self.assertEqual(proc.returncode, 42, proc.stderr)
        self.assertEqual(stats["frames"], 168)

    def test_color_capture_and_padded_pitch(self):
        captures = self.root / "captures"
        proc, stats = self.run_host("0,1,UP\n", frames=1, capture=captures)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(stats["video_frames"], 1)
        image = (captures / "frame-000001.ppm").read_bytes()
        width, top, bottom = self.LCD_WIDTH, self.view_y, self.view_y+self.view_height
        header = ("P6\n%d 240\n255\n" % width).encode()
        self.assertTrue(image.startswith(header))
        rgb = image[len(header):]
        self.assertEqual(len(rgb), width * 240 * 3)
        self.assertEqual(rgb[:width * top * 3], b"\0" * (width * top * 3))
        self.assertEqual(rgb[width * bottom * 3:], b"\0" * (width * (240-bottom) * 3))
        self.assertEqual(rgb[width * top * 3:width * top * 3 + 3], b"\xff\0\0")
        raw = (captures / "raw-000001.ppm").read_bytes()
        self.assertTrue(raw.startswith(b"P6\n240 160\n255\n"))
        # KEY3 is the original GBA START, shown blue by this test-only core.
        proc, _ = self.run_host("0,1,KEY3\n", frames=1, capture=captures)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual((captures / "frame-000001.ppm").read_bytes()[len(header)+width*top*3:][:3],
                         b"\0\0\xff")

    def test_failures_never_unlock(self):
        for extra_env in ({"MOCK_FAIL_LOAD": "1"}, {"MOCK_BAD_VIDEO": "1"}):
            proc, _ = self.run_host(extra_env=extra_env)
            self.assertNotEqual(proc.returncode, 0)
            self.assertNotEqual(proc.returncode, 42)
        for option in ("--unknown", "--frames", "--core"):
            proc = subprocess.run([str(self.binary), option], capture_output=True)
            self.assertNotEqual(proc.returncode, 42)
            self.assertNotEqual(proc.returncode, 0)
        proc, _ = self.run_host("bad,input,line\n")
        self.assertNotEqual(proc.returncode, 42)
        self.assertNotEqual(proc.returncode, 0)

    def bridge_child(self, extra_env=None):
        return subprocess.Popen([str(self.binary), "--bridge", "--core",
                                 str(self.core), "--rom", str(self.rom)],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, bufsize=0,
                                env=dict(os.environ, **(extra_env or {})))

    def pipe_read(self, pipe, size):
        body = bytearray()
        deadline = time.monotonic() + 5
        while len(body) < size:
            ready, _, _ = select.select([pipe], [], [], max(0, deadline-time.monotonic()))
            self.assertTrue(ready, "Bridge timed out")
            chunk = os.read(pipe.fileno(), size-len(body))
            if not chunk:
                return bytes(body)
            body.extend(chunk)
        return bytes(body)

    def bridge_frame(self, child):
        self.assertEqual(self.pipe_read(child.stdout, 4), b"FRM1")
        count, = struct.unpack(">H", self.pipe_read(child.stdout, 2))
        self.assertLessEqual(count, 600)
        rects = []
        for _ in range(count):
            x, y, w, h = struct.unpack(">4H", self.pipe_read(child.stdout, 8))
            self.assertTrue(w and h and x+w <= self.LCD_WIDTH and y+h <= 240)
            rects.append((x,y,w,h,self.pipe_read(child.stdout,w*h*2)))
        return rects

    def test_bridge_preserves_pixels_isolates_core_stdout_and_waits_for_ack(self):
        child = self.bridge_child({"MOCK_CORE_STDOUT":"1"})
        try:
            self.assertEqual(self.pipe_read(child.stdout,4), b"INP1")
            child.stdin.write(bytes([1]))
            rects = self.bridge_frame(child)
            self.assertEqual(len(rects),1)
            x,y,w,h,data = rects[0]
            self.assertEqual((x,y,w,h),(0,0,self.LCD_WIDTH,240))
            self.assertEqual(data[:self.LCD_WIDTH*self.view_y*2], bytes(self.LCD_WIDTH*self.view_y*2))
            self.assertEqual(data[self.LCD_WIDTH*self.view_y*2:][:2], b"\xf8\x00")
            self.assertEqual(select.select([child.stdout],[],[],0.05)[0], [])
            child.stdin.write(b"\x01")  # invalid ACK must never unlock
            self.assertEqual(child.wait(timeout=5),1)
            self.assertIn(b"config_path is", child.stderr.read())
        finally:
            if child.poll() is None: child.kill()
            child.wait()
            for pipe in (child.stdin,child.stdout,child.stderr): pipe.close()

    def run_clocked_bridge(self, display_delay=0):
        child = self.bridge_child()
        start = time.monotonic()
        displays = 0
        pixels = bytearray(self.LCD_WIDTH*240*2)
        try:
            while True:
                tag = self.pipe_read(child.stdout,4)
                if not tag: break
                if tag == b"INP1":
                    child.stdin.write(bytes([160 if time.monotonic()-start<2.15 else 0]))
                    continue
                self.assertEqual(tag,b"FRM1")
                count, = struct.unpack(">H",self.pipe_read(child.stdout,2))
                for _ in range(count):
                    x,y,w,h = struct.unpack(">4H",self.pipe_read(child.stdout,8))
                    self.assertTrue(w and h and x+w<=self.LCD_WIDTH and y+h<=240)
                    data=self.pipe_read(child.stdout,w*h*2)
                    self.assertEqual(len(data),w*h*2)
                    for row in range(h):
                        offset=((y+row)*self.LCD_WIDTH+x)*2
                        pixels[offset:offset+w*2]=data[row*w*2:(row+1)*w*2]
                if display_delay: time.sleep(display_delay)
                child.stdin.write(b"\0")
                displays += 1
            self.assertEqual(child.wait(timeout=5),42)
            self.assertGreater(time.monotonic()-start,2.20)
            diagnostics=child.stderr.read().decode()
            stats=next(json.loads(line) for line in diagnostics.splitlines()
                       if line.startswith('{"frames":'))
            self.assertGreater(stats["frames"],120)
            self.assertEqual(stats["presented_frames"],displays)
            self.assertEqual(stats["video_frames"],stats["frames"])
            self.assertEqual(stats["suppressed_frames"]+displays,stats["frames"])
            self.assertEqual(stats["discarded_clock_frames"],0)
            # The reconstructed LCD must match the native last-presented frame,
            # including differences accumulated during skipped presentations.
            value=14695981039346656037
            for byte in pixels: value=((value^byte)*1099511628211)&((1<<64)-1)
            self.assertEqual('%016x'%value,stats["frame_hash"])
            return stats
        finally:
            if child.poll() is None: child.kill()
            child.wait()
            for pipe in (child.stdin,child.stdout,child.stderr): pipe.close()

    def test_bridge_requires_real_hold_then_release_and_never_opens_hardware(self):
        # This mode also works on macOS, where /dev/gpiomem and SPI do not exist.
        stats=self.run_clocked_bridge()
        self.assertLess(stats["presented_frames"],stats["frames"])

    def test_slow_display_preserves_game_speed_and_latest_displayed_pixels(self):
        for delay in (0.020,0.040,0.060):
            with self.subTest(delay=delay):
                stats=self.run_clocked_bridge(delay)
                self.assertGreater(stats["emulated_fps"],stats["target_fps"]*0.95)
                self.assertLess(stats["emulated_fps"],stats["target_fps"]*1.05)
                self.assertLess(stats["presented_frames"],stats["frames"]*0.60)

    def test_bridge_eof_and_core_failure_never_unlock(self):
        for env in ({}, {"MOCK_FAIL_LOAD":"1"}):
            child = self.bridge_child(env)
            child.stdin.close()
            try:
                self.assertNotEqual(child.wait(timeout=5),42)
                self.assertNotEqual(child.returncode,0)
            finally:
                if child.poll() is None: child.kill()
                child.wait()
                child.stdout.close(); child.stderr.close()

    def test_custom_gesture_timing_and_game_input_suppression(self):
        args = ["--enter-buttons", "UP+CENTER", "--hold-seconds", "1",
                "--display-width", str(self.LCD_WIDTH)]
        proc, stats = self.run_host("0,61,UP|CENTER\n", extra_args=args)
        self.assertEqual(proc.returncode, 42, proc.stderr)
        self.assertEqual(stats["frames"], 66)
        # The mock core paints UP red; a custom UP+CENTER chord must remain black.
        captures = self.root / "custom-captures"
        proc, _ = self.run_host("0,1,UP|CENTER\n", frames=1, capture=captures, extra_args=args)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        image = (captures / "frame-000001.ppm").read_bytes()
        offset = len(("P6\n%d 240\n255\n" % self.LCD_WIDTH).encode())
        offset += self.LCD_WIDTH*self.view_y*3
        self.assertEqual(image[offset:offset+3], b"\0\0\0")
        proc, _ = self.run_host("0,121,KEY1|KEY3\n", extra_args=args)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_invalid_entry_configuration_and_profile_mismatch_fail(self):
        for args in (["--enter-buttons", "KEY1"], ["--enter-buttons", "KEY1+KEY1"],
                     ["--enter-buttons", "KEY1++KEY3"], ["--enter-buttons", "KEY1+OTHER"],
                     ["--hold-seconds", "nan"], ["--hold-seconds", "0.5"],
                     ["--hold-seconds", "11"],
                     ["--display-width", "240" if self.LCD_WIDTH == 320 else "320"]):
            proc, _ = self.run_host(extra_args=args)
            self.assertEqual(proc.returncode, 1, (args, proc.stderr))


class RegularFrontendTest(FrontendTest):
    LCD_WIDTH = 240


if __name__ == "__main__":
    unittest.main()
