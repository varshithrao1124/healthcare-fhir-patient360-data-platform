PYTHON ?= python3
export SPARK_LOCAL_IP ?= 127.0.0.1
export PYSPARK_PYTHON ?= $(PYTHON)
export ACN_TOKEN_SALT ?= local-dev-salt-not-for-production

.PHONY: install lint test coverage pipeline smoke clean

install:
	$(PYTHON) -m pip install -e ".[dev]"

lint:
	$(PYTHON) -m ruff check src tests

test:
	$(PYTHON) -m pytest --cov=acn_interop --cov-report=term-missing --cov-report=xml

coverage: test

pipeline:
	$(PYTHON) -m acn_interop.jobs.run_local --profile demo --lake data/lake --evidence evidence

smoke:
	$(PYTHON) -m acn_interop.jobs.run_local --profile smoke --lake data/smoke-lake --evidence data/smoke-evidence

clean:
	rm -rf data .pytest_cache .ruff_cache htmlcov coverage.xml .coverage
	find src tests -type d -name __pycache__ -exec rm -rf {} +
