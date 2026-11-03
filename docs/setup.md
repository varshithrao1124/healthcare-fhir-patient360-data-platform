# Local setup

Alderbrook Interop runs on Python 3.10+ and a Java 17 or 21 runtime. This repository was executed with Python 3.12.3, OpenJDK 21, PySpark 3.5.6, and delta-spark 3.3.2.

## Install

```bash
python -m pip install -e ".[dev]"
export SPARK_LOCAL_IP=127.0.0.1
export PYSPARK_PYTHON=python
export ACN_TOKEN_SALT=local-dev-salt-not-for-production
```

The salt is required in production and has a local default in `configs/local.yml` so a fresh clone still runs. Copy `.env.example` if you want the variable list in one place. Do not commit a real `.env`.

The first Spark session downloads `delta-spark_2.12` from Maven into the Ivy cache. Later runs reuse it.

## Commands

| Command | What it does |
| --- | --- |
| `make lint` | Ruff on `src` and `tests` |
| `make test` | Unit, quality, and the Spark integration test, with coverage |
| `make smoke` | Scripted population only, output under `data/smoke-lake` |
| `make pipeline` | Demo population, `data/lake`, and `evidence/` |
| `make clean` | Deletes `data/` and test caches. Does not delete `evidence/` |

A direct invocation:

```bash
python -m acn_interop.jobs.run_local --profile demo --lake data/lake --evidence evidence
```

`--write-samples` rewrites `samples/` from the same renderers the feed uses.

## What the integration test covers

`tests/integration/test_pipeline.py` runs the smoke profile in a temporary lake and checks the clinical story: Elena's survivorship, Robert and Sofia each collapse to one enterprise id, the Millers do not, Helen sits on the review queue at 0.78, the two readmissions and the transfer, the persistent potassium, the unmapped lab, the de-identified token, and a second streaming trigger that does not insert rows.

## Configuration

`configs/local.yml` sets the as-of date, the two-hour lateness window, and the match thresholds. `configs/azure.yml.example` points the same job at `abfss` paths and the Kafka transport. Azure values are environment variable names, not secrets.
