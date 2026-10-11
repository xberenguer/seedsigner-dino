"""Model and render tests; no display, GPIO or signer code is imported."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
GAME_PATH = ROOT / "payload/opt/dino/dino_game.py"
spec = importlib.util.spec_from_file_location("dino_game", GAME_PATH)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
DinoGame, Obstacle = module.DinoGame, module.Obstacle
STEP = module.STEP


def advance(game, seconds, jump=False, duck=False, rate=60):
    for _ in range(round(seconds * rate)):
        game.update(1 / rate, jump=jump, duck=duck)


def test_title_start_and_held_jump_does_not_autojump():
    game = DinoGame(seed=1)
    assert game.state == "title"
    game.update(STEP, jump=True)
    assert game.state == "running" and game.jumping
    advance(game, 1.4, jump=True)
    assert not game.jumping
    game.update(STEP, jump=False)
    game.update(STEP, jump=True)
    assert game.jumping


def test_substep_button_edge_is_not_lost():
    game = DinoGame(seed=1)
    game.update(0.005, jump=True)
    game.update(0.005, jump=False)
    game.update(0.01, jump=False)
    assert game.state == "running" and game.jumping


def test_fixed_step_is_independent_of_render_poll_rate():
    a, b = DinoGame(seed=4), DinoGame(seed=4)
    a.restart()
    b.restart()
    advance(a, 2, rate=30)
    advance(b, 2, rate=100)
    assert a.distance == pytest.approx(b.distance)
    assert a.speed == pytest.approx(b.speed)
    assert a.y == b.y
    assert a.render().tobytes() == b.render().tobytes()


def test_jump_release_shortens_jump_and_duck_speeds_descent():
    held, released, fast = (DinoGame(seed=5) for _ in range(3))
    for game in (held, released, fast):
        game.update(STEP, jump=True)
    held_apex = released_apex = 999
    for _ in range(45):
        held.update(STEP, jump=True)
        released.update(STEP, jump=False)
        held_apex = min(held_apex, held.y)
        released_apex = min(released_apex, released.y)
    assert released_apex > held_apex + 10
    advance(fast, 0.1, jump=True)
    y_before = fast.y
    fast.update(STEP, jump=False, duck=True)
    assert fast.y > y_before and fast.velocity > 0
    advance(fast, 0.5, duck=True)
    assert not fast.jumping and fast.ducking


def test_cactus_collision_and_bird_duck_clearance():
    game = DinoGame(seed=6)
    game.restart()
    cactus = Obstacle("small", game.dino_x, 105)
    assert game._collides(cactus)
    medium_bird = Obstacle("bird", game.dino_x, 75)
    assert game._collides(medium_bird)
    game.ducking = True
    assert not game._collides(medium_bird)
    assert game._collides(cactus)
    assert game._collides(Obstacle("bird", game.dino_x, 100))
    game.ducking = False
    game.y = 25
    assert not game._collides(cactus)


def test_crash_requires_fresh_jump_and_preserves_volatile_high_score():
    game = DinoGame(seed=7)
    game.restart()
    game.distance = 5000
    game.obstacles = [Obstacle("small", game.dino_x + 4, 105)]
    game.update(STEP)
    assert game.game_over and game.high_score == 125
    advance(game, 0.5)
    game.update(STEP, jump=True)
    assert not game.game_over and game.jumping and game.high_score == 125
    assert game.score == 0


def test_spawn_determinism_birds_and_grouped_cacti():
    a, b = DinoGame(seed=8), DinoGame(seed=8)
    a.speed = b.speed = 13 * a._scale
    for _ in range(40):
        a._spawn_obstacle()
        b._spawn_obstacle()
    assert a.obstacles == b.obstacles
    assert any(o.kind == "bird" for o in a.obstacles)
    assert any(o.count > 1 for o in a.obstacles)
    assert all(o.gap > 0 for o in a.obstacles)
    assert all(len(o.collision_boxes()) > 0 for o in a.obstacles)


def test_score_acceleration_cap_and_day_night_cycle():
    game = DinoGame(seed=9)
    game.restart()
    game.distance = 700 / 0.025
    before = game.speed
    game.update(STEP)
    assert game.score >= 700 and game.speed > before and game.night
    assert game.render().getpixel((0, 0)) == (8, 8, 8)
    game.obstacles.clear()
    game.running_time = -1000  # Isolate the 12s display cycle from collisions.
    advance(game, 12.1)
    assert not game.night
    game.speed = 13 * game._scale
    game.update(STEP)
    assert game.speed == 13 * game._scale


def test_render_dimensions_state_and_pinned_asset():
    game = DinoGame(seed=10)
    before = (game.elapsed, game.distance, game.rng.getstate())
    frame = game.render()
    assert frame.mode == "RGB" and frame.size == (320, 150)
    assert frame.tobytes() == game.render().tobytes()
    assert before == (game.elapsed, game.distance, game.rng.getstate())
    manifest = json.loads((GAME_PATH.parent / "source-manifest.json").read_text())
    record = next(f for f in manifest["files"] if f["path"].endswith("100-offline-sprite.png"))
    assert hashlib.sha256((GAME_PATH.parent / "assets/100-offline-sprite.png").read_bytes()).hexdigest() == record["sha256"]


@pytest.mark.parametrize("dt", [-1, float("inf"), float("nan")])
def test_invalid_time(dt):
    with pytest.raises(ValueError):
        DinoGame().update(dt)
