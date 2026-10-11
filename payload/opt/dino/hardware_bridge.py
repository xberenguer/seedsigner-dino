"""Bounded pipe transport between the native game and the existing HAT driver.

The child owns emulation and pixel generation only. This process owns all GPIO
and SPI through the same Python driver as the first, working image. Diagnostics
are bounded and written only to /tmp, which is the image's RAM filesystem.
"""

import os
from pathlib import Path
import selectors
import struct
import subprocess
import time


WIDTH, HEIGHT = 320, 240
MAX_RECTS = 600
MAX_DIAGNOSTIC_BYTES = 32 * 1024
PIPE_READ_BYTES = 64 * 1024


class BridgeError(RuntimeError):
    pass


class _Diagnostics:
    def __init__(self, path):
        self.path = path
        self.data = bytearray()

    def append(self, data):
        self.data.extend(data)
        if len(self.data) > MAX_DIAGNOSTIC_BYTES:
            del self.data[:-MAX_DIAGNOSTIC_BYTES]

    def save(self):
        if self.path is not None:
            # This is deliberately fixed to a RAM path by the production caller.
            try:
                Path(self.path).write_bytes(self.data)
            except OSError:
                pass


class _Reader:
    def __init__(self, process, diagnostics):
        self.process, self.diagnostics = process, diagnostics
        self.selector = selectors.DefaultSelector()
        self.selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        self.selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        self.output_eof = False
        # A frame often contains dozens of small rectangle headers. Reading only
        # the requested 2/8 bytes forced a select + read syscall for every header
        # even when the child had already queued the complete frame. Keep one
        # bounded pipe chunk and parse successive headers/pixels from memory.
        self.buffer = b""
        self.offset = 0

    def read(self, size, deadline, allow_eof=False):
        result = bytearray()
        while len(result) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BridgeError("Native game stopped responding")
            if self.offset < len(self.buffer):
                amount = min(size - len(result), len(self.buffer) - self.offset)
                result.extend(self.buffer[self.offset:self.offset + amount])
                self.offset += amount
                continue
            if self.output_eof:
                if not result and allow_eof:
                    return b""
                raise BridgeError("Truncated native frame")
            ready = self.selector.select(remaining)
            if not ready:
                raise BridgeError("Native game stopped responding")
            for key, _ in ready:
                amount = PIPE_READ_BYTES if key.data == "stdout" else 4096
                data = os.read(key.fd, amount)
                if not data:
                    self.selector.unregister(key.fileobj)
                    if key.data == "stdout":
                        self.output_eof = True
                elif key.data == "stderr":
                    self.diagnostics.append(data)
                else:
                    self.buffer, self.offset = data, 0
        return bytes(result)

    def close(self):
        self.selector.close()

    def drain_diagnostics(self):
        """Capture final stats after wait(), even if stdout closed first.

        Never block on a descendant that inherited stderr and cap the remaining
        drain to one pipe chunk. The retained diagnostic tail stays at 32 KiB.
        """
        descriptor = self.process.stderr.fileno()
        remaining = PIPE_READ_BYTES
        try:
            os.set_blocking(descriptor, False)
            while remaining:
                data = os.read(descriptor, min(4096, remaining))
                if not data:
                    break
                self.diagnostics.append(data)
                remaining -= len(data)
        except OSError:
            pass


def _stop(process):
    if process.poll() is None:
        try:
            process.terminate()
            process.wait(timeout=1.0)
        except ProcessLookupError:
            return
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=1.0)
            except ProcessLookupError:
                pass


def run_bridge(command, display, read_buttons, *, timeout=15.0,
               popen=subprocess.Popen, diagnostic_path="/tmp/dino-native.log"):
    """Serve validated frames/inputs until the child exits, returning its status.

    INP1 requests one active-low button mask. FRM1 carries a BE uint16 rectangle
    count followed by x/y/w/h BE uint16 headers and RGB565 bytes. A zero ACK is
    sent only after the entire bounded frame has been validated and displayed.
    Any timeout or transport failure terminates the child before returning.
    """
    width, height = getattr(display, "width", WIDTH), getattr(display, "height", HEIGHT)
    if (width, height) not in ((240, 240), (320, 240)):
        raise BridgeError("Unsupported display dimensions")
    max_rectangles = (width // 16) * (height // 8)
    diagnostics = _Diagnostics(diagnostic_path)
    process, reader = None, None
    try:
        process = popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, bufsize=0, close_fds=True)
        reader = _Reader(process, diagnostics)
        while True:
            deadline = time.monotonic() + timeout
            token = reader.read(4, deadline, allow_eof=True)
            if not token:
                result = process.wait(timeout=1.0)
                reader.drain_diagnostics()
                diagnostics.append(("\nNative exit: %d\n" % result).encode())
                return result
            if token == b"INP1":
                mask = read_buttons()
                if not isinstance(mask, int) or not 0 <= mask <= 255:
                    raise BridgeError("Invalid button mask")
                reply = bytes([mask])
            elif token == b"FRM1":
                count, = struct.unpack(">H", reader.read(2, deadline))
                if count > max_rectangles:
                    raise BridgeError("Too many native rectangles")
                frame, pixels = [], 0
                for _ in range(count):
                    x, y, rect_width, rect_height = struct.unpack(">4H", reader.read(8, deadline))
                    if not (rect_width and rect_height and x < width and y < height
                            and rect_width <= width - x and rect_height <= height - y):
                        raise BridgeError("Native rectangle outside display")
                    pixels += rect_width * rect_height
                    if pixels > width * height:
                        raise BridgeError("Native frame exceeds display size")
                    data = reader.read(rect_width * rect_height * 2, deadline)
                    frame.append((data, x, y, rect_width, rect_height))
                for rectangle in frame:
                    display.blit_buffer(*rectangle)
                reply = b"\0"
            else:
                raise BridgeError("Invalid native protocol message")
            process.stdin.write(reply)
            process.stdin.flush()
    except (OSError, EOFError, subprocess.SubprocessError, BridgeError) as error:
        diagnostics.append(("\nBridge failure: %s\n" % error).encode("utf-8", "replace"))
        raise BridgeError(str(error)) from error
    finally:
        try:
            if process is not None:
                _stop(process)
        finally:
            if reader is not None:
                reader.close()
            if process is not None:
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
            diagnostics.save()
