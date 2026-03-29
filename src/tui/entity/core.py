"""Energy entity — the visual body of Orchestrator.

A pulsing abstract energy form rendered on a PICO-8 framebuffer.
Core + orbiting particles + aura + breathing pulse + starfield + ripples.
All driven by system state data.
"""

import math
import random
from dataclasses import dataclass, field

from ..pico8.renderer import Pico8Renderer
from ..pico8.palette import DEPT_COLORS


@dataclass
class SystemSnapshot:
    """Minimal system state for driving the entity."""
    container_up: bool = True
    active_task_count: int = 0
    dept_active: list[str] = field(default_factory=list)
    has_alert: bool = False
    collecting: bool = False
    idle_seconds: float = 0.0


class Star:
    """Background star with twinkle."""
    __slots__ = ("x", "y", "base_col", "twinkle_phase", "twinkle_speed")

    def __init__(self, x: int, y: int):
        self.x = x
        self.y = y
        self.base_col = random.choice([1, 5, 17, 21])
        self.twinkle_phase = random.uniform(0, math.tau)
        self.twinkle_speed = random.uniform(0.02, 0.08)

    def update(self):
        self.twinkle_phase += self.twinkle_speed

    def color(self) -> int | None:
        v = math.sin(self.twinkle_phase)
        if v > 0.6:
            return 6   # bright flash
        if v > 0.2:
            return self.base_col
        if v > -0.3:
            return self.base_col
        return None  # invisible this frame


class Ripple:
    """Expanding ring from core."""
    __slots__ = ("radius", "max_radius", "speed", "color", "alive")

    def __init__(self, max_radius: float, speed: float, color: int):
        self.radius = 0.0
        self.max_radius = max_radius
        self.speed = speed
        self.color = color
        self.alive = True

    def update(self):
        self.radius += self.speed
        if self.radius > self.max_radius:
            self.alive = False

    def alpha(self) -> float:
        """Fade out as it expands. 1.0 → 0.0."""
        return max(0, 1.0 - self.radius / self.max_radius)


class DataDrop:
    """Vertical data rain drop."""
    __slots__ = ("x", "y", "speed", "length", "color", "alive", "_h")

    def __init__(self, x: int, y: int, h: int, color: int):
        self.x = x
        self.y = y
        self.speed = random.uniform(0.5, 1.5)
        self.length = random.randint(2, 5)
        self.color = color
        self.alive = True
        self._h = h

    def update(self):
        self.y += self.speed
        if self.y - self.length > self._h:
            self.alive = False


class OrbitalParticle:
    """A particle orbiting the core."""

    def __init__(self, angle: float, radius: float, speed: float, color: int, size: float = 1.0):
        self.angle = angle
        self.radius = radius
        self.speed = speed
        self.color = color
        self.size = size
        self.wobble_phase = random.uniform(0, math.tau)
        self.wobble_amp = random.uniform(0.5, 2.0)

    def update(self, dt: float):
        self.angle += self.speed * dt
        self.wobble_phase += 1.7 * dt

    def pos(self, cx: float, cy: float) -> tuple[float, float]:
        r = self.radius + math.sin(self.wobble_phase) * self.wobble_amp
        return (cx + math.cos(self.angle) * r, cy + math.sin(self.angle) * r)


class IncomingParticle:
    """A particle flying toward the core (data collection visual)."""

    def __init__(self, sx: float, sy: float, cx: float, cy: float, color: int):
        self.sx, self.sy = sx, sy
        self.cx, self.cy = cx, cy
        self.color = color
        self.progress = 0.0
        self.alive = True

    def update(self, dt: float):
        self.progress += dt * 0.8
        if self.progress >= 1.0:
            self.alive = False

    def pos(self) -> tuple[float, float]:
        t = min(self.progress, 1.0)
        t = t * t
        return (self.sx + (self.cx - self.sx) * t, self.sy + (self.cy - self.sy) * t)


class SpriteAnimation:
    """A set of indexed sprite frames that can be blitted to the renderer."""

    def __init__(self, frames: list, frame_delay: int = 4):
        self.frames = frames  # list of np.ndarray (H, W)
        self.frame_delay = frame_delay
        self._tick = 0

    def update(self):
        self._tick += 1

    @property
    def current_frame(self):
        idx = (self._tick // self.frame_delay) % len(self.frames)
        return self.frames[idx]

    def draw(self, r, cx: int, cy: int, scale: float = 1.0):
        """Blit current frame centered at (cx, cy). Palette idx 0 = transparent."""
        frame = self.current_frame
        h, w = frame.shape
        # Scale dimensions
        dw, dh = int(w * scale), int(h * scale)
        x0 = cx - dw // 2
        y0 = cy - dh // 2

        if scale == 1.0:
            for sy in range(h):
                for sx in range(w):
                    col = int(frame[sy, sx])
                    if col != 0:
                        r.pset(x0 + sx, y0 + sy, col)
        else:
            for dy in range(dh):
                for dx in range(dw):
                    sy = int(dy / scale)
                    sx = int(dx / scale)
                    if 0 <= sy < h and 0 <= sx < w:
                        col = int(frame[sy, sx])
                        if col != 0:
                            r.pset(x0 + dx, y0 + dy, col)


class EnergyEntity:
    """The living energy form of Orchestrator."""

    SHAPES = ["circle", "diamond", "hexagon"]

    def __init__(self, core_sprite: SpriteAnimation | None = None):
        self.frame = 0
        self.breath_phase = 0.0
        self.orbitals: list[OrbitalParticle] = []
        self.incoming: list[IncomingParticle] = []
        self.stars: list[Star] = []
        self.ripples: list[Ripple] = []
        self.data_drops: list[DataDrop] = []
        self._last_snap = SystemSnapshot()
        self._alert_flash = 0
        self._shape_idx = 0
        self._shape_morph_timer = 0
        self._stars_inited = False
        self.core_sprite = core_sprite  # optional sprite-based core

        # Seed ambient orbitals
        for i in range(5):
            angle = (math.tau / 5) * i + random.uniform(-0.3, 0.3)
            self.orbitals.append(OrbitalParticle(
                angle=angle,
                radius=random.uniform(14, 22),
                speed=random.uniform(0.02, 0.05),
                color=random.choice([1, 5, 12, 13]),
                size=1.0,
            ))

    def _init_stars(self, w: int, h: int):
        """Lazy-init star field to match canvas size."""
        self.stars.clear()
        count = max(20, (w * h) // 120)
        for _ in range(count):
            self.stars.append(Star(random.randint(0, w - 1), random.randint(0, h - 1)))
        self._stars_inited = True

    def update(self, snap: SystemSnapshot):
        self._last_snap = snap
        self.frame += 1
        dt = 1.0

        # Breathing
        if not snap.container_up:
            self.breath_phase += 0.03 + math.sin(self.frame * 0.7) * 0.02
        elif snap.active_task_count > 0:
            self.breath_phase += 0.08 + snap.active_task_count * 0.01
        else:
            self.breath_phase += 0.04

        # Shape morphing: change shape every ~120 frames when busy
        self._shape_morph_timer += 1
        morph_interval = 80 if snap.active_task_count > 0 else 200
        if self._shape_morph_timer >= morph_interval:
            self._shape_morph_timer = 0
            self._shape_idx = (self._shape_idx + 1) % len(self.SHAPES)

        # Stars
        for s in self.stars:
            s.update()

        # Orbitals
        for p in self.orbitals:
            speed_mult = 1.5 if snap.active_task_count > 0 else 0.7
            p.update(dt * speed_mult)

        target = 5 + snap.active_task_count * 2
        while len(self.orbitals) < target:
            dept_colors = [DEPT_COLORS.get(d, 12) for d in snap.dept_active] or [12]
            self.orbitals.append(OrbitalParticle(
                angle=random.uniform(0, math.tau),
                radius=random.uniform(12, 25),
                speed=random.uniform(0.03, 0.07),
                color=random.choice(dept_colors),
                size=random.uniform(0.8, 1.5),
            ))
        while len(self.orbitals) > target and len(self.orbitals) > 3:
            self.orbitals.pop()

        # Ripples — spawn periodically
        ripple_interval = 30 if snap.active_task_count > 0 else 60
        if snap.container_up and self.frame % ripple_interval == 0:
            self.ripples.append(Ripple(
                max_radius=35 + snap.active_task_count * 5,
                speed=0.6 + snap.active_task_count * 0.1,
                color=self._aura_color(snap),
            ))
        for rip in self.ripples:
            rip.update()
        self.ripples = [rip for rip in self.ripples if rip.alive]

        # Data rain — background effect, stronger when collecting
        if snap.container_up:
            drop_chance = 0.3 if snap.collecting else 0.06
            if random.random() < drop_chance:
                # Will set x/h at draw time when we know dimensions
                self.data_drops.append(DataDrop(0, 0, 0, random.choice([1, 3, 17, 19])))
        for dd in self.data_drops:
            dd.update()
        self.data_drops = [dd for dd in self.data_drops if dd.alive]

        # Incoming
        if snap.collecting and self.frame % 6 == 0:
            self.incoming.append(IncomingParticle(0, 0, 0, 0, random.choice([11, 3, 12])))
        for ip in self.incoming:
            ip.update(dt)
        self.incoming = [ip for ip in self.incoming if ip.alive]

        # Alert flash
        if snap.has_alert:
            self._alert_flash = (self._alert_flash + 1) % 12
        else:
            self._alert_flash = 0

        # Core sprite animation
        if self.core_sprite:
            # Speed up animation when busy
            speed = 1 + snap.active_task_count
            for _ in range(speed):
                self.core_sprite.update()

    def draw(self, r: Pico8Renderer):
        snap = self._last_snap
        W, H = r.width, r.height
        cx, cy = W // 2, H // 2

        if not self._stars_inited:
            self._init_stars(W, H)

        r.cls(0)

        # ── Layer 0: Star field ──
        for s in self.stars:
            col = s.color()
            if col is not None:
                r.pset(s.x, s.y, col)

        # ── Layer 1: Data rain ──
        for dd in self.data_drops:
            if dd.x == 0:
                dd.x = random.randint(0, W - 1)
                dd._h = H
            head_y = int(dd.y)
            for i in range(dd.length):
                py = head_y - i
                if 0 <= py < H:
                    col = dd.color if i == 0 else 17
                    r.pset(dd.x, py, col)

        # ── Layer 2: Ripples ──
        for rip in self.ripples:
            radius = int(rip.radius)
            if radius < 2:
                continue
            alpha = rip.alpha()
            # Sparse circle — fewer points as it fades
            density = max(0.05, alpha * 0.5)
            col = rip.color if alpha > 0.5 else (1 if rip.color == 12 else 5)
            points = max(8, int(radius * math.tau * 0.4))
            for i in range(points):
                if random.random() > density:
                    continue
                angle = (math.tau / points) * i
                px = int(cx + math.cos(angle) * radius)
                py = int(cy + math.sin(angle) * radius)
                if 0 <= px < W and 0 <= py < H:
                    r.pset(px, py, col)

        # ── Layer 3: Aura (outer glow) ──
        aura_color = self._aura_color(snap)
        breath = math.sin(self.breath_phase) * 0.5 + 0.5
        base_r = 18 + breath * 4

        if snap.container_up:
            for i in range(3):
                ring_r = int(base_r + 8 + i * 5)
                self._dither_circ(r, cx, cy, ring_r, 1 if i < 2 else 17, 0.3 - i * 0.08)

        # ── Layer 4: Constellation lines between orbitals ──
        if snap.container_up and len(self.orbitals) >= 2:
            # Connect nearby pairs, cycle which ones are visible
            visible_line_phase = (self.frame // 15) % max(1, len(self.orbitals))
            positions = [(p, p.pos(cx, cy)) for p in self.orbitals]
            for i, (p1, (x1, y1)) in enumerate(positions):
                if (i + visible_line_phase) % 3 != 0:
                    continue
                # Find nearest neighbor
                best_dist = 999
                best_j = -1
                for j, (p2, (x2, y2)) in enumerate(positions):
                    if i == j:
                        continue
                    d = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
                    if d < best_dist:
                        best_dist = d
                        best_j = j
                if best_j >= 0 and best_dist < 30:
                    _, (x2, y2) = positions[best_j]
                    # Dashed line
                    self._dashed_line(r, int(x1), int(y1), int(x2), int(y2), 1)

        # ── Layer 5: Core ──
        core_r = int(8 + breath * 3)
        shape = self.SHAPES[self._shape_idx]

        if not snap.container_up:
            if self.core_sprite:
                # Dim flickering sprite
                if self.frame % 6 < 3:
                    self.core_sprite.draw(r, cx, cy, scale=0.8)
            else:
                if self.frame % 6 < 3:
                    r.circfill(cx, cy, core_r - 2, 5)
                    r.circ(cx, cy, core_r - 2, 1)
            return

        if self.core_sprite:
            # Sprite-based core with breathing scale
            scale = 0.9 + breath * 0.2
            self.core_sprite.draw(r, cx, cy, scale=scale)
            # Alert overlay
            if snap.has_alert and self._alert_flash < 6:
                r.circ(cx, cy, int(16 * scale) + 2, 8)
                r.circ(cx, cy, int(16 * scale) + 3, 8)
        else:
            # Procedural core (fallback)
            if snap.has_alert:
                flash_col = 8 if self._alert_flash < 6 else 2
                self._draw_shape(r, cx, cy, core_r + 2, shape, flash_col, filled=True)
                self._draw_shape(r, cx, cy, core_r, shape, 7, filled=True)
                self._draw_shape(r, cx, cy, core_r + 3, shape, 8, filled=False)
            else:
                self._draw_shape(r, cx, cy, core_r, shape, aura_color, filled=True)
                self._draw_shape(r, cx, cy, max(2, core_r - 3), shape, 7, filled=True)
                spot_r = max(1, int(2 + breath * 1.5))
                r.circfill(cx, cy, spot_r, 7)
                self._draw_shape(r, cx, cy, core_r + 1, shape, aura_color, filled=False)

        # ── Layer 6: Orbital particles ──
        for p in self.orbitals:
            px, py = p.pos(cx, cy)
            ipx, ipy = int(px), int(py)
            if 0 <= ipx < W and 0 <= ipy < H:
                if p.size > 1.2:
                    r.rectfill(ipx - 1, ipy - 1, ipx + 1, ipy + 1, p.color)
                else:
                    r.pset(ipx, ipy, p.color)
                    trail_x = int(px - math.cos(p.angle) * 3)
                    trail_y = int(py - math.sin(p.angle) * 3)
                    if 0 <= trail_x < W and 0 <= trail_y < H:
                        r.pset(trail_x, trail_y, 1)
                    trail_x2 = int(px - math.cos(p.angle) * 5)
                    trail_y2 = int(py - math.sin(p.angle) * 5)
                    if 0 <= trail_x2 < W and 0 <= trail_y2 < H:
                        r.pset(trail_x2, trail_y2, 17)

        # ── Layer 7: Incoming data particles ──
        for ip in self.incoming:
            ip.cx, ip.cy = cx, cy
            if ip.sx == 0 and ip.sy == 0:
                edge = random.choice(["top", "bot", "left", "right"])
                if edge == "top":
                    ip.sx, ip.sy = random.randint(10, W - 10), 2
                elif edge == "bot":
                    ip.sx, ip.sy = random.randint(10, W - 10), H - 2
                elif edge == "left":
                    ip.sx, ip.sy = 2, random.randint(10, H - 10)
                else:
                    ip.sx, ip.sy = W - 2, random.randint(10, H - 10)
            px, py = ip.pos()
            ipx, ipy = int(px), int(py)
            if 0 <= ipx < W and 0 <= ipy < H:
                r.pset(ipx, ipy, ip.color)
                # Small trail
                t = max(0, ip.progress - 0.05)
                tx = int(ip.sx + (ip.cx - ip.sx) * t * t)
                ty = int(ip.sy + (ip.cy - ip.sy) * t * t)
                if 0 <= tx < W and 0 <= ty < H:
                    r.pset(tx, ty, 1)

        # ── Layer 8: Ambient sparkle near core ──
        if self.frame % 2 == 0:
            for _ in range(3):
                angle = random.uniform(0, math.tau)
                dist = random.uniform(10, 32)
                sx = int(cx + math.cos(angle) * dist)
                sy = int(cy + math.sin(angle) * dist)
                if 0 <= sx < W and 0 <= sy < H:
                    r.pset(sx, sy, random.choice([5, 6, 13]))

    def _aura_color(self, snap: SystemSnapshot) -> int:
        if snap.has_alert:
            return 8
        if snap.active_task_count >= 3:
            return 9
        if snap.active_task_count > 0:
            return 12
        if snap.idle_seconds > 300:
            return 1
        return 12

    def _dither_circ(self, r: Pico8Renderer, cx: int, cy: int,
                     radius: int, col: int, density: float):
        points = max(8, int(radius * math.tau * 0.5))
        for i in range(points):
            if random.random() > density:
                continue
            angle = (math.tau / points) * i + self.breath_phase * 0.3
            px = int(cx + math.cos(angle) * radius)
            py = int(cy + math.sin(angle) * radius)
            if 0 <= px < r.width and 0 <= py < r.height:
                r.pset(px, py, col)

    def _dashed_line(self, r: Pico8Renderer, x0: int, y0: int, x1: int, y1: int, col: int):
        """Draw a dashed line (3 on, 3 off)."""
        dx = x1 - x0
        dy = y1 - y0
        dist = max(1, int(math.sqrt(dx * dx + dy * dy)))
        for i in range(0, dist, 2):
            if (i // 3) % 2 == 1:
                continue
            t = i / dist
            px = int(x0 + dx * t)
            py = int(y0 + dy * t)
            if 0 <= px < r.width and 0 <= py < r.height:
                r.pset(px, py, col)

    def _draw_shape(self, r: Pico8Renderer, cx: int, cy: int, radius: int,
                    shape: str, col: int, filled: bool):
        """Draw core shape: circle, diamond, or hexagon."""
        if shape == "circle":
            if filled:
                r.circfill(cx, cy, radius, col)
            else:
                r.circ(cx, cy, radius, col)
        elif shape == "diamond":
            pts = [
                (cx, cy - radius), (cx + radius, cy),
                (cx, cy + radius), (cx - radius, cy),
            ]
            if filled:
                self._fill_polygon(r, pts, col)
            else:
                self._draw_polygon(r, pts, col)
        elif shape == "hexagon":
            pts = []
            for i in range(6):
                angle = math.tau / 6 * i - math.pi / 6
                pts.append((int(cx + math.cos(angle) * radius),
                            int(cy + math.sin(angle) * radius)))
            if filled:
                self._fill_polygon(r, pts, col)
            else:
                self._draw_polygon(r, pts, col)

    def _draw_polygon(self, r: Pico8Renderer, pts: list[tuple[int, int]], col: int):
        for i in range(len(pts)):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % len(pts)]
            r.line(x0, y0, x1, y1, col)

    def _fill_polygon(self, r: Pico8Renderer, pts: list[tuple[int, int]], col: int):
        """Scanline fill a convex polygon."""
        if not pts:
            return
        min_y = max(0, min(p[1] for p in pts))
        max_y = min(r.height - 1, max(p[1] for p in pts))
        n = len(pts)
        for y in range(min_y, max_y + 1):
            intersections: list[int] = []
            for i in range(n):
                x0, y0 = pts[i]
                x1, y1 = pts[(i + 1) % n]
                if y0 == y1:
                    continue
                if min(y0, y1) <= y < max(y0, y1):
                    x = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
                    intersections.append(int(x))
            intersections.sort()
            for j in range(0, len(intersections) - 1, 2):
                r.line(intersections[j], y, intersections[j + 1], y, col)
