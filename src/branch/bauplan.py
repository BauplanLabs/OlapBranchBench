import os
from pathlib import Path

import bauplan
import polars as pl
from dotenv import load_dotenv

from src.branch.experiment import BranchConfig, run_branch_experiment

# Credentials come from .env file
load_dotenv()


def create_branches(
    config: BranchConfig | None = None,
    results_path: str | Path = "results/branching.parquet",
) -> pl.DataFrame:
    """Branch-creation benchmark backed by the Bauplan client."""

    config = config or BranchConfig()
    namespace = config.namespace

    # Username resolution is not part of what we measure
    user = bauplan.Client(api_key=os.getenv("BAUPLAN_API_KEY")).info().user
    if user is None:
        raise RuntimeError("could not resolve the authenticated bauplan user")
    username = user.username

    def client_factory() -> bauplan.Client:
        client = bauplan.Client(api_key=os.getenv("BAUPLAN_API_KEY"))
        _warmup = client.info()
        return client

    def build_branch_name(exp_id: str, branch_id: str) -> str:
        """Bauplan branches need to be prefixed with username. Use experiment and branch uuid
        to create unique branch name."""
        return f"{username}.{exp_id}-{branch_id}"

    def create_branch(client: bauplan.Client, branch_name: str, base_branch: str) -> str:
        """Create the branch from the base ref; return its name so it can be chained from."""
        client.create_branch(branch=branch_name, from_ref=base_branch)
        return branch_name

    def delete_branch(client: bauplan.Client, branch_name: str) -> None:
        """Delete the branch."""
        client.delete_branch(branch=branch_name)

    def verify_branch(client: bauplan.Client, branch_name: str, base_ref: str) -> None:
        """Assert the new branch carries every table the source ref has in the benchmark namespace."""
        source = {table.name for table in client.get_tables(base_ref, filter_by_namespace=namespace)}
        # The namespace is assumed to exist; an empty source would make the check vacuous, so fail loudly
        if not source:
            raise RuntimeError(f"no tables found in {base_ref}.{namespace}; cannot verify branch {branch_name}")
        branch = {table.name for table in client.get_tables(branch_name, filter_by_namespace=namespace)}
        missing = source - branch
        if missing:
            formatted = ", ".join(sorted(missing))
            raise RuntimeError(
                f"branch {branch_name} is missing {len(missing)} tables from {base_ref}.{namespace}: {formatted}"
            )

    return run_branch_experiment(
        backend="bauplan",
        config=config,
        client_factory=client_factory,
        build_branch_name=build_branch_name,
        create_branch=create_branch,
        delete_branch=delete_branch,
        results_path=results_path,
        verify_branch=verify_branch if config.verify_clone else None,
    )
