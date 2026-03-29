"""Demo: Game & Watch style Orchestrator LCD panel.

Run: python -m src.tui.demo_gw
"""

from textual.app import App, ComposeResult
from textual.widgets import Static

from .pico8.renderer import Pico8Renderer
from .pico8.halfblock import render_to_markup
from .entity.gw_scene import GWScene
from .entity.core import SystemSnapshot


class GWCanvas(Static):
    """Game & Watch LCD display widget."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._scene = GWScene()
        self._renderer: Pico8Renderer | None = None
        self._snap = SystemSnapshot()
        self._demo_frame = 0

    def on_mount(self):
        self._resize_renderer()

    def on_resize(self):
        self._resize_renderer()

    def _resize_renderer(self):
        w = max(60, self.size.width)
        h = max(30, self.size.height * 2)
        self._renderer = Pico8Renderer(width=w, height=h)

    def tick(self):
        if self._renderer is None:
            return
        self._demo_frame += 1
        self._snap = self._demo_state()
        self._scene.update(self._snap)
        self._scene.draw(self._renderer, self._snap)
        markup = render_to_markup(
            self._renderer.screen, self._renderer.width, self._renderer.height
        )
        self.update(markup)

    def _demo_state(self) -> SystemSnapshot:
        f = self._demo_frame
        cycle = f % 360

        if cycle < 80:
            return SystemSnapshot(
                container_up=True, active_task_count=0,
                idle_seconds=cycle * 1.5,
            )
        elif cycle < 100:
            return SystemSnapshot(
                container_up=True, active_task_count=0,
                idle_seconds=150,
            )
        elif cycle < 180:
            tasks = min(4, 1 + (cycle - 100) // 20)
            depts = ["engineering", "quality", "operations", "security"][:tasks]
            return SystemSnapshot(
                container_up=True, active_task_count=tasks,
                dept_active=depts, collecting=(cycle % 15 < 5),
            )
        elif cycle < 230:
            return SystemSnapshot(
                container_up=True, active_task_count=2,
                dept_active=["engineering", "quality"],
                has_alert=True,
            )
        elif cycle < 280:
            return SystemSnapshot(
                container_up=True, active_task_count=1,
                dept_active=["quality"],
            )
        elif cycle < 330:
            return SystemSnapshot(container_up=False)
        else:
            return SystemSnapshot(
                container_up=True, active_task_count=0,
                idle_seconds=0,
            )


class StatusLine(Static):
    def update_phase(self, snap: SystemSnapshot, frame: int):
        cycle = frame % 360
        if cycle < 80:
            phase, col = "IDLE", "rgb(29,173,255)"
        elif cycle < 100:
            phase, col = "SLEEP — idle_seconds > 120", "rgb(29,43,83)"
        elif cycle < 180:
            phase, col = f"WORK — {snap.active_task_count} tasks", "rgb(0,228,54)"
        elif cycle < 230:
            phase, col = "ALERT", "rgb(255,0,77)"
        elif cycle < 280:
            phase, col = "RECOVERY", "rgb(255,163,0)"
        elif cycle < 330:
            phase, col = "DOWN", "rgb(95,87,79)"
        else:
            phase, col = "STARTUP", "rgb(194,195,199)"
        self.update(f"  [{col}]● {phase}[/]  │  [Space] next  [q] quit  │  frame {frame}")


class GWDemo(App):
    CSS = """
    Screen { background: #000000; }
    GWCanvas { width: 1fr; height: 1fr; }
    StatusLine {
        dock: bottom; height: 1;
        background: #1d2b53; color: #c2c3c7;
    }
    """
    BINDINGS = [("q", "quit", "Quit"), ("space", "cycle", "Next")]

    def compose(self) -> ComposeResult:
        yield GWCanvas(id="canvas")
        yield StatusLine(id="status")

    def on_mount(self):
        self.set_interval(1 / 10, self._tick)

    def _tick(self):
        canvas = self.query_one("#canvas", GWCanvas)
        canvas.tick()
        self.query_one("#status", StatusLine).update_phase(canvas._snap, canvas._demo_frame)

    def action_cycle(self):
        canvas = self.query_one("#canvas", GWCanvas)
        cycle = canvas._demo_frame % 360
        boundaries = [80, 100, 180, 230, 280, 330, 360]
        for b in boundaries:
            if cycle < b:
                canvas._demo_frame += (b - cycle)
                break


def main():
    GWDemo().run()

if __name__ == "__main__":
    main()
