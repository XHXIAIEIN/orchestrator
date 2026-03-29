"""Demo: Arcade screensaver with auto-switching mini-games.

Run: python -m src.tui.demo_arcade
"""

from textual.app import App, ComposeResult
from textual.widgets import Static

from .pico8.renderer import Pico8Renderer
from .pico8.halfblock import render_to_markup
from .entity.core import SystemSnapshot
from .entity.arcade import ArcadeManager
from .entity.breakout import BreakoutScene
from .entity.pong import PongScene


class ArcadeCanvas(Static):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._mgr = ArcadeManager(switch_interval=500)
        self._mgr.register("breakout", BreakoutScene())
        self._mgr.register("pong", PongScene())
        self._renderer: Pico8Renderer | None = None
        self.snap = SystemSnapshot()
        self.demo_frame = 0

    def on_mount(self):
        self._resize()

    def on_resize(self):
        self._resize()

    def _resize(self):
        w = max(60, self.size.width)
        h = max(30, self.size.height * 2)
        self._renderer = Pico8Renderer(width=w, height=h)

    def tick(self):
        if self._renderer is None:
            return
        self.demo_frame += 1
        self.snap = self._demo_state()
        self._mgr.update(self.snap, self._renderer.width, self._renderer.height)
        self._mgr.draw(self._renderer, self.snap)
        self.update(render_to_markup(
            self._renderer.screen, self._renderer.width, self._renderer.height
        ))

    def _demo_state(self) -> SystemSnapshot:
        f = self.demo_frame
        cycle = f % 400
        if cycle < 80:
            return SystemSnapshot(container_up=True, active_task_count=0)
        elif cycle < 200:
            tasks = min(4, 1 + (cycle - 80) // 30)
            depts = ["engineering", "quality", "operations", "security"][:tasks]
            return SystemSnapshot(
                container_up=True, active_task_count=tasks,
                dept_active=depts, collecting=(cycle % 15 < 5),
            )
        elif cycle < 260:
            return SystemSnapshot(
                container_up=True, active_task_count=2,
                dept_active=["engineering", "quality"], has_alert=True,
            )
        elif cycle < 340:
            return SystemSnapshot(container_up=True, active_task_count=1,
                                  dept_active=["quality"])
        else:
            return SystemSnapshot(container_up=False)


class StatusLine(Static):
    def update_info(self, mgr: ArcadeManager, snap: SystemSnapshot, frame: int):
        game = mgr.current_name.upper()
        remaining = mgr.switch_interval - mgr.frames_on_current
        self.update(
            f"  [rgb(29,173,255)]▸ {game}[/]"
            f"  │  next in {remaining // 10}s"
            f"  │  [Space] switch  [q] quit"
            f"  │  frame {frame}"
        )


class ArcadeDemo(App):
    CSS = """
    Screen { background: #000000; }
    ArcadeCanvas { width: 1fr; height: 1fr; }
    StatusLine {
        dock: bottom; height: 1;
        background: #1d2b53; color: #c2c3c7;
    }
    """
    BINDINGS = [("q", "quit", "Quit"), ("space", "switch", "Switch Game")]

    def compose(self) -> ComposeResult:
        yield ArcadeCanvas(id="canvas")
        yield StatusLine(id="status")

    def on_mount(self):
        self.set_interval(1 / 12, self._tick)  # 12fps render, physics on beat

    def _tick(self):
        canvas = self.query_one("#canvas", ArcadeCanvas)
        canvas.tick()
        self.query_one("#status", StatusLine).update_info(
            canvas._mgr, canvas.snap, canvas.demo_frame
        )

    def action_switch(self):
        self.query_one("#canvas", ArcadeCanvas)._mgr.random_game()


def main():
    ArcadeDemo().run()

if __name__ == "__main__":
    main()
