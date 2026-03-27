import signal
import threading
import logging
import time

logger = logging.getLogger(__name__)


class GracefulShutdown:
    """Coordinates graceful shutdown across all components.

    Usage:
        shutdown = GracefulShutdown(grace_period=10.0)
        shutdown.register_cleanup(db.close)
        shutdown.register_cleanup(monitor.stop)
        shutdown.install_handlers()

        # In your main loop:
        while not shutdown.is_stopping:
            ...
    """

    def __init__(self, grace_period: float = 10.0):
        self._stop_evt = threading.Event()
        self._grace_period = grace_period
        self._cleanups: list[tuple[str, callable]] = []
        self._shutdown_started = False

    @property
    def is_stopping(self) -> bool:
        return self._stop_evt.is_set()

    @property
    def stop_event(self) -> threading.Event:
        return self._stop_evt

    def register_cleanup(self, fn: callable, name: str = ""):
        """Register a cleanup function to call during shutdown."""
        self._cleanups.append((name or fn.__name__, fn))

    def install_handlers(self):
        """Install SIGINT/SIGTERM handlers."""
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, self._handle_signal)

    def _handle_signal(self, signum, frame):
        sig_name = signal.Signals(signum).name
        if self._shutdown_started:
            logger.warning(f"Force shutdown (second {sig_name})")
            raise SystemExit(1)

        logger.info(
            f"Received {sig_name}, starting graceful shutdown "
            f"(grace={self._grace_period}s)"
        )
        self._shutdown_started = True
        self._stop_evt.set()

    def run_cleanup(self):
        """Run all registered cleanup functions."""
        for name, fn in reversed(self._cleanups):
            try:
                logger.info(f"Cleanup: {name}")
                fn()
            except Exception as e:
                logger.warning(f"Cleanup '{name}' failed: {e}")

        # Check for zombie threads
        zombies = [
            t
            for t in threading.enumerate()
            if t.is_alive()
            and t != threading.current_thread()
            and not t.daemon
        ]
        if zombies:
            logger.warning(
                f"Zombie threads after cleanup: {[t.name for t in zombies]}"
            )
            # Wait grace period for zombies
            deadline = time.time() + self._grace_period
            for t in zombies:
                remaining = deadline - time.time()
                if remaining > 0:
                    t.join(timeout=remaining)

            still_alive = [t for t in zombies if t.is_alive()]
            if still_alive:
                logger.error(
                    f"Threads refused to die: {[t.name for t in still_alive]}"
                )
