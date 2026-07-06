.PHONY: setup test compile clean check-public

PYTHON ?= python3

setup:
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e ".[dev,pdf,excel]"
	test -f config/user.yaml || cp config/default.yaml config/user.yaml
	mkdir -p input data reports

test:
	. .venv/bin/activate && pytest

compile:
	. .venv/bin/activate && python -m compileall src/app tests

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache

check-public:
	sh scripts/check_public_release.sh
