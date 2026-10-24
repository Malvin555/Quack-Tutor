.PHONY: install test demo clean
install:
	pip install -e ".[dev]"
test:
	python -m pytest -q
demo:
	bash scripts/make_demo.sh
clean:
	rm -rf .quack .pytest_cache build dist *.egg-info
	find . -name __pycache__ -prune -exec rm -rf {} +
