PYTHON ?= python3
PARALLEL ?= 1
N ?= 3
VARIANT ?= plane
EXT ?= 0
SEED_OUT ?= build/seed_records
export PYTHONDONTWRITEBYTECODE := 1

.DEFAULT_GOAL := help
.PHONY: help prepare check host firmware inputs sim-build sim-build-matrix build all \
 unit formal quality recurrence applications fpga collect core reproduce reproduce-plan seeds seeds-check

help:
	@echo "make check       Parse sources, generate local job/test inputs and inventory tools"
	@echo "make build       Build host helpers, firmware and one simulator (no workload run)"
	@echo "make all         Build all helpers, firmware, simulator matrix and Vivado jobs"
	@echo "make sim-build   Build VARIANT=plane N=3 EXT=0; override those variables as needed"
	@echo "make sim-build-matrix  Build the complete-mesh application matrix"
	@echo "make unit formal quality recurrence applications fpga collect  Run individual stages"
	@echo "make reproduce-plan  Print the full reproduction sequence without running it"
	@echo "make reproduce   Run every stage, including Vivado, the timing audit and Private A*"
	@echo "make seeds       Recreate the seed records without generating streams"

prepare: seeds-check
	$(PYTHON) scripts/bootstrap_sources.py

check: prepare
	$(PYTHON) reproduce.py check

host:
	$(PYTHON) scripts/build_host.py

firmware:
	$(PYTHON) scripts/build_firmware.py

inputs:
	$(PYTHON) scripts/generate_inputs.py

sim-build:
	$(PYTHON) scripts/build_simulator.py --variant $(VARIANT) --n $(N) --ext $(EXT)

sim-build-matrix:
	$(PYTHON) scripts/build_simulator.py --matrix

build: check host firmware sim-build

all: check host firmware sim-build-matrix fpga

unit formal quality recurrence collect: prepare
	$(PYTHON) reproduce.py $@

applications: prepare
	$(PYTHON) reproduce.py full-system

fpga: prepare
	$(PYTHON) reproduce.py fpga --parallel $(PARALLEL)

# Core stages only, without the timing audit and Private A* comparison.
core: prepare
	$(PYTHON) reproduce.py all --parallel $(PARALLEL)

reproduce: prepare
	$(PYTHON) scripts/reproduce_all.py --through private_astar --parallel $(PARALLEL) --execute

reproduce-plan: prepare
	$(PYTHON) scripts/reproduce_all.py --through private_astar --parallel $(PARALLEL)

# Timing audit and Private A* stages. Plans do not launch workloads.
.PHONY: audit-prepare audit-plan audit-shared-checkpoints audit-timing private-functional private-route private-postroute private-summary
audit-prepare: prepare
	$(PYTHON) experiments/audit/prepare_private_astar.py

audit-plan: audit-prepare
	$(PYTHON) experiments/audit/run_existing_timing_audit.py
	$(PYTHON) experiments/audit/run_private_functional.py
	$(PYTHON) experiments/audit/run_private_route.py

# Rebuild only the three Shared A* mesh checkpoints needed by the audit.
audit-shared-checkpoints: audit-prepare
	$(PYTHON) experiments/chaos_local/normalizer_staged/tools/run_vivado.py experiments/chaos_local/normalizer_staged/fpga/jobs/mesh.json --parallel $(PARALLEL)

# Shared A* checkpoints must first be built with the target above.
audit-timing: audit-prepare
	$(PYTHON) experiments/audit/run_existing_timing_audit.py --execute

# Inputs are rebuilt locally and must match the expected identity hashes.
private-functional: audit-prepare firmware inputs
	$(PYTHON) experiments/audit/run_private_functional.py --execute

# Requires a passing functional record bound to the same RTL hashes.
private-route: audit-prepare
	$(PYTHON) experiments/audit/run_private_route.py --execute

private-postroute: audit-prepare
	$(PYTHON) experiments/audit/run_private_postroute_audit.py --execute

private-summary: audit-prepare
	$(PYTHON) experiments/audit/summarize_private_astar.py

# Deterministic configuration records, independent of stream generation.
seeds:
	$(PYTHON) scripts/reproduce_seeds.py --out-dir "$(SEED_OUT)"

seeds-check:
	$(PYTHON) scripts/reproduce_seeds.py --check --check-numpy
	$(PYTHON) scripts/check_seed_sources.py
