# ORB27: shared orbit-plane byte generation for many-core meshes

HDL, firmware, reference models, test benches, analysis programs and the Vivado
flow for the shared orbit-plane generator, together with the exact experiment
seeds. Generated streams, traces, checkpoints, reports and firmware images are
not stored; every one of them is rebuilt from source.

## Quick start

Use Python 3.10 or newer and a Linux shell.

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install -r requirements.txt
make seeds-check
make check
make build
```

- `make seeds-check` verifies the seed records and the NumPy key recipe.
- `make check` parses sources, creates the job recipes and test inputs, and lists the tools it finds.
- `make build` compiles the host helpers, the three firmware images and one simulator
  (Shared A, N=3). It runs no workload and no Vivado job.

```sh
make sim-build VARIANT=staged N=3
make reproduce-plan
make reproduce PARALLEL=1
```

`make reproduce` runs the complete workflow from source: unit checks, the
bounded formal check, quality analyses, application checks, the FPGA matrix,
the routed-checkpoint timing audit and the integrated Private A* comparison.
It is expensive. Run `make reproduce-plan` first to see the exact sequence.

`make all PARALLEL=1` builds products only: host helpers, firmware, the
simulator matrix and the configured Vivado jobs.

## Individual stages

| Command | Purpose |
|---|---|
| `make unit formal` | Functional checks and bounded A/A* equivalence |
| `make quality recurrence` | Matched dependence analysis and recurrence diagnostics |
| `make firmware inputs applications` | Firmware, input image and complete-mesh applications |
| `make fpga collect` | Implementation matrix and report extraction |
| `make core` | All of the above in sequence |
| `make audit-plan` | Timing audit and Private A* stages (plan only) |
| `make seeds` | Write the seed records to `build/seed_records` (`SEED_OUT=` to change) |

Run dependent stages one at a time: `quality` must precede `recurrence`.
Stages refuse to overwrite completed output directories, so use a fresh
checkout for a complete rerun.

## Layout

| Path | Contents |
|---|---|
| `src/rtl`, `src/sw`, `src/sim` | Mesh, source generators, firmware and simulation |
| `src/baseline/reference_original`, `src/reference`, `src/tools` | Reference models and checks |
| `src/fpga` | Common Vivado flow |
| `src/quality` | Recurrence and held-out prediction programs |
| `experiments/` | Alternative generators, directed tests, timing audit and evaluation programs |
| `scripts/` | Input generation, build, seed and orchestration |
| `seeds/` | Key/nonce configurations and derived initial states |
| `docs/` | Reproduction protocol and seed inventory |

## Required tools

- Host: Make, GCC/G++, Python, Icarus Verilog (`iverilog`, `vvp`), Yosys and Verilator.
- Firmware: a bare-metal RISC-V GCC and objcopy with RV32IM/ILP32 and the matching
  `libgcc` multilib. GCC 13.4 reproduces the expected firmware images byte for byte.
- FPGA: Vivado 2025.2 with support for `xczu7ev-ffvc1156-2-e`.

Tools are found on `PATH`. You can override them with `CC`, `CXX`, `IVERILOG`, `VVP`,
`YOSYS`, `VERILATOR`, `VIVADO`, `RISCV_CC`, `RISCV_OBJCOPY`, `CROSS_COMPILE`
and `JOBS`. `VIVADO_ROOT` locates the vendor DSP models used by the timing
audit.

`requirements-numerical-tested.txt` and `requirements-image-tested.txt` pin the
exact versions used for the numerical checks and for input-image generation.

## Further reading

- [Reproduction protocol](docs/REPRODUCTION.md): fixed-width arithmetic, configuration
  and FIFO sequencing, predictor definitions, aggregation, measurement scopes,
  Uniform ordering and the formal bound.
- [Seed inventory](docs/SEED_INVENTORY.md): where every seed family lives.

Third-party notices, including PicoRV32's, are kept in their source files.
