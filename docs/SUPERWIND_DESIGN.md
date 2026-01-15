# Superwind Architecture and Polygon Job Design

Date: 2025-11-11

This document explains how the project is structured, how the `superwind` package works, and how the polygon job runs end‑to‑end using a small notebook runner plus YAML pipeline definitions. It focuses on the design (not just the incident) so you can reason about behavior and extend it safely.

## High‑Level Concept

There are **two execution styles** in the current ecosystem:

1) **Notebook runner (repo/workspace style)**
- A notebook is a thin runner that accepts a `yaml_file` parameter and delegates execution to `superwind`.
- This is the style described in most of this document (because it explains the runtime behavior very clearly).

2) **Python wheel task runner (bundle/production style)**
- Jobs can run pipelines as a `python_wheel_task` by calling `superwind.cli.exec_superwind`.
- In this mode, YAML can be stored as **package assets** and referenced with `from_package=...`.
- This is how the deployed `pipeline_equities` job runs today.

Superwind itself is a lightweight dataflow framework:
  - Producers: create a Spark `DataFrame` from some source.
  - Operators: transform the `DataFrame` (select, cast, reshape, etc.).
  - Consumers: write the `DataFrame` somewhere (typically a Delta table via save/merge).
- Pipelines are defined declaratively in YAML (producer → operators → consumer). YAML is parsed into a `PipelineDefinition`, instantiated into a `Pipeline`, and executed in batch or streaming mode.

## Key Files and Paths

- Runner notebook (workspace export to Python): `nb_exec_superwind.py`
  - Path (local export): `nb_exec_superwind.py:1`
  - Path (workspace): `/Users/datsando@outlook.com/superwind/notebooks/exec-superwind`
- YAML (workspace): `/Users/datsando@outlook.com/superwind/pipelines/...`
  - Polygon bronze: `/Users/datsando@outlook.com/superwind/pipelines/polygon/bronze.polygon.snapshot_all_tickers.yaml`
  - Polygon silver: `/Users/datsando@outlook.com/superwind/pipelines/polygon/silver.polygon.snapshot_all_tickers.yaml`
- Superwind package (local repo): `superwind/src/superwind/...`
  - YAML loader: `superwind/src/superwind/definition/yaml.py`
  - Definitions & pipeline: `superwind/src/superwind/definition/__init__.py`
  - Producers: `superwind/src/superwind/producers/`
  - Operators: `superwind/src/superwind/operators/`
  - Consumers: `superwind/src/superwind/consumers/`
  - Registry & secrets setup: `superwind/src/superwind/__init__.py`

## How the Runner Notebook Works

- The runner is intentionally minimal (from the exported source):
  1) Read notebook parameter `yaml_file` from `dbutils.notebook.entry_point.getCurrentBindings()`
  2) `YAMLPipelineDefinition().load(yaml_file)` to parse YAML into a `PipelineDefinition`
  3) `pdef.run()` executes the pipeline (batch or streaming per YAML `config.mode`)

This keeps job tasks simple: all tasks use the same runner notebook and pass a different YAML path.

## YAML Parsing and Pipeline Instantiation

- File: `superwind/src/superwind/definition/yaml.py`
- Features:
  - `$ENV{VAR}`: inject environment variables
  - `$VAR{name:default}`: inject input variables with default
  - `$ASSET_PATH{package, relative_path}`: resolve files packaged with Python distributions
  - `include:` support to merge multiple YAML files before validation
- The parsed YAML becomes a `PipelineDefinition`:
  - `producer` → `ComponentDefinition` (variant + parameters)
  - `operators` → list of component defs
  - `consumer` → component def
- File: `superwind/src/superwind/definition/__init__.py`
  - `PipelineDefinition.get_pipeline()` resolves components using registries and constructs a `Pipeline`
  - `Pipeline.display()` or `Pipeline.run_batch()` / `Pipeline.run_stream()` performs execution

## Registries, Components, and Decorators

- The package uses a registry pattern to map string variants in YAML to concrete Python classes:
  - Producers registry: `superwind/src/superwind/producers/core.py`
  - Operators registry: `superwind/src/superwind/operators/core.py`
  - Consumers registry: `superwind/src/superwind/consumers/core.py`
- Decorators (`@producer`, `@operator`, `@consumer`) register a class by name in a central registry (`superwind/src/superwind/__init__.py` aggregates them).
- Components inherit from `BaseComponent` (pydantic model) so YAML parameters are validated/typed.

## Producers (sources)

- Examples used here:
  - `RESTProducer` (workspace version in `superwind/superwind/producers/finance.py`): issues HTTP GET/POST, reads JSON, optionally extracts from nested keys, and constructs a DataFrame from a provided Spark schema.
  - `ReadTable` (local code in `superwind/src/superwind/producers/catalog.py` and workspace in `superwind/superwind/producers/catalog.py`): reads from an existing Delta table. In streaming mode it uses `readStream` with options like `readChangeFeed`.

## Operators (transforms)

- Located in `superwind/src/superwind/operators/transforms.py`.
- Notable ones used in polygon:
  - `WithColumns`: add or derive columns via expressions (e.g., add `snapshot_date`, convert maps to JSON strings using `to_json(...)`).
  - `CastJSONString`: parse a JSON string column into a typed Spark `StructType` (or via schema file)
  - `Filter`, `Select`, `DropColumns`: standard projection/cleanup
  - `ExecSQL`: execute arbitrary SQL against the DataFrame (see critical notes below)

### ExecSQL Operator — CRITICAL USAGE NOTES

The `ExecSQL` operator allows running SQL queries against the incoming DataFrame.

**Important:** The operator creates a temporary view with a configurable name. The **default view name is `data`**, not `__THIS__`.

```python
# From transforms.py
class ExecSQL(BaseOperator):
    sql_query: Optional[str] = None
    sql_file: Optional[str] = None
    query_name: str = 'data'  # <-- DEFAULT VIEW NAME

    def apply(self, df: DataFrame) -> DataFrame:
        df.createOrReplaceTempView(self.query_name)  # Creates 'data' view
        return df.sparkSession.sql(self.query)
```

**Correct usage:**
```yaml
operators:
  - variant: ExecSQL
    parameters:
      sql_query: |
        select d.*, t.extra_col
        from data d  -- CORRECT: use 'data'
        left join other_table t on d.id = t.id
```

**Common mistake (will fail):**
```yaml
operators:
  - variant: ExecSQL
    parameters:
      sql_query: |
        select * from __THIS__  -- WRONG: __THIS__ does not exist
```

This mistake causes: `[TABLE_OR_VIEW_NOT_FOUND] The table or view '__THIS__' cannot be found.`

The `__THIS__` pattern may be familiar from other frameworks (e.g., dbt, some ETL tools), but superwind uses `data` by default. If you need a custom view name, set `query_name` explicitly.

## Consumers (sinks)

- Located in `superwind/src/superwind/consumers/catalog.py`.
- `SaveAsTable`: write a DataFrame to a Delta table (table or path), optionally partitioned.
- `MergeTable`: upsert semantics using Delta MERGE.
  - Meta augmentation: every write wraps rows with `_id` (uuid) and `_footprint` (timestamps). Columns are lowercased before write to keep names stable.
  - First run: if table doesn’t exist, writes DataFrame and returns.
  - Subsequent runs: builds a merge condition on the configured `key_columns` (e.g., `[ticker, snapshot_date]`) and performs `whenMatched`/`whenNotMatched` actions.

## How the Polygon Bronze Pipeline Works

- YAML: `/Users/datsando@outlook.com/superwind/pipelines/polygon/bronze.polygon.snapshot_all_tickers.yaml`
- Producer: `RESTProducer`
  - URL: `https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers`
  - Extract: `[tickers]`
  - Schema covers: `ticker`, `todaysChangePerc`, `todaysChange`, `updated`, plus map fields (`day`, `lastQuote`, `lastTrade`, `min`, `prevDay`) captured as `map<string,string>` (or JSON strings via later operators).
- Operators:
  - Add `snapshot_date` (e.g., cast current PST to date)
  - Convert nested maps to JSON strings with `to_json(...)`
- Consumer: `MergeTable` into `bronze.polygon.snapshot_all_tickers` with keys `[ticker, snapshot_date]`.
  - On a fresh table the schema is created from the DataFrame and subsequent runs MERGE on the keys.

## How the Polygon Silver Pipeline Works

- YAML: `/Users/datsando@outlook.com/superwind/pipelines/polygon/silver.polygon.snapshot_all_tickers.yaml`
- Producer: `ReadTable` from `bronze.polygon.snapshot_all_tickers` with CDF (streaming, `available_now`)
- Operators:
  - Filter CDF rows to inserts + postimage updates
  - Parse JSON strings (`day`, `lastTrade`, `prevDay`, etc.) into typed structs using `CastJSONString`
  - Handle `lastQuote` with `get_json_object` to be robust to Polygon’s mixed‑case keys (`P/S` and `p/s`)
  - Build a clean typed struct set via `Select`, then drop CDF columns
- Consumer: `MergeTable` into `silver.polygon.snapshot_all_tickers` with keys `[ticker, snapshot_date]`.

## Secrets and Environment Integration

- `superwind/__init__.py` sets a Databricks keyring implementation when running on DBR so `keyring.get_password(scope, key)` transparently reads Databricks Secrets.
- `YAMLPipelineDefinition` supports `$ENV{}` and `$VAR{}` substitution inside YAML, and `$ASSET_PATH{}` for packaged assets.

## Job Definition, Libraries, and Runtime

- The Databricks job is a multi‑task workflow where each task calls `notebooks/exec-superwind` and passes a different YAML path.
- Libraries: even if a given pipeline doesn’t use `feedparser`, the package imports a module that does at import time (e.g., `finance.py`). So the cluster must have `feedparser`, `pydantic`, `ratelimit`, `pyyaml`, `keyring` available or the import will fail. The job definition includes these Pypi libraries.
- Cluster conf includes Delta defaults like `enableChangeDataFeed=true` (useful for silver reading bronze via CDF).

## Failure Modes and Debugging

- Merge key mismatch:
  - If the target table exists but lacks the configured `key_columns`, the MERGE condition referencing `tab.<key>` fails at analysis time (e.g., `[DELTA_MERGE_UNRESOLVED_EXPRESSION] Cannot resolve tab.ticker ...`).
  - Remedies: drop & recreate via pipeline, or `ALTER TABLE ... ADD COLUMNS` to introduce expected fields.
- Permissions:
  - The principal actually running the job (run‑as) must have `USAGE` on catalog/schema and `MODIFY` on target tables. Otherwise MERGE/INSERT/UPDATE fails.
- Library availability:
  - Package import time may require libraries not used by a specific pipeline, so include them in the job baseline.
- Inspecting runs:
  - Use Jobs Runs API to fetch run/task details and get output (error JSON).
  - Use Workspace API to export notebooks and YAML if needed for auditing.

## Typical Execution Flow (Polygon)

1) Job task → `notebooks/exec-superwind` with `yaml_file="../pipelines/polygon/bronze.polygon.snapshot_all_tickers.yaml"`
2) Runner loads YAML → `PipelineDefinition`
3) Producer (REST) fetches payload from Polygon and returns a DataFrame
4) Operators enrich and normalize payload (e.g., `snapshot_date`, `to_json(...)`)
5) Consumer (`MergeTable`) writes/merges into `bronze.polygon.snapshot_all_tickers`
6) Silver task → same runner with `yaml_file="../pipelines/polygon/silver.polygon.snapshot_all_tickers.yaml"`
7) Producer (`ReadTable` with CDF) reads bronze changes
8) Operators cast JSON strings into typed structs and compute derived columns
9) Consumer (`MergeTable`) writes/merges into `silver.polygon.snapshot_all_tickers`

## Where to Extend Safely

- Add a new source: implement a `@producer` class and reference it by name in YAML.
- Add a transform: implement a new `@operator` and chain it in YAML.
- Change sink behavior: adjust `MergeTable` parameters (keys, ignore patterns, delete conditions) in YAML.
- Reuse the same runner across jobs by pointing tasks to different YAML files.

## Quick Reference (Useful Paths)

- Runner notebook (workspace): `/Users/datsando@outlook.com/superwind/notebooks/exec-superwind`
- Polygon YAML (workspace): `/Users/datsando@outlook.com/superwind/pipelines/polygon/...`
- Package source (local): `superwind/src/superwind/...`
- Consumers (merge): `superwind/src/superwind/consumers/catalog.py`
- Operators (transforms): `superwind/src/superwind/operators/transforms.py`
- YAML loader: `superwind/src/superwind/definition/yaml.py`

---

If you need a compact diagram or a code‑level walkthrough for another pipeline, we can add it here.

## DBUtils and Parameter Bindings

- Source of `dbutils` in the runner:
  - In Databricks Runtime, `dbutils` is available implicitly in notebooks. The exported runner recreates it explicitly so the code works as plain source inside Jobs.
  - Code pattern (from the exported source): `dbutils = importlib.import_module('pyspark.dbutils').DBUtils(SparkSession.builder.getOrCreate())`.
- How parameters are read:
  - The job task passes `base_parameters` (e.g., `yaml_file`). The runner accesses them via `dbutils.notebook.entry_point.getCurrentBindings()['yaml_file']`.
  - Alternative (interactive): define a widget and read it with `dbutils.widgets.get('yaml_file')`. A hardened runner can try bindings first, then fallback to widgets, with a helpful error if neither is set.
- Constraint: `pyspark.dbutils` only exists on Databricks (or with Databricks Connect). Running locally without DBR will raise `ModuleNotFoundError`.

## Pipeline Construction (Step‑by‑step)

1) YAML load and merge
   - `YAMLPipelineDefinition.load(...)` reads the YAML, processes `include:` files, and performs substitutions for `$ENV{}`, `$VAR{}`, and `$ASSET_PATH{}`. The result is validated into a `PipelineDefinition` (Pydantic).
2) Resolve concrete components via registries
   - `PipelineDefinition.get_pipeline()` looks up `variant` names in the registries populated by the `@producer`, `@operator`, and `@consumer` decorators, then instantiates each class with the provided `parameters`.
   - Producers may be a single component or a list; multiple producers are supported and will be unioned.
3) Build the in‑memory `Pipeline`
   - Holds: producer(s), ordered operator list, and a single consumer.
4) Apply Spark configuration (optional)
   - `pdef.run()` sets any `config.spark_confs` on the active Spark session before execution.
5) Execute (batch)
   - `Pipeline.get_df(mode=BATCH)` → calls `produce()` (or unions multiple), then applies each operator’s `apply(df)` in order.
   - `consumer.consume(df)` performs the write (e.g., Delta table save or MERGE).
6) Execute (streaming)
   - `Pipeline.run_stream(...)` constructs a streaming DataFrame.
   - If `config.streaming_defer_operators` is true, operators run inside `foreachBatch` and each operator's `on_streaming_defer()` hook can pre‑load schemas (e.g., `CastJSONString`).
   - Trigger can be `ProcessingTime`, `AvailableNow`, or `Continuous`, configured in YAML.
   - **IMPORTANT:** When using `ExecSQL` with `streaming_defer_operators: True`, the SQL query must reference `data` (not `__THIS__`). The temp view is created inside `foreachBatch` with the configured `query_name` (default: `data`).

### Notes and Constraints
- Merge keys must exist on the target
  - `MergeTable` builds a match condition across `key_columns`. If the table pre‑exists without those columns, MERGE analysis fails. Remedies: drop & recreate via pipeline, or `ALTER TABLE ... ADD COLUMNS`.
- Meta and case handling
  - Consumers add `_id` and `_footprint` meta columns and lowercase column names before writing to keep schema stable and case‑insensitive.
- Multiple producers
  - When a list of producers is provided, their outputs are `unionAll`’d; schemas must be compatible or projected accordingly by operators before union.
- Libraries at import time
  - The `superwind` package imports some modules eagerly (e.g., `finance.py` imports `feedparser`), so cluster libraries must include these even if a specific pipeline doesn’t use them.
- Permissions
  - The run‑as principal must have `USAGE` on catalog/schema and `MODIFY` on target tables for writes/merges to succeed.

## RESTProducer: Origin and Instantiation

- Where it’s defined
  - Workspace: `/Users/datsando@outlook.com/superwind/superwind/producers/finance.py` defines `RESTProducer` with fields `url`, `method`, `headers`, `params`, `data`, `spark_schema`, `api_key_secret`, `extract_from`.
  - Local repo (alternate): `superwind/src/superwind/producers/misc.py` also defines a `RESTProducer`, but with different behavior (e.g., returning raw headers/content). The polygon bronze YAML uses the workspace variant because it supports `spark_schema` + `extract_from`.
- How it’s registered
  - Decorator `@producer` (in `superwind/src/superwind/producers/core.py`) adds the class to the producers registry keyed by class name (`"RESTProducer"`).
  - Import side-effect: producers packages’ `__init__.py` import their modules (e.g., `.finance`), executing decorators and populating the registry. The `PipelineDefinition.get_pipeline()` path imports producers/operators/consumers, ensuring registries are filled before lookup.
- How YAML instantiates it
  - YAML fragment (bronze):
    ```yaml
    producer:
      variant: RESTProducer
      parameters:
        url: https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers
        method: GET
        spark_schema: |
          ticker string,
          todaysChangePerc string,
          todaysChange string,
          updated string,
          day map<string, string>,
          lastQuote map<string, string>,
          lastTrade map<string, string>,
          min map<string, string>,
          prevDay map<string, string>
        api_key_secret:
          scope: superwind
          key: polygon.api_key
        extract_from: [tickers]
    ```
  - During `get_pipeline()`: `registry.producers["RESTProducer"](**parameters)` → returns a Pydantic-validated instance.
- What `produce()` does at runtime
  - Builds HTTP headers; if `api_key_secret` provided, resolves the token via `keyring.get_password(scope, key)` (mapped to Databricks Secrets when on DBR via `superwind/__init__.py`).
  - Issues the request with `requests.get`/`requests.post`.
  - Parses JSON and walks keys listed in `extract_from` (e.g., `['tickers']`).
  - Creates a DataFrame using `get_spark_session().createDataFrame(data, spark_schema)` and returns it to the pipeline.

## Diagram Suggestions

High-level superwind execution flow:

```
Databricks Job Task
  → notebooks/exec-superwind (runner)
      → dbutils.notebook.entry_point.getCurrentBindings()['yaml_file']
      → YAMLPipelineDefinition.load(yaml)
          → include + $ENV/$VAR/$ASSET_PATH → PipelineDefinition
          → PipelineDefinition.get_pipeline()
              → resolve Producer(s) via registry
              → resolve Operators via registry
              → resolve Consumer via registry
          → pdef.run()
              → (batch) produce → operators → consume (save/merge)
              → (streaming) readStream → foreachBatch(operators → consume)
```

RESTProducer (polygon bronze) dataflow:

```
Polygon REST API
  → requests (with Authorization from Databricks Secrets via keyring)
  → JSON payload
  → extract_from: ['tickers']
  → Spark createDataFrame(data, spark_schema)
  → Operators
     - WithColumns (snapshot_date, to_json of nested maps)
  → Consumer: MergeTable (keys: ticker, snapshot_date)
  → Delta table: bronze.polygon.snapshot_all_tickers
```


