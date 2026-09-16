PYTHON ?= python
STATE ?= .wiki-worker
WIKI ?= wiki-en
REVIEWER ?= reviewer-agent
PORT ?= 8080

.PHONY: run playground test

run:
	$(PYTHON) -m wiki_worker.cli --state $(STATE) --folder $(WIKI) --reviewer $(REVIEWER) web --port $(PORT)

playground:
	$(PYTHON) -m scripts.semantic_conflict_playground --reviewer $(REVIEWER) --port $(PORT)

test:
	node tests/test_ui_file.js
	$(PYTHON) -m unittest discover -s tests -v
