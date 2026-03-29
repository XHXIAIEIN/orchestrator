"""Auto-playing Breakout screensaver — system state drives gameplay.

Ball speed = system activity level
Bricks = tasks/departments
Paddle = Orchestrator (never misses... unless container is down)
Brick colors = department colors

State mapping:
  IDLE   — slow ball, few bricks, relaxed
  WORK   — faster ball, more bricks, active
  ALERT  — ball goes red, screen flash
  DOWN   — paddle disappears, ball falls
"""

import math
import random
from dataclasses import dataclass, field

from ..pico8.renderer import Pico8Renderer
from ..pico8.palette import DEPT_COLORS
from .core import SystemSnapshot

# Colors
BG = 0
PADDLE_COL = 12    # blue
BALL_COL = 7       # white
WALL_COL = 5       # dark gray
SCORE_COL = 6      # light gray
ALERT_BALL = 8     # red


@dataclass
class Brick:
    x: float
    y: float
    w: float
    h: float
    color: int
    alive: bool = True
    flash: int = 0  # flash frames on hit


@dataclass
class Ball:
    x: float
    y: float
    vx: float
    vy: float
    radius: float = 2.0


class BreakoutScene:
    """Self-playing Breakout that reflects Orchestrator state."""

    def __init__(self):
        self.frame = 0
        self.ball = Ball(x=40, y=30, vx=3, vy=-2)
        self.paddle_x = 30.0
        self.paddle_w = 16.0
        self.bricks: list[Brick] = []
        self.score = 0
        self._last_state = ""
        self._flash_screen = 0
        self._initialized = False
        self._hit_particles: list[dict] = []
        self._tick_interval = 4    # frames between physics steps
        self._tick_counter = 0

    def _init_bricks(self, w: int, h: int, snap: SystemSnapshot):
        """Generate bricks based on system state."""
        self.bricks.clear()
        margin = 4
        brick_h = 3
        gap = 1

        # Number of rows based on activity
        rows = 3 if snap.active_task_count == 0 else min(6, 2 + snap.active_task_count)
        cols = max(4, (w - margin * 2) // 10)
        brick_w = (w - margin * 2 - (cols - 1) * gap) / cols

        # Color per row — use dept colors when depts are active
        dept_cols = [DEPT_COLORS.get(d, 12) for d in snap.dept_active]
        row_colors = [12, 8, 14, 9, 11, 10]  # fallback: blue red pink orange green yellow

        for row in range(rows):
            color = dept_cols[row % len(dept_cols)] if dept_cols else row_colors[row % len(row_colors)]
            for col in range(cols):
                bx = margin + col * (brick_w + gap)
                by = 8 + row * (brick_h + gap)
                self.bricks.append(Brick(x=bx, y=by, w=brick_w, h=brick_h, color=color))

    def update(self, snap: SystemSnapshot, w: int, h: int):
        self.frame += 1

        # Initialize or rebuild bricks when state changes
        state_key = f"{snap.active_task_count}-{snap.container_up}-{len(snap.dept_active)}"
        if not self._initialized or (state_key != self._last_state and not any(b.alive for b in self.bricks)):
            self._init_bricks(w, h, snap)
            self._initialized = True
            self._last_state = state_key

        # Rhythm: tick interval = tempo. Busier = faster beat
        self._tick_interval = 4
        if snap.active_task_count > 0:
            self._tick_interval = max(2, 4 - snap.active_task_count)
        if snap.has_alert:
            self._tick_interval = 1

        # Only step physics on the beat
        self._tick_counter += 1
        if self._tick_counter < self._tick_interval:
            # Off-beat: only update cosmetics
            if self._flash_screen > 0:
                self._flash_screen -= 1
            for p in self._hit_particles:
                p["life"] -= 1
            self._hit_particles = [p for p in self._hit_particles if p["life"] > 0]
            return

        self._tick_counter = 0

        # ── Physics step (on the beat) ──

        # Fixed step size per beat — ball jumps discrete distances
        step = 3
        vx_sign = 1 if self.ball.vx > 0 else -1
        vy_sign = 1 if self.ball.vy > 0 else -1
        move_x = abs(self.ball.vx)
        move_y = abs(self.ball.vy)

        self.ball.x += move_x * vx_sign
        self.ball.y += move_y * vy_sign

        # Wall collisions
        r = self.ball.radius
        if self.ball.x - r <= 2:
            self.ball.x = 2 + r
            self.ball.vx = abs(self.ball.vx)
        if self.ball.x + r >= w - 2:
            self.ball.x = w - 2 - r
            self.ball.vx = -abs(self.ball.vx)
        if self.ball.y - r <= 2:
            self.ball.y = 2 + r
            self.ball.vy = abs(self.ball.vy)

        # Paddle AI — snaps to position on beat (no smooth lag)
        if snap.container_up:
            target = self.ball.x - self.paddle_w / 2
            if self.ball.vy > 0:
                steps_to_paddle = max(1, (h - 8 - self.ball.y) / max(0.1, abs(self.ball.vy)))
                target = self.ball.x + self.ball.vx * steps_to_paddle * 0.5 - self.paddle_w / 2
            # Discrete snap — move in fixed increments
            diff = target - self.paddle_x
            max_move = 6
            if abs(diff) > max_move:
                self.paddle_x += max_move if diff > 0 else -max_move
            else:
                self.paddle_x = target
            self.paddle_x = max(2, min(w - 2 - self.paddle_w, self.paddle_x))

        # Paddle collision
        paddle_y = h - 8
        if (self.ball.vy > 0 and
            self.ball.y + r >= paddle_y and
            self.ball.y + r <= paddle_y + 6 and
            self.paddle_x - 1 <= self.ball.x <= self.paddle_x + self.paddle_w + 1):
            self.ball.vy = -abs(self.ball.vy)
            hit_pos = (self.ball.x - self.paddle_x) / self.paddle_w
            self.ball.vx = step * (hit_pos - 0.5) * 2
            if abs(self.ball.vx) < 1:
                self.ball.vx = random.choice([-1, 1]) * 1.5
            self.ball.y = paddle_y - r

        # Ball falls below paddle
        if self.ball.y > h:
            self.ball.x = w / 2
            self.ball.y = h / 2
            self.ball.vy = -step
            self.ball.vx = random.choice([-1, 1]) * step * 0.7

        # Brick collisions
        for brick in self.bricks:
            if not brick.alive:
                continue
            if (brick.x <= self.ball.x <= brick.x + brick.w and
                brick.y - r <= self.ball.y <= brick.y + brick.h + r):
                brick.alive = False
                brick.flash = 3
                self.ball.vy = -self.ball.vy
                self.score += 1
                for _ in range(3):
                    self._hit_particles.append({
                        "x": self.ball.x, "y": brick.y + brick.h / 2,
                        "vx": random.uniform(-1.5, 1.5),
                        "vy": random.uniform(-1.0, 0.5),
                        "life": 4,
                        "color": brick.color,
                    })
                break

        # All bricks cleared → regenerate
        if not any(b.alive for b in self.bricks):
            self._init_bricks(w, h, snap)

        # Screen flash
        if self._flash_screen > 0:
            self._flash_screen -= 1
        if snap.has_alert and self.frame % 10 == 0:
            self._flash_screen = 1

    def draw(self, renderer: Pico8Renderer, snap: SystemSnapshot):
        W, H = renderer.width, renderer.height
        renderer.cls(BG)

        # Screen flash on alert
        if self._flash_screen > 0:
            renderer.rectfill(0, 0, W - 1, H - 1, 2)

        # Walls — subtle
        renderer.line(1, 1, W - 2, 1, WALL_COL)
        renderer.line(1, 1, 1, H - 1, WALL_COL)
        renderer.line(W - 2, 1, W - 2, H - 1, WALL_COL)

        # Bricks
        for brick in self.bricks:
            if brick.alive:
                renderer.rectfill(
                    int(brick.x), int(brick.y),
                    int(brick.x + brick.w - 1), int(brick.y + brick.h - 1),
                    brick.color
                )
            elif brick.flash > 0:
                brick.flash -= 1
                renderer.rectfill(
                    int(brick.x), int(brick.y),
                    int(brick.x + brick.w - 1), int(brick.y + brick.h - 1),
                    7  # white flash
                )

        # Hit particles
        for p in self._hit_particles:
            px, py = int(p["x"]), int(p["y"])
            if 0 <= px < W and 0 <= py < H:
                renderer.pset(px, py, p["color"])

        # Paddle
        if snap.container_up:
            paddle_y = H - 8
            renderer.rectfill(
                int(self.paddle_x), paddle_y,
                int(self.paddle_x + self.paddle_w), paddle_y + 2,
                PADDLE_COL
            )
        # Down state: no paddle, ball just bounces around walls

        # Ball
        bx, by = int(self.ball.x), int(self.ball.y)
        ball_col = ALERT_BALL if snap.has_alert else BALL_COL
        renderer.circfill(bx, by, int(self.ball.radius), ball_col)

        # Score — tiny, bottom right
        renderer.print(str(self.score), W - 16, H - 6, SCORE_COL)

        # Status dots — bottom left, same as before
        dy = H - 4
        dept_order = ["engineering", "quality", "protocol",
                      "operations", "security", "personnel"]
        for i, dept in enumerate(dept_order):
            dx = 4 + i * 4
            col = DEPT_COLORS.get(dept, 12) if dept in snap.dept_active else 17
            renderer.pset(dx, dy, col)
            renderer.pset(dx + 1, dy, col)
            renderer.pset(dx, dy + 1, col)
            renderer.pset(dx + 1, dy + 1, col)
