"""Demo: Orchestrator energy entity in a Textual TUI.

Run: python -m src.tui.demo_entity
"""

import math
import random
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Static, Footer
from textual.reactive import reactive
from textual import work

from .pico8.renderer import Pico8Renderer
from .pico8.halfblock import render_to_markup
from .pico8.palette import PALETTE
from .entity.core import EnergyEntity, SpriteAnimation, SystemSnapshot


def _hex(idx: int) -> str:
    r, g, b = PALETTE[idx % 16]
    return f"#{r:02x}{g:02x}{b:02x}"


def _load_core_sprite() -> SpriteAnimation | None:
    """Try to load the rotating orb spritesheet. Returns None if not found."""
    sheet_path = Path(__file__).parent / "assets" / "rotating_orbs" / "PNG" / "32x32" / "rotating_orbs.png"
    if not sheet_path.exists():
        return None
    try:
        from .pico8.sprite_import import load_spritesheet
        all_frames = load_spritesheet(str(sheet_path), 32, 32, columns=4)
        # Use first orb (frames 0-3) — blue/cyan orb
        orb_frames = all_frames[0:4]
        return SpriteAnimation(orb_frames, frame_delay=3)
    except Exception:
        return None


class EntityCanvas(Static):
    """Widget that renders the energy entity via half-block characters."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        core_sprite = _load_core_sprite()
        self._entity = EnergyEntity(core_sprite=core_sprite)
        self._renderer: Pico8Renderer | None = None
        self._snap = SystemSnapshot()
        self._demo_frame = 0

    def on_mount(self):
        self._resize_renderer()

    def on_resize(self):
        self._resize_renderer()

    def _resize_renderer(self):
        # Each terminal col = 1 pixel width, each row = 2 pixel height (half-block)
        w = max(40, self.size.width)
        h = max(20, self.size.height * 2)
        self._renderer = Pico8Renderer(width=w, height=h)

    def tick(self):
        if self._renderer is None:
            return

        # Demo: cycle through states
        self._demo_frame += 1
        self._snap = self._demo_state()

        self._entity.update(self._snap)
        self._entity.draw(self._renderer)
        markup = render_to_markup(
            self._renderer.screen, self._renderer.width, self._renderer.height
        )
        self.update(markup)

    def _demo_state(self) -> SystemSnapshot:
        """Simulate state changes for demo purposes."""
        f = self._demo_frame
        cycle = f % 300  # 30-second cycle at 10fps

        if cycle < 60:
            # Idle
            return SystemSnapshot(
                container_up=True, active_task_count=0,
                idle_seconds=cycle * 0.5,
            )
        elif cycle < 140:
            # Working — tasks ramp up
            tasks = min(4, 1 + (cycle - 60) // 20)
            depts = ["engineering", "quality", "operations", "security"][:tasks]
            return SystemSnapshot(
                container_up=True, active_task_count=tasks,
                dept_active=depts, collecting=(cycle % 12 < 4),
            )
        elif cycle < 180:
            # Alert!
            return SystemSnapshot(
                container_up=True, active_task_count=2,
                dept_active=["engineering", "quality"],
                has_alert=True,
            )
        elif cycle < 220:
            # Recovery
            return SystemSnapshot(
                container_up=True, active_task_count=1,
                dept_active=["quality"],
            )
        elif cycle < 260:
            # Container down
            return SystemSnapshot(container_up=False)
        else:
            # Coming back up
            return SystemSnapshot(
                container_up=True, active_task_count=0,
                idle_seconds=0,
            )


class StatusLine(Static):
    """Bottom status showing current demo phase."""

    def update_phase(self, snap: SystemSnapshot, frame: int):
        cycle = frame % 300
        if cycle < 60:
            phase = "IDLE — 休眠呼吸"
            col = "rgb(29,173,255)"
        elif cycle < 140:
            phase = f"WORKING — {snap.active_task_count} tasks, {', '.join(snap.dept_active)}"
            col = "rgb(0,228,54)"
        elif cycle < 180:
            phase = "ALERT — supervisor 介入"
            col = "rgb(255,0,77)"
        elif cycle < 220:
            phase = "RECOVERY — 恢复中"
            col = "rgb(255,163,0)"
        elif cycle < 260:
            phase = "DOWN — 容器宕机"
            col = "rgb(95,87,79)"
        else:
            phase = "STARTUP — 重新上线"
            col = "rgb(194,195,199)"

        self.update(f"  [{col}]● {phase}[/]  │  frame {frame}")


class EntityDemo(App):
    CSS = """
    Screen {
        background: #000000;
    }
    EntityCanvas {
        width: 1fr;
        height: 1fr;
    }
    StatusLine {
        dock: bottom;
        height: 1;
        background: #1d2b53;
        color: #c2c3c7;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("space", "cycle", "Next Phase"),
    ]

    def compose(self) -> ComposeResult:
        yield EntityCanvas(id="canvas")
        yield StatusLine(id="status")

    def on_mount(self):
        self.set_interval(1 / 10, self._tick)  # 10 FPS

    def _tick(self):
        canvas = self.query_one("#canvas", EntityCanvas)
        canvas.tick()
        status = self.query_one("#status", StatusLine)
        status.update_phase(canvas._snap, canvas._demo_frame)

    def action_cycle(self):
        """Jump to next demo phase."""
        canvas = self.query_one("#canvas", EntityCanvas)
        cycle = canvas._demo_frame % 300
        if cycle < 60:
            canvas._demo_frame += (60 - cycle)
        elif cycle < 140:
            canvas._demo_frame += (140 - cycle)
        elif cycle < 180:
            canvas._demo_frame += (180 - cycle)
        elif cycle < 220:
            canvas._demo_frame += (220 - cycle)
        elif cycle < 260:
            canvas._demo_frame += (260 - cycle)
        else:
            canvas._demo_frame += (300 - cycle)


def main():
    app = EntityDemo()
    app.run()


if __name__ == "__main__":
    main()
