# Reproduction protocol

Exact definitions behind every stage of `make reproduce`: initialization
arithmetic, the recurrence and extractors, the consumer interface, the quality
experiment, the Uniform control, measurement scopes and the formal bound.

## Configuration and exact initial states

`seeds/quality_config.json` holds the four quality-test key/nonce pairs. They
were generated with NumPy 1.21.5, one `Generator(PCG64(20271013))`, and four
successive pairs of `rng.bytes(32)` and `rng.bytes(12)`. The literal bytes are
included so initialization can be reconstructed without depending on that RNG
API. `make seeds-check` also checks that recipe.

Each configuration consists of eleven little-endian uint32 words, the eight
key words followed by the three nonce words. Let X32 apply XOR shifts left 13,
right 17, left 5 and X64 apply left 13, right 7, left 17, truncating after every
operation to unsigned 32 or unsigned 64. Let G32=0x9e3779b9 and
G64=0x9e3779b97f4a7c15. Starting with a=b=0, absorb each word w as

```
a = X32(a XOR w)
b = X64((b + (w << 32) + (w XOR G32)) mod 2^64)
```

Define P(z)=2^30+(z mod 2^30). The plane starts every source with
`x0=P(X32(X32(a XOR G32)))` and `s0=X64(b)`, replacing zero s0 by G64.
The four exact accumulators and plane states are included in
`seeds/postmix_cases.csv`. Row y has variant 2y and column x has variant 2x+1.
Their common initialization does not by itself imply different emitted bytes.

For zero-based tile coordinates use t=y*N+x+1. Salt products wrap to their
constant widths. Compute raw q=X64(b XOR (t*G64 mod 2^64)). Local XS starts at q,
replacing zero by G64. Local LG starts at
`P(X32(X32(a XOR (t*G32 mod2^32))))` with perturbation state equal to the XS
state. Local TM starts at raw q mod 2^32, replacing zero by 1. TM's replacement
uses the raw q, independently of the XS fallback. The executable helper
`reproduce_seeds.py` and the included CSV records resolve all tile states.

Plane byte 0 uses source update 65 after 64 discarded updates. Local LG also
uses its first output after 65 updates. XS returns the current low byte before
its first update. TM returns current state bits 30, 26, 22, 18, 14, 10, 6 and 2 before its
first update, with bit 2 becoming output bit 0. The software-only XS spaced
adapter selects bits 56, 48, 40, 32, 24, 16, 8 and 0 with bit 0 becoming output bit 0. Trivium
and ChaCha20 initialization remain defined by their included cores and
reference programs, driven by the same application configuration words.

## Fixed-point recurrence and extraction

The stored and broadcast state is unsigned 32-bit Q0.32. For variant v,
expression e=v mod 6 and guard count g=floor(v/6). The following is the source
arithmetic, not a claim of minimum necessary container widths.

```
xx = zero_extend_42(state) << g
one = 1 << (32 + g)
rr = ((1 << 34) - (1 << (32 - 6))) << g
rmul(t) = (t << 2) - (t >> 6)
```

Working variables and `rmul` arguments/return values are unsigned 42-bit;
product containers are unsigned 84-bit. A product is shifted right by 32+g
before reuse. Assignment, argument and return conversions retain the low
bits of the destination width, with no saturation. The final right shift by g
removes guards before retaining the low 32-bit returned state. Verilog width
semantics in `lbe_dist.v:form_v` are authoritative for expression evaluation.
The six expressions implement the stated logistic map with their respective
rounded operation ordering. Source variants differ by coordinate, expression
and guard precision. The coefficient multiplication uses shifts and subtraction
for the evaluated LEAN=6 setting.

For every asserted advance the perturbation state applies X64. The low 8 bits
of its new value are XORed into the new source state. The emitted byte then
uses the row/column pair at the same accepted iteration. With D=abs(R-C) and
`n=D << (32-bit_length(D))` for D>0, otherwise n=0, the extractors are

| Extractor | Output |
|---|---|
| A and A* | `((n>>15) XOR (n>>23)) AND255` |
| B | `(D>>8) AND255` |
| C | `((R XOR C)>>8) AND255` |
| D | `(n>>15) AND255` |

A* uses combinational conditional shifts for normalization and adds no clock
stage. Its output function is the same as A. Both HDL forms
(`normalizer_original`, `normalizer_staged`) and the independent byte reference
are included.

## Initialization, advance and consumer interface

Configuration writes address 0..10. Writing address 15 starts a pass. The tile
absorbs the eleven words, initializes states and arms. The mesh registers the
all-armed reduction and the global readiness reduction. Sources update on an
asserted global advance. There are direct row/column broadcast wires, no
per-hop recurrence pipelines.

The evaluated receiver configuration has PLANE_REG=1, FIFO depth 32,
MARGIN=2 and registered global advance. Receiver registers sample every edge.
The FIFO read is accepted exactly when take AND hit, where hit means nonempty.
A receiver is ready when it is not running, when its byte quota has already
been scheduled, or when occupancy is less than depth−2. The scheduled-push
counter and actual-write counter are distinct. A tile that has scheduled its
quota stops producing and does not block the other receivers.

During continuous qualified emission, a source update at edge e reaches the
receiver at e+1 and the FIFO at e+2. The pending write can occur even if current
advance has fallen. A stall can delay qualification, so this is not an
unconditional two-cycle latency guarantee. Once occupancy reaches depth−2,
one remaining registered-advance step and the pending push can cause two
further writes. The two reserved entries accommodate those pending writes in
the evaluated path. Existing RTL tests exercise initialization, restart,
stalls, output order and completion; this argument is not a new general FIFO
formal proof.

## Matched dependence experiment

N=6. Each of four configurations provides 125000 bytes per tile. The first 62500
fit each predictor and the last 62500 evaluate it. Generate all streams in the
specified order and preserve the chronological split. The 225 rectangles per
configuration are all row-pair/column-pair combinations, including overlapping
rectangles. They are not 225 independent experimental replicates.

For rectangle corners a,b,c,d in top-left, top-right, bottom-left, bottom-right
order, fit one of 41 spatial rules. Rule 0 is d=a XOR b XOR c. The other 40 rules
are d=(s1*a+s2*b+s3*c+c0) mod 256 with each sign in{-1,+1} and
c0 in{-2,-1,0,1,2}. Enumeration is sign loops in that order, followed by the
offset loop. The first maximizer wins fitting ties. Only the chosen rule is
scored on the held-out half. `predict.cpp` is the exact executable definition.

Temporal predictors at lags 1 and 4 fit a 256×256 transition-count table. For
each predecessor byte the prediction is its most frequent successor, breaking
ties toward the lowest byte. Training and test pairs stay entirely within
their own halves. Therefore each test stream has 62500−lag pairs, not 62500.
Prediction scores are percentages. Mean spatial prediction first averages
225 rectangle scores within each configuration and then the four configuration
means. Temporal means use the 36 tile streams in each configuration. Any
reported standard error is sample SD across four configuration/block means,
divided by sqrt(4); it is a descriptive spread summary. It does not treat
rectangles or tiles as independent replications.

Request masks take bit 7 from each rectangle-corner byte. Top-left is mask bit 3,
top-right bit 2, bottom-left bit 1 and bottom-right bit 0. Counts use only the
held-out half. Support is the minimum number of distinct masks across 900
configuration/rectangle cases. TV16 is one half of the sum over 16 masks of the
absolute difference between empirical frequency and 1/16. It is dimensionless.
A standalone arbiter stimulus experiment is distinct from the integrated mesh
application experiment.

## Exact Uniform control

The Uniform control uses NumPy 1.21.5 PCG64 through one
`numpy.random.default_rng(20271014)`. Call

```python
rng.integers(0, 256, (6, 6, 125000), dtype=numpy.uint8)
```

exactly four times in case order 0, 1, 2 and 3, with no reseeding and no other draws
from this generator. Arrays are C-order B[y,x,time], time varying fastest.
The exact dtype, full-shape calls and draw order matter. Uniform blocks are
successive control blocks, not keyed configurations, and Uniform has no
routed hardware row. `seeds/uniform_protocol.json` is a machine-readable copy.
The seed-generation helper does not generate these arrays.

## Hardware measurement and application boundaries

The common implementation flow uses Vivado 2025.2 and
xczu7ev-ffvc1156-2-e. It performs out-of-context synthesis, then introduces the
clock for subsequent implementation. The isolated extractor target is 300 MHz.
Subsystem and complete mesh targets are 70 MHz. WNS is reported at the stated
clock, not converted into a measured maximum frequency. External AXI input
and output delay constraints are absent. Internal paths and externally
unconstrained interfaces must be reported separately. The timing audit
inspects recurrence, distribution, readiness, initialization and advance
paths in the routed checkpoints.

Isolated-extractor resources, subsystem resources and complete-mesh increments
are different comparison scopes. Whole-mesh increments subtract the matching
base configuration at the same N. The integrated Private A* comparator keeps
initialization, extraction, FIFO and collective advance equivalent to Shared
A* while enabling the two coordinate-specific sources at every tile. Its
routing gate requires matched N=3 accepted-byte/application checks and a
source manifest. Inspect mapped source liveness and hierarchy after routing.
The separate unequal-demand Private A experiment uses independent advances;
it is not the collective-advance integrated Private A* comparator.

The application image is 120×120. XOR write-back timing includes startup as
specified by the bench, and the fused Sobel workload is measured separately.
Rebuild the documented firmware and input image before comparing exact cycle
counts. Full application images, accepted-byte traces and reported completion
values are outputs, not bundled inputs.

The delivery RTL bench uses 1600 bytes per tile. It includes unrestricted
demand, one consumer requesting every fourth cycle and coordinated stalls.
Its completion values are zero-based rising-edge indices beginning after
configuration words and the start write have been sampled. Internal mixing,
collective initialization, the discarded prefix and FIFO startup remain inside
the interval. The last accepted byte records finish=cycle. A count of
observations 0..finish inclusive would be finish+1. Steady delivery rate counts
accepted bytes at tile 1 over cycle indices 256..1279 inclusive, 1024 observations.

## Bounded formal check

The A/A* check runs Yosys with
`sat -seq 3 -set-init-zero -prove trigger 0 -verify -timeout 60` on the two
EXT=0 registered extractor wrappers. The first modeled state contains zero
registers. The second holds an arbitrary captured 32-bit input pair, while the
output is F(0,0). The third compares the A and A* output bytes for that arbitrary
pair. The normalizer adds no registers. This bound establishes the compared
extractor behavior at those unrolled states. It is not a whole-mesh induction
proof. The command, miter construction and source wrappers are included.

