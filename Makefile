PYTHON ?= python
STATE ?= .wiki-worker
WIKI ?= wiki-en
REVIEWER ?= reviewer-agent
PORT ?= 8080

.PHONY: run playground stroke-demo stroke-demo-slack stroke-demo-agent-loop test

run:
	$(PYTHON) -m wiki_worker.cli --state $(STATE) --folder $(WIKI) --reviewer $(REVIEWER) web --port $(PORT)

playground:
	$(PYTHON) -m scripts.semantic_conflict_playground --reviewer $(REVIEWER) --port $(PORT)

stroke-demo:
	$(PYTHON) -m scripts.stroke_demo_playground --reviewer $(REVIEWER) --port 8093

stroke-demo-slack:
	set -a; . ./.env; set +a; $(PYTHON) -m scripts.stroke_demo_playground --reviewer $(REVIEWER) --port 8093 --slack-poll 60

stroke-demo-agent-loop:
	set -a; . ./.env; set +a; $(PYTHON) -m scripts.stroke_demo_agent_loop --interval 10

test:
	node tests/test_ui_file.js
	$(PYTHON) -m unittest discover -s tests -v
