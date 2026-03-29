"""Arcade screensaver manager — rotates between mini-games.

Each game implements the same interface:
  update(snap, w, h) — advance one tick
  draw(renderer, snap) — render current frame

Games switch automatically after a set duration or when a round ends.
Agent hook: set .agent_controller to override the built-in AI.
"""

import random
from typing import Protocol

from ..pico8.renderer import Pico8Renderer
from .core import SystemSnapshot


class ArcadeGame(Protocol):
    """Interface that all mini-games must implement."""
    frame: int

    def update(self, snap: SystemSnapshot, w: int, h: int) -> None: ...
    def draw(self, renderer: Pico8Renderer, snap: SystemSnapshot) -> None: ...


class AgentAction:
    """Action from an external agent controller.

    For Breakout: paddle_target (0.0 = left edge, 1.0 = right edge)
    For Pong: paddle_target (0.0 = top, 1.0 = bottom)
    """
    def __init__(self, paddle_target: float = 0.5):
        self.paddle_target = paddle_target


class AgentController(Protocol):
    """Interface for external agent (local LLM, etc.) to control games.

    Called once per frame. Receives game state, returns an action.
    """
    def decide(self, game_name: str, game_state: dict) -> AgentAction: ...


class ArcadeManager:
    """Manages rotation between mini-games."""

    def __init__(self, switch_interval: int = 600):
        """
        Args:
            switch_interval: frames between game switches (~60s at 10fps)
        """
        self.games: dict[str, ArcadeGame] = {}
        self.game_order: list[str] = []
        self.current_idx = 0
        self.switch_interval = switch_interval
        self.frames_on_current = 0
        self.agent_controller: AgentController | None = None

    def register(self, name: str, game: ArcadeGame):
        """Register a mini-game."""
        self.games[name] = game
        if name not in self.game_order:
            self.game_order.append(name)

    @property
    def current_name(self) -> str:
        if not self.game_order:
            return ""
        return self.game_order[self.current_idx % len(self.game_order)]

    @property
    def current_game(self) -> ArcadeGame | None:
        name = self.current_name
        return self.games.get(name)

    def next_game(self):
        """Switch to next game."""
        if self.game_order:
            self.current_idx = (self.current_idx + 1) % len(self.game_order)
            self.frames_on_current = 0

    def random_game(self):
        """Switch to a random different game."""
        if len(self.game_order) > 1:
            choices = [i for i in range(len(self.game_order)) if i != self.current_idx]
            self.current_idx = random.choice(choices)
            self.frames_on_current = 0

    def update(self, snap: SystemSnapshot, w: int, h: int):
        game = self.current_game
        if game is None:
            return

        self.frames_on_current += 1

        # Auto-switch
        if self.frames_on_current >= self.switch_interval:
            self.random_game()
            game = self.current_game
            if game is None:
                return

        game.update(snap, w, h)

    def draw(self, renderer: Pico8Renderer, snap: SystemSnapshot):
        game = self.current_game
        if game is None:
            return
        game.draw(renderer, snap)

    def get_game_state(self) -> dict:
        """Export current game state for agent controller.

        Returns a dict with game-specific state info that an agent
        can use to make decisions.
        """
        game = self.current_game
        if game is None:
            return {}

        name = self.current_name
        state = {"game": name, "frame": game.frame}

        # Game-specific state export
        if name == "breakout":
            from .breakout import BreakoutScene
            if isinstance(game, BreakoutScene):
                state.update({
                    "ball_x": game.ball.x, "ball_y": game.ball.y,
                    "ball_vx": game.ball.vx, "ball_vy": game.ball.vy,
                    "paddle_x": game.paddle_x, "paddle_w": game.paddle_w,
                    "bricks_alive": sum(1 for b in game.bricks if b.alive),
                    "score": game.score,
                })
        elif name == "pong":
            from .pong import PongScene
            if isinstance(game, PongScene):
                state.update({
                    "ball_x": game.ball_x, "ball_y": game.ball_y,
                    "ball_vx": game.ball_vx, "ball_vy": game.ball_vy,
                    "left_y": game.left_y, "right_y": game.right_y,
                    "score_l": game.score_l, "score_r": game.score_r,
                })

        return state
