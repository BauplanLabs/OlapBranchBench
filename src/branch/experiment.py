import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from src.common.results import append_results
from src.common.runner import RunConfig, run_repeated


@dataclass(frozen=True)
class BranchConfig(RunConfig):
    n_branches: int = 10
    base_branch: str = "main"
    chained: bool = False
    verify_clone: bool = False
    namespace: str = "tpch_1"


def _timed_row[R](operation: str, branch_name: str, op: Callable[..., R], *args: object) -> tuple[dict[str, object], R]:
    """Run a branch op, returning its result row (with wall-clock start and end) and the op's value."""
    started_at = datetime.now(tz=UTC)
    perf_start = time.perf_counter()
    result = op(*args)
    duration_s = time.perf_counter() - perf_start
    ended_at = datetime.now(tz=UTC)
    row: dict[str, object] = {
        "branch_name": branch_name,
        "operation": operation,
        "duration_s": duration_s,
        "started_at": started_at,
        "ended_at": ended_at,
    }
    return row, result


def run_branch_experiment[ClientT](
    backend: str,
    config: BranchConfig,
    client_factory: Callable[[], ClientT],
    build_branch_name: Callable[[str, str], str],
    create_branch: Callable[[ClientT, str, str], str],
    delete_branch: Callable[[ClientT, str], None],
    results_path: str | Path = "results/branching.parquet",
    close_client: Callable[[ClientT], None] | None = None,
    verify_branch: Callable[[ClientT, str, str], None] | None = None,
) -> pl.DataFrame:
    """Backend-agnostic branch benchmark, timing create and delete as separate operations."""

    exp_id = str(uuid.uuid4())

    def work(client: ClientT) -> list[dict[str, object]]:
        """Time create from the fixed base then delete, for one independent branch."""
        # Name building stays out of both measured regions
        branch_name = build_branch_name(exp_id, str(uuid.uuid4()))
        create_row, _ = _timed_row("create_branch", branch_name, create_branch, client, branch_name, config.base_branch)
        # Verification runs between create and delete, outside both measured regions
        if verify_branch is not None:
            verify_branch(client, branch_name, config.base_branch)
        delete_row, _ = _timed_row("delete_branch", branch_name, delete_branch, client, branch_name)
        return [create_row, delete_row]

    def run_chained(client: ClientT) -> list[dict[str, object]]:
        """Create a chain of branches, each from the previous, then delete them in reverse order."""
        rows: list[dict[str, object]] = []
        names: list[str] = []
        parent = config.base_branch
        for _ in range(config.n_branches):
            branch_name = build_branch_name(exp_id, str(uuid.uuid4()))
            # Capture the source before parent is reassigned to the new branch
            source = parent
            row, parent = _timed_row("create_branch", branch_name, create_branch, client, branch_name, parent)
            if verify_branch is not None:
                verify_branch(client, branch_name, source)
            rows.append(row)
            names.append(branch_name)
        # Delete children before parents so chained shallow clones are not orphaned
        for branch_name in reversed(names):
            row, _ = _timed_row("delete_branch", branch_name, delete_branch, client, branch_name)
            rows.append(row)
        return rows

    if config.chained:
        # Chaining needs each branch to outlive the next one's creation, so it runs serially
        client = client_factory()
        try:
            rows = run_chained(client)
        finally:
            if close_client is not None:
                close_client(client)
    else:
        rows = run_repeated(config.n_branches, config, client_factory, work, close_client)

    config_struct = asdict(config)

    # Config details kept in the "config" struct, timestamps stay top-level for easy querying
    df = pl.DataFrame([{"backend": backend, "exp_id": exp_id, **row, "config": config_struct} for row in rows])

    return append_results(df, results_path)
