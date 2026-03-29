"""Auto-playing Pong screensaver — two paddles, system state drives tempo.

Left paddle = Orchestrator (smart AI)
Right paddle = "opponent" (slightly dumber AI)
Ball speed = system activity

State mapping:
  IDLE   — slow rally
  WORK   — faster, more intense
  ALERT  — ball turns red, shakes
  DOWN   — both paddles freeze, ball drifts
"""

import math
import random

from ..pico8.renderer import Pico8Renderer
from ..pico8.palette import DEPT_COLORS
from .core import SystemSnapshot

BG = 0
PADDLE_COL = 12
BALL_COL = 7
NET_COL = 17      # ghost
SCORE_COL = 5


class PongScene:
    """Self-playing Pong."""

    def __init__(self):
        self.frame = 0
        self.ball_x = 40.0
        self.ball_y = 24.0
        self.ball_vx = 3.0
        self.ball_vy = 2.0
        self.left_y = 20.0
        self.right_y = 20.0
        self.paddle_h = 10.0
        self.score_l = 0
        self.score_r = 0
        self._tick_interval = 4
        self._tick_counter = 0

    def update(self, snap: SystemSnapshot, w: int, h: int):
        self.frame += 1

        # Rhythm tempo
        self._tick_interval = 4
        if snap.active_task_count > 0:
            self._tick_interval = max(2, 4 - snap.active_task_count)
        if snap.has_alert:
            self._tick_interval = 1

        self._tick_counter += 1
        if self._tick_counter < self._tick_interval:
            return
        self._tick_counter = 0

        # ── Physics step (on the beat) ──
        self.ball_x += self.ball_vx
        self.ball_y += self.ball_vy

        # Top/bottom walls
        if self.ball_y <= 2:
            self.ball_y = 2
            self.ball_vy = abs(self.ball_vy)
        if self.ball_y >= h - 3:
            self.ball_y = h - 3
            self.ball_vy = -abs(self.ball_vy)

        # Paddle AI — discrete jumps
        paddle_step = 4
        if snap.container_up:
            # Left paddle — snaps toward ball
            diff_l = self.ball_y - self.paddle_h / 2 - self.left_y
            if abs(diff_l) > paddle_step:
                self.left_y += paddle_step if diff_l > 0 else -paddle_step
            else:
                self.left_y += diff_l

            # Right paddle — slightly worse, with jitter
            target_r = self.ball_y - self.paddle_h / 2 + random.choice([-2, 0, 0, 2])
            diff_r = target_r - self.right_y
            if abs(diff_r) > paddle_step:
                self.right_y += paddle_step if diff_r > 0 else -paddle_step
            else:
                self.right_y += diff_r

        self.left_y = max(2, min(h - 2 - self.paddle_h, self.left_y))
        self.right_y = max(2, min(h - 2 - self.paddle_h, self.right_y))

        # Left paddle collision
        px_l = 6
        if (self.ball_vx < 0 and self.ball_x <= px_l + 3 and
            self.left_y <= self.ball_y <= self.left_y + self.paddle_h):
            self.ball_vx = abs(self.ball_vx)
            hit = (self.ball_y - self.left_y) / self.paddle_h - 0.5
            self.ball_vy = 2.0 * (1 if hit > 0 else -1) + hit

        # Right paddle collision
        px_r = w - 9
        if (self.ball_vx > 0 and self.ball_x >= px_r and
            self.right_y <= self.ball_y <= self.right_y + self.paddle_h):
            self.ball_vx = -abs(self.ball_vx)
            hit = (self.ball_y - self.right_y) / self.paddle_h - 0.5
            self.ball_vy = 2.0 * (1 if hit > 0 else -1) + hit

        # Scoring
        if self.ball_x < 0:
            self.score_r += 1
            self._reset_ball(w, h, 1)
        if self.ball_x > w:
            self.score_l += 1
            self._reset_ball(w, h, -1)

    def _reset_ball(self, w, h, direction):
        self.ball_x = w / 2
        self.ball_y = h / 2
        self.ball_vx = 0.5 * direction
        self.ball_vy = random.uniform(-0.3, 0.3)

    def draw(self, r: Pico8Renderer, snap: SystemSnapshot):
        W, H = r.width, r.height
        r.cls(BG)

        # Center net
        for y in range(2, H - 2, 4):
            r.line(W // 2, y, W // 2, min(y + 2, H - 2), NET_COL)

        # Paddles
        col = PADDLE_COL if snap.container_up else 5
        r.rectfill(4, int(self.left_y), 6, int(self.left_y + self.paddle_h), col)
        r.rectfill(W - 7, int(self.right_y), W - 5, int(self.right_y + self.paddle_h), col)

        # Ball
        bx, by = int(self.ball_x), int(self.ball_y)
        ball_c = 8 if snap.has_alert else BALL_COL
        r.circfill(bx, by, 2, ball_c)

        # Score
        r.print(str(self.score_l), W // 2 - 14, 3, SCORE_COL)
        r.print(str(self.score_r), W // 2 + 6, 3, SCORE_COL)

        # Status dots
        dy = H - 4
        dept_order = ["engineering", "quality", "protocol",
                      "operations", "security", "personnel"]
        for i, dept in enumerate(dept_order):
            dx = 4 + i * 4
            c = DEPT_COLORS.get(dept, 12) if dept in snap.dept_active else 17
            r.pset(dx, dy, c)
            r.pset(dx + 1, dy, c)
