# OlapBranchBench

Benchmark of data-branching latency across three backends (Bauplan, Databricks, Snowflake) over the same dataset. Each run times the creation and the deletion of a branch (or the per-backend equivalent) and appends the measurements to a single parquet file.

## Table of contents

- [Overview](#overview)
- [Setup](#setup)
- [Dataset](#dataset)
- [Running a benchmark](#running-a-benchmark)
- [Branching across backends](#branching-across-backends)
- [Results](#results)

## Overview

The repository is a small Typer CLI. A backend-agnostic engine runs an operation N times (serial or across worker threads, with optional jitter) and times only the operation itself. Each backend supplies a thin wrapper that knows how to open a client and how to create and delete a branch; everything else (orchestration, timing, output) is shared. A second (optional) command generates the TPC-H dataset with different scale factors, used as the common input.

## Setup

Requires Python 3.13 and [uv](https://docs.astral.sh/uv/). Install the dependencies with:

```
uv sync
```

Credentials are read from a `.env` file (copy `.env.example` and fill in the values for the backends).

Bauplan needs an API key (see [this guide](https://docs.bauplanlabs.com/tutorial/installation) for a tutorial on how to get one):

```
BAUPLAN_API_KEY=
```

Snowflake uses key-pair authentication, which avoids interactive MFA on parallel runs:

```
SF_ACCOUNT=
SF_USER=
SF_ROLE=
SF_WAREHOUSE=
SF_PRIVATE_KEY_FILE=
```

Run this in a Snowflake worksheet to read the first four values directly:

```sql
SELECT
    CURRENT_ORGANIZATION_NAME() || '-' || CURRENT_ACCOUNT_NAME() AS sf_account,
    CURRENT_USER()      AS sf_user,
    CURRENT_ROLE()      AS sf_role,
    CURRENT_WAREHOUSE() AS sf_warehouse;
```

Then generate a key pair and register the public key on your user:

```
openssl genrsa 2048 | openssl pkcs8 -topk8 -inform PEM -out rsa_key.p8 -nocrypt
openssl rsa -in rsa_key.p8 -pubout -out rsa_key.pub
```

Then, in a Snowflake worksheet, run 
```
ALTER USER <your_user> SET RSA_PUBLIC_KEY='<body of rsa_key.pub, without the BEGIN/END lines>
``` 
and point `SF_PRIVATE_KEY_FILE` at `rsa_key.p8`.

Databricks uses a SQL warehouse and a personal access token:

```
DATABRICKS_SERVER_HOSTNAME=
DATABRICKS_HTTP_PATH=
DATABRICKS_TOKEN=
```

The hostname, HTTP path and token come from the SQL warehouse "Connection details" page; you can fetch them from `Compute` > `<YOUR_WAREHOUSE>` > `Connection details`.

## Dataset

All three backends branch the same TPC-H scale-factor-1 dataset, composed of 8 tables in total (`customer`, `lineitem`, `nation`, `orders`, `part`, `partsupp`, `region`, `supplier`). If your warehouses already hold it, there is nothing to do.

Otherwise generate it locally with DuckDB:

```
uv run main.py data tpch --sf 1
```

This writes one parquet per table to `data/tpch_sf1/` (as a check, for SF1, `lineitem` has 6,001,215 rows). Upload those files to object storage and load them into Bauplan, Snowflake and Databricks.

## Running a benchmark

```
uv run main.py bench bauplan <BRANCH>
uv run main.py bench snowflake <DATABASE>
uv run main.py bench databricks <CATALOG>.<SCHEMA>
```

The first argument is the backend and the second is what to branch from: a ref for bauplan, a source database for Snowflake, a source `catalog.schema` for Databricks. The options are `--n-branches`, `--parallel` / `--no-parallel`, `--n-workers`, `--jitter-ms`, `--chained`, `--verify-clone`, `--namespace` and `--results-path`; see `uv run main.py bench --help`. `--chained` makes each branch start from the previous one instead of from the fixed base (sequential only). Each run appends one row per timed operation to the results parquet, recording `duration_s` plus the wall-clock `started_at` and `ended_at` separately for the create and the delete.

`--verify-clone` checks, after each branch is created and before it is deleted, that every source table is present in the new branch, and aborts the run if any is missing. The check runs outside the timed region, so it does not affect the measurements.

## Branching across backends

The three platforms expose different primitives, and the benchmark maps each to a create and a delete operation that are timed separately.

Bauplan has native git-for-data branches, so it calls `create_branch` and `delete_branch` directly on a ref. Notice that, unlike Snowflake and Databricks, Bauplan branches the _entire_ lakehouse, not just this dataset.

Snowflake has no branches; its analog is a zero-copy database clone. Create is `CREATE DATABASE <name> CLONE <source>` and delete is `DROP DATABASE`. A single statement covers the whole database.

Databricks only offers a per-table shallow clone, with no database or schema level clone. A branch is therefore a new schema into which every table of the source schema is shallow-cloned, and delete is `DROP SCHEMA ... CASCADE`. Notice that Databricks does _not_ allow the `--chained` flag.

## Results

Speedup is based on atomic create p95, relative to Bauplan within the same execution mode. Testing was carried out from the same region as each provider: `us-east-1` for Bauplan and Snowflake, `us-west-2` for Databricks.

**Serial**

| Setup | Atomic create avg (s) | Atomic create p95 (s) | Bauplan relative speedup |
|---|---|---|---|
| bauplan | 0.083 | 0.099 | 1.0x |
| snowflake | 8.406 | 9.866 | 99.7x |
| snowflake-iceberg | 10.315 | 11.652 | 117.7x |
| databricks | 24.950 | 26.400 | 266.7x |

**Parallel**

| Setup | Atomic create avg (s) | Atomic create p95 (s) | Bauplan relative speedup |
|---|---|---|---|
| bauplan | 0.195 | 0.827 | 1.0x |
| snowflake | 8.430 | 9.713 | 11.7x |
| snowflake-iceberg | 9.989 | 11.691 | 14.1x |
| databricks | 34.033 | 45.656 | 55.2x |

**Chained**

| Setup | Atomic create avg (s) | Atomic create p95 (s) | Bauplan relative speedup |
|---|---|---|---|
| bauplan | 0.091 | 0.134 | 1.0x |
| snowflake | 10.119 | 12.176 | 90.9x |
| snowflake-iceberg | 10.371 | 13.024 | 97.2x |
| databricks | N/A | N/A | N/A |

Databricks is `N/A` for chained because it does not allow for chained shallow copies.
