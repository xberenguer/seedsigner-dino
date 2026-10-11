"""Native, offline Dino runner for a 320 x 150 Pillow viewport.

Copyright 2014-2026 The Chromium Authors.
Python/Pillow adaptation, 2026.
BSD-3-Clause; see licenses/CHROMIUM-BSD-3-Clause.txt and source-manifest.json.

The game owns no hardware and writes no files. Inputs are held-button states.
Physics runs at 60 Hz independently of the caller's display refresh rate.
"""

from dataclasses import dataclass
import math
from pathlib import Path
import random

from PIL import Image, ImageDraw, ImageFont, ImageOps


STEP = 1.0 / 60.0
_RUN_BOXES = ((22, 0, 17, 16), (1, 18, 30, 9), (10, 35, 14, 8),
              (1, 24, 29, 5), (5, 30, 21, 4), (9, 34, 15, 4))
_DUCK_BOXES = ((1, 18, 55, 25),)
_OBSTACLES = {
    "small": {"width": 17, "height": 35, "x": 228, "y": 105,
              "boxes": ((0, 7, 5, 27), (4, 0, 6, 34), (10, 4, 7, 14))},
    "large": {"width": 25, "height": 50, "x": 332, "y": 90,
              "boxes": ((0, 12, 7, 38), (8, 0, 7, 49), (13, 10, 10, 38))},
    "bird": {"width": 46, "height": 40, "x": 134, "y": 75,
             "boxes": ((15, 15, 16, 5), (18, 21, 24, 6), (2, 14, 4, 3),
                       (6, 10, 4, 7), (10, 8, 6, 9))},
}


@dataclass
class Obstacle:
    kind: str
    x: float
    y: float
    count: int = 1
    gap: float = 160.0
    speed_offset: float = 0.0

    @property
    def width(self):
        return _OBSTACLES[self.kind]["width"] * self.count

    @property
    def height(self):
        return _OBSTACLES[self.kind]["height"]

    def collision_boxes(self):
        boxes = list(_OBSTACLES[self.kind]["boxes"])
        if self.count > 1:
            a, b, c = boxes
            boxes[1] = (b[0], b[1], self.width - a[2] - c[2], b[3])
            boxes[2] = (self.width - c[2], c[1], c[2], c[3])
        return [(self.x + x, self.y + y, w, h) for x, y, w, h in boxes]


def _overlap(a, b):
    return (a[0] < b[0] + b[2] and a[0] + a[2] > b[0]
            and a[1] < b[1] + b[3] and a[1] + a[3] > b[1])


class DinoGame:
    """Small-screen adaptation of Chromium's original runner.

    ``update`` accepts elapsed seconds and held jump/duck states. A fresh jump
    starts the title screen or restarts a crashed round after a short debounce.
    ``restart`` immediately starts a fresh round, preserving the RAM high score.
    """

    def __init__(self, width=320, height=150, seed=None):
        if not 240 <= width <= 600 or not 150 <= height <= 240:
            raise ValueError("Supported viewport: width 240..600, height 150..240")
        self.width, self.height = int(width), int(height)
        self.rng = random.Random(seed)
        self._scale = min(1.0, self.width / 600.0 * 1.2)
        self.ground_y = self.height - 57
        self.dino_x = 35
        self.high_score = 0
        self.elapsed = 0.0
        self._accumulator = 0.0
        self._jump_was_held = False
        self._jump_pending = False
        self._jump_held = False
        self._duck_held = False
        with Image.open(Path(__file__).parent / "assets/100-offline-sprite.png") as im:
            self._sheet = im.convert("RGBA")
        self._cache = {}
        self._font = ImageFont.load_default()
        self._reset_round()
        self.state = "title"

    @property
    def game_over(self):
        return self.state == "game_over"

    @property
    def score(self):
        return int(self.distance * 0.025)

    def _reset_round(self):
        self.state = "running"
        self.speed = 6.0 * self._scale
        self.distance = 0.0
        self.running_time = 0.0
        self.crash_time = 0.0
        self.y = float(self.ground_y)
        self.velocity = 0.0
        self.jumping = False
        self.ducking = False
        self._reached_min_height = False
        self._fast_fall = False
        self.obstacles = []
        self._history = []
        self.horizon_x = 0.0
        self.night = False
        self._night_remaining = 0.0
        self._next_night_score = 700
        self._moon_phase = 0
        self.clouds = [[self.width * 0.45, 30], [self.width * 0.9, 50]]

    def restart(self):
        self._reset_round()
        self._accumulator = 0.0
        self._jump_pending = False

    def update(self, dt, jump=False, duck=False):
        if not math.isfinite(dt) or dt < 0:
            raise ValueError("dt must be finite, non-negative seconds")
        jump, duck = bool(jump), bool(duck)
        self._jump_pending |= jump and not self._jump_was_held
        self._jump_was_held = jump
        self._jump_held, self._duck_held = jump, duck
        # Do not simulate an unbounded backlog after a paused or suspended app.
        self._accumulator += min(float(dt), 0.25)
        while self._accumulator + 1e-12 >= STEP:
            event, self._jump_pending = self._jump_pending, False
            self._step(event)
            self._accumulator = max(0.0, self._accumulator - STEP)

    def _step(self, jump_event):
        self.elapsed += STEP
        if self.state == "title":
            if jump_event:
                self._reset_round()
                self._start_jump()
            return
        if self.game_over:
            self.crash_time += STEP
            if jump_event and self.crash_time >= 0.35:
                self._reset_round()
                self._start_jump()
            return

        self.running_time += STEP
        self.ducking = self._duck_held and not self.jumping
        if jump_event and not self.jumping and not self.ducking:
            self._start_jump()
        if self.jumping:
            if self._duck_held and not self._fast_fall:
                self._fast_fall, self.velocity = True, 1.0
            self.y += self.velocity * (3 if self._fast_fall else 1)
            self.velocity += 0.6
            if self.y <= self.ground_y - 30:
                self._reached_min_height = True
            if ((not self._jump_held and self._reached_min_height)
                    or self.y <= self.height - 120):
                self.velocity = max(self.velocity, -5.0)
            if self.y >= self.ground_y:
                self.y, self.velocity = float(self.ground_y), 0.0
                self.jumping = self._fast_fall = False
                self.ducking = self._duck_held

        self.horizon_x = (self.horizon_x + self.speed) % 600
        for cloud in self.clouds:
            cloud[0] -= 0.2 * self.speed
            if cloud[0] < -46:
                cloud[:] = [self.width + self.rng.randrange(30, 150),
                            self.rng.randrange(20, 60)]
        for obstacle in self.obstacles:
            obstacle.x -= self.speed + obstacle.speed_offset
        self.obstacles = [o for o in self.obstacles if o.x + o.width > 0]
        if self.running_time >= 3.0:
            if not self.obstacles or (self.obstacles[-1].x + self.obstacles[-1].width
                                      + self.obstacles[-1].gap < self.width):
                self._spawn_obstacle()
        if any(self._collides(o) for o in self.obstacles):
            self.state = "game_over"
            self.high_score = max(self.high_score, self.score)
            self.crash_time = 0.0
            return
        self.distance += self.speed
        self.speed = min(13.0 * self._scale, self.speed + 0.001 * self._scale)
        if self.night:
            self._night_remaining -= STEP
            if self._night_remaining <= 0:
                self.night = False
        elif self.score >= self._next_night_score:
            self.night = True
            self._night_remaining = 12.0
            self._next_night_score += 700
            self._moon_phase = (self._moon_phase + 1) % 7

    def _start_jump(self):
        self.jumping = True
        self.ducking = self._fast_fall = self._reached_min_height = False
        self.velocity = -10.0 - self.speed / 10.0

    def _spawn_obstacle(self):
        choices = ["small", "large"]
        if self.speed >= 8.5 * self._scale:
            choices.append("bird")
        if len(self._history) >= 2 and self._history[-1] == self._history[-2]:
            choices = [c for c in choices if c != self._history[-1]]
        kind = self.rng.choice(choices)
        minimum = (4 if kind == "small" else 7) * self._scale
        count = self.rng.randint(1, 3) if kind != "bird" and self.speed >= minimum else 1
        data = _OBSTACLES[kind]
        y = (self.rng.choice((100, 75, 50)) if kind == "bird" else data["y"])
        y += self.height - 150
        minimum_gap = round(data["width"] * count * self.speed
                            + (150 if kind == "bird" else 120) * 0.6)
        obstacle = Obstacle(kind, float(self.width + 8), y, count,
                            self.rng.randint(minimum_gap, round(minimum_gap * 1.5)),
                            self.rng.choice((-0.8, 0.8)) * self._scale if kind == "bird" else 0.0)
        self.obstacles.append(obstacle)
        self._history.append(kind)
        self._history = self._history[-2:]

    def _collides(self, obstacle):
        boxes = _DUCK_BOXES if self.ducking else _RUN_BOXES
        # Match Chromium's inset collision origin; artwork includes a 1px border.
        dino_boxes = [(self.dino_x + 1 + x, self.y + 1 + y, w, h)
                      for x, y, w, h in boxes]
        return any(_overlap(a, b) for a in dino_boxes for b in obstacle.collision_boxes())

    def _sprite(self, x, y, width, height):
        key = (x, y, width, height)
        if key not in self._cache:
            self._cache[key] = self._sheet.crop((x, y, x + width, y + height))
        return self._cache[key]

    def _paste(self, canvas, sprite, x, y):
        canvas.paste(sprite, (round(x), round(y)), sprite)

    def _number(self, canvas, value, x, y):
        for index, digit in enumerate("%05d" % (value % 100000)):
            self._paste(canvas, self._sprite(655 + int(digit) * 10, 2, 10, 13),
                        x + index * 11, y)

    def _center_text(self, canvas, text, y):
        draw = ImageDraw.Draw(canvas)
        bounds = draw.textbbox((0, 0), text, font=self._font)
        draw.text(((self.width - (bounds[2] - bounds[0])) // 2, y), text,
                  fill=(83, 83, 83), font=self._font)

    def render(self):
        """Return a new RGB frame. Rendering does not advance game state."""
        canvas = Image.new("RGB", (self.width, self.height), (247, 247, 247))
        if self.night:
            phases = (140, 120, 100, 60, 40, 20, 0)
            mw = 40 if self._moon_phase == 3 else 20
            self._paste(canvas, self._sprite(484 + phases[self._moon_phase], 2, mw, 40),
                        self.width - 70, 24)
            for i, x in enumerate((self.width // 3, self.width * 2 // 3)):
                self._paste(canvas, self._sprite(645, 2 + i * 9, 9, 9), x, 25 + i * 20)
        else:
            for x, y in self.clouds:
                self._paste(canvas, self._sprite(86, 2, 46, 14), x, y)
        # Two original 600px strips wrap smoothly; cached crops stay at native size.
        ground = self._sprite(2, 52, 600, 12)
        gx = -round(self.horizon_x)
        self._paste(canvas, ground, gx, self.height - 23)
        self._paste(canvas, ground, gx + 600, self.height - 23)
        for obstacle in self.obstacles:
            data = _OBSTACLES[obstacle.kind]
            if obstacle.kind == "bird":
                frame = int(self.running_time * 6) % 2
                sx = data["x"] + frame * data["width"]
            else:
                sx = data["x"] + data["width"] * obstacle.count * (obstacle.count - 1) // 2
            self._paste(canvas, self._sprite(sx, 2, obstacle.width, obstacle.height),
                        obstacle.x, obstacle.y)
        if self.game_over:
            offset, dw = 220, 44
        elif self.ducking:
            offset, dw = 264 + 59 * (int(self.running_time * 8) % 2), 59
        elif self.jumping:
            offset, dw = 0, 44
        elif self.state == "title":
            offset, dw = (44 if self.elapsed % 4 > 3.8 else 0), 44
        else:
            offset, dw = 88 + 44 * (int(self.running_time * 12) % 2), 44
        self._paste(canvas, self._sprite(848 + offset, 2, dw, 47), self.dino_x, self.y)
        self._number(canvas, self.score, self.width - 61, 5)
        if self.high_score:
            self._paste(canvas, self._sprite(755, 2, 20, 13), self.width - 155, 5)
            self._number(canvas, self.high_score, self.width - 131, 5)
        if self.state == "title":
            self._center_text(canvas, "NO INTERNET", 30)
            self._center_text(canvas, "PRESS UP TO START", 51)
        elif self.game_over:
            self._paste(canvas, self._sprite(655, 15, 191, 11), (self.width - 191) // 2, 39)
            restart_frame = min(7, int(self.crash_time / (0.875 / 8)))
            self._paste(canvas, self._sprite(2 + restart_frame * 36, 68, 36, 32),
                        (self.width - 36) // 2, 61)
        return ImageOps.invert(canvas) if self.night else canvas
