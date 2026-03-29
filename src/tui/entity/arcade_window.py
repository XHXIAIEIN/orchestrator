"""Arcade screensaver as a standalone pygame window — for Wisecoco secondary display.

Renders PICO-8 framebuffer directly to a pygame surface.
Designed to run borderless on the secondary monitor (1080x1240).

Usage:
    python -m src.tui.entity.arcade_window [--monitor 1] [--windowed]
"""

import sys
import time
import argparse

# Lazy imports so the module can be imported without pygame installed
def main():
    import pygame
    from ..pico8.renderer import Pico8Renderer
    from ..pico8.palette import PALETTE, PALETTE_EXT
    from .core import SystemSnapshot
    from .arcade import ArcadeManager
    from .breakout import BreakoutScene
    from .pong import PongScene

    parser = argparse.ArgumentParser(description="Arcade screensaver for secondary display")
    parser.add_argument("--monitor", type=int, default=1, help="Monitor index (0=primary, 1=secondary)")
    parser.add_argument("--windowed", action="store_true", help="Run in a window instead of fullscreen")
    parser.add_argument("--scale", type=int, default=0, help="Pixel scale factor (0=auto)")
    args = parser.parse_args()

    ALL_COLORS = PALETTE + PALETTE_EXT

    # ── Init pygame ──
    pygame.init()

    # Detect monitor position
    if args.windowed:
        screen_w, screen_h = 540, 620  # half of 1080x1240
        screen = pygame.display.set_mode((screen_w, screen_h))
    else:
        # Try to position on secondary monitor
        num_displays = pygame.display.get_num_displays() if hasattr(pygame.display, 'get_num_displays') else 1
        if num_displays > 1 and args.monitor > 0:
            try:
                bounds = pygame.display.get_desktop_sizes()
                # Position window on secondary display
                import os
                # Sum widths of monitors before target
                x_offset = sum(b[0] for b in bounds[:args.monitor])
                os.environ['SDL_VIDEO_WINDOW_POS'] = f"{x_offset},0"
            except Exception:
                pass
        screen_w, screen_h = 1080, 1240
        screen = pygame.display.set_mode((screen_w, screen_h), pygame.NOFRAME)

    pygame.display.set_caption("Orchestrator Arcade")

    # ── PICO-8 canvas — scale to fit screen ──
    # Use a retro resolution that fits the aspect ratio
    # 1080:1240 ≈ 0.87:1 — close to 7:8
    # Pick a clean pixel resolution
    canvas_w, canvas_h = 108, 124  # 10x scale to 1080x1240
    if args.scale > 0:
        canvas_w = screen_w // args.scale
        canvas_h = screen_h // args.scale
    else:
        # Auto: find scale that gives a retro feel
        scale = min(screen_w // 80, screen_h // 80)
        scale = max(4, min(scale, 12))
        canvas_w = screen_w // scale
        canvas_h = screen_h // scale

    pixel_scale = min(screen_w // canvas_w, screen_h // canvas_h)
    renderer = Pico8Renderer(width=canvas_w, height=canvas_h)

    # ── Arcade setup ──
    mgr = ArcadeManager(switch_interval=600)
    mgr.register("breakout", BreakoutScene())
    mgr.register("pong", PongScene())

    # ── Demo state cycling ──
    frame = 0
    clock = pygame.time.Clock()
    fps = 12  # match the rhythmic feel

    def demo_state(f: int) -> SystemSnapshot:
        cycle = f % 400
        if cycle < 80:
            return SystemSnapshot(container_up=True, active_task_count=0)
        elif cycle < 200:
            tasks = min(4, 1 + (cycle - 80) // 30)
            depts = ["engineering", "quality", "operations", "security"][:tasks]
            return SystemSnapshot(container_up=True, active_task_count=tasks,
                                  dept_active=depts, collecting=(cycle % 15 < 5))
        elif cycle < 260:
            return SystemSnapshot(container_up=True, active_task_count=2,
                                  dept_active=["engineering", "quality"], has_alert=True)
        elif cycle < 340:
            return SystemSnapshot(container_up=True, active_task_count=1,
                                  dept_active=["quality"])
        else:
            return SystemSnapshot(container_up=False)

    # ── Main loop ──
    running = True
    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_q, pygame.K_ESCAPE):
                    running = False
                elif event.key == pygame.K_SPACE:
                    mgr.random_game()

        frame += 1
        snap = demo_state(frame)
        mgr.update(snap, canvas_w, canvas_h)
        mgr.draw(renderer, snap)

        # ── Render framebuffer to pygame surface ──
        # Convert indexed buffer to RGB
        surf = pygame.Surface((canvas_w, canvas_h))
        pixels = pygame.surfarray.pixels3d(surf)
        # renderer.screen is (H, W), pixels is (W, H, 3)
        for idx in range(32):
            r, g, b = ALL_COLORS[idx] if idx < len(ALL_COLORS) else (0, 0, 0)
            mask = renderer.screen == idx
            # mask is (H, W), pixels is (W, H, 3) — need transpose
            mask_t = mask.T  # (W, H)
            pixels[mask_t] = [r, g, b]
        del pixels  # unlock surface

        # Scale up to screen
        scaled = pygame.transform.scale(surf, (canvas_w * pixel_scale, canvas_h * pixel_scale))
        # Center on screen
        x_off = (screen_w - canvas_w * pixel_scale) // 2
        y_off = (screen_h - canvas_h * pixel_scale) // 2
        screen.fill((0, 0, 0))
        screen.blit(scaled, (x_off, y_off))
        pygame.display.flip()

        clock.tick(fps)

    pygame.quit()


if __name__ == "__main__":
    main()
