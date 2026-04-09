# AICODE-NOTE: Keep these wrappers aligned with the README commands so the sample
# stays trivial to run from a fresh checkout without inventing parallel workflows.

.PHONY: sync run task reply

sync:
	uv sync

run:
	uv run python main.py

task:
	@if [ -z "$(TASKS)" ]; then echo "usage: make task TASKS='t01 t03'"; exit 1; fi
	uv run python main.py $(TASKS)

reply:
	@if [ -z "$(JSON)" ]; then echo "usage: make reply JSON=path/to/response.json"; exit 1; fi
	uv run python antigravity_reply.py $(JSON)
