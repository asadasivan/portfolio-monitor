.PHONY: setup sync lock test compile clean check-public

UV ?= uv
UV_EXTRAS ?= --extra pdf --extra excel
UV_CACHE_DIR ?= .uv-cache

setup:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) sync --group dev $(UV_EXTRAS)
	test -f config/user.yaml || cp config/default.yaml config/user.yaml

sync:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) sync --group dev $(UV_EXTRAS)

lock:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) lock

test:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) run --no-sync pytest

compile:
	UV_CACHE_DIR=$(UV_CACHE_DIR) $(UV) run --no-sync python -m compileall src/app tests

clean:
	find . -name "__pycache__" -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache

check-public:
	sh scripts/check_public_release.sh
