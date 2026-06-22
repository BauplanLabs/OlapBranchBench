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

    # Username resolution is not part of what we measure
    user = bauplan.Client(api_key=os.getenv("BAUPLAN_API_KEY")).info().user
    if user is None:
        raise RuntimeError("could not resolve the authenticated bauplan user")
    username = user.username

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

    return run_branch_experiment(
        backend="bauplan",
        config=config,
        client_factory=lambda: bauplan.Client(api_key=os.getenv("BAUPLAN_API_KEY")),
        build_branch_name=build_branch_name,
        create_branch=create_branch,
        delete_branch=delete_branch,
        results_path=results_path,
    )
