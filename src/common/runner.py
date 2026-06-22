import random
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Lock, local


@dataclass(frozen=True)
class RunConfig:
    parallel: bool = True
    n_workers: int = 4
    jitter_ms: float = 0.0


def run_repeated[ClientT](
    n: int,
    config: RunConfig,
    client_factory: Callable[[], ClientT],
    work: Callable[[ClientT], list[dict[str, object]]],
    close_client: Callable[[ClientT], None] | None = None,
) -> list[dict[str, object]]:
    """Run work n times, serial or across worker threads, collecting the rows it returns."""

    # One client per worker thread: thread-safety is not guaranteed, and client
    # construction must stay outside whatever work measures
    thread_state = local()
    created: list[ClientT] = []
    created_lock = Lock()

    def get_client() -> ClientT:
        """Return this thread's client, building it on first use and tracking it for cleanup."""
        client = getattr(thread_state, "client", None)
        if client is None:
            client = client_factory()
            thread_state.client = client
            with created_lock:
                created.append(client)
        return client

    def run_one() -> list[dict[str, object]]:
        """Run one unit of work on this thread's client, after optional jitter."""
        client = get_client()
        # Jitter staggers parallel calls and stays outside the measured region
        if config.parallel and config.jitter_ms > 0:
            time.sleep(random.uniform(0, config.jitter_ms) / 1000.0)
        return work(client)

    try:
        if config.parallel and config.n_workers > 1:
            with ThreadPoolExecutor(max_workers=config.n_workers) as executor:
                batches = [f.result() for f in [executor.submit(run_one) for _ in range(n)]]
        else:
            batches = [run_one() for _ in range(n)]
    finally:
        # Close clients explicitly so connectors do not log teardown noise when GC closes them
        if close_client is not None:
            for client in created:
                close_client(client)

    return [row for batch in batches for row in batch]
