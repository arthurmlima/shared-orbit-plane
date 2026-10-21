// Verilator testbench acting as the Processing System (PS) of the heterogeneous MPSoC.
//  1. programs every Tile with the same Tile-code (broadcast over the programming interface)
//  2. sends the input image to the central Tile, which distributes it over the NoC
//  3. releases the RISC-V cores and measures cycles until every Tile reports done
//  4. reads every step of every pixel back through the central Tile
#include "Vmpriscv.h"
#include "verilated.h"
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <vector>
#include <map>
#include <string>
#include <fstream>

static Vmpriscv *top;

// 32-bit word i of a Verilator signal, whatever its width (scalar, 64-bit or wide)
static uint32_t word32(uint8_t v, int i)  { return i ? 0 : v; }
static uint32_t word32(uint16_t v, int i) { return i ? 0 : v; }
static uint32_t word32(uint32_t v, int i) { return i ? 0 : v; }
static uint32_t word32(uint64_t v, int i) { return i > 1 ? 0 : (uint32_t)(v >> (32 * i)); }
template <std::size_t W> static uint32_t word32(const VlWide<W> &v, int i) { return v[i]; }
#define BIT_OF(sig, t) ((word32((sig), (t) / 32) >> ((t) % 32)) & 1u)
static uint64_t cyc = 0;

static void tick() {
    top->clk = 0; top->eval();
    top->clk = 1; top->eval();
    cyc++;
}

// message packing (must match mpriscv_defs.vh)
static uint64_t msg(uint16_t data, int tx, int ty, int ox, int oy, int s, int f, int type, int osink) {
    uint64_t m = 0;
    m |= (uint64_t)data;
    m |= (uint64_t)(tx & 0xff) << 16;
    m |= (uint64_t)(ty & 0xff) << 24;
    m |= (uint64_t)(ox & 0xff) << 32;
    m |= (uint64_t)(oy & 0xff) << 40;
    m |= (uint64_t)(s & 0xf) << 48;
    m |= (uint64_t)(f & 0xf) << 52;
    m |= (uint64_t)(type & 3) << 56;
    m |= (uint64_t)(osink & 1) << 58;
    return m;
}

int main(int argc, char **argv) {
    Verilated::commandArgs(argc, argv);
    if (argc < 6) {
        fprintf(stderr, "usage: %s N W H prog.hex image.txt out_prefix\n", argv[0]);
        return 1;
    }
    int N = atoi(argv[1]), W = atoi(argv[2]), H = atoi(argv[3]);
    const char *hexf = argv[4], *imgf = argv[5];
    std::string out = argc > 6 ? argv[6] : "out";
    int C = (N - 1) / 2;   // central Tile; origin from the balanced partition rule
    int NT = N * N, NSTEP = 8;

    top = new Vmpriscv;
    top->rst = 1; top->cpu_resetn = 0; top->prog_we = 0; top->ext_in_valid = 0;
    for (int i = 0; i < 5; i++) tick();
    top->rst = 0; tick();

    // ---- 1. programming ----
    std::vector<uint32_t> prog;
    { std::ifstream f(hexf); std::string l; while (f >> l) prog.push_back(strtoul(l.c_str(), 0, 16)); }
    uint64_t t_prog0 = cyc;
    for (size_t i = 0; i < prog.size(); i++) {
        top->prog_we = 1; top->prog_addr = i * 4; top->prog_data = prog[i]; tick();
    }
    top->prog_we = 0; tick();
    uint64_t t_prog = cyc - t_prog0;
    if (getenv("TB_VERBOSE")) fprintf(stderr, "programmed\n");

    // ---- 2. image transfer PS -> central Tile -> NoC ----
    std::vector<int> img(W * H);
    { std::ifstream f(imgf); for (auto &p : img) f >> p; }
    uint64_t t_in0 = cyc;
    for (int y = 0; y < H; y++)
        for (int x = 0; x < W; x++) {
            top->ext_in_data = msg(img[y * W + x], x, y, 0, 0, 0, 0, 0 /*WR*/, 0);
            top->ext_in_valid = 1;
            top->eval();
            while (top->ext_in_full) { tick(); top->eval(); }
            tick();
        }
    top->ext_in_valid = 0;
    tick();
    while (top->noc_busy) tick();
    for (int i = 0; i < 4; i++) tick();
    uint64_t t_in = cyc - t_in0;
    if (getenv("TB_VERBOSE")) fprintf(stderr, "image loaded\n");

    // ---- 3. run ----
    std::map<int, std::vector<uint64_t>> marks;   // mark id -> per-tile cycle
    top->cpu_resetn = 1;
    uint64_t t0 = cyc;
    const uint64_t LIMIT = 2000000000ULL;
    while (!top->all_done && cyc - t0 < LIMIT) {
        tick();
        for (int t = 0; t < NT; t++) {
            if (BIT_OF(top->mark_valid, t)) {
                uint32_t id = word32(top->mark_data, t);   // N*N*32-bit signal
                auto &v = marks[id];
                if (v.empty()) v.assign(NT, 0);
                v[t] = cyc - t0;
                if (getenv("TB_VERBOSE")) fprintf(stderr, "mark %u tile %d at %llu\n", id, t, (unsigned long long)(cyc - t0));
            }
        }
    }
    uint64_t t_run = cyc - t0;
    if (getenv("TB_VERBOSE")) fprintf(stderr, "run done %d\n", (int)top->all_done);
    if (!top->all_done) { fprintf(stderr, "TIMEOUT\n"); return 2; }
    top->cpu_resetn = 0;
    tick();

    // ---- 4. read back all steps through the central Tile ----
    std::vector<int> res(NSTEP * W * H, 0x7fffffff);
    uint64_t t_out0 = cyc;
    size_t expected = (size_t)NSTEP * W * H, got = 0;
    // central Tile origin, same rule as rtl/mpriscv.v (PART_ALIGN from the environment, default 1)
    int A = getenv("PART_ALIGN") ? atoi(getenv("PART_ALIGN")) : 1;
    auto org = [&](int i, int len) { int nb = (len + A - 1) / A, o = A * (i * nb / N); return o > len ? len : o; };
    int ox = org(C, W), oy = org(C, H);
    auto poll = [&]() {
        if (top->ext_out_valid) {
            uint64_t m = top->ext_out_data;
            int16_t d = (int16_t)(m & 0xffff);
            int px = (m >> 32) & 0xff, py = (m >> 40) & 0xff, s = (m >> 48) & 0xf;
            res[(s * H + py) * W + px] = d;
            got++;
        }
    };
    for (int s = 0; s < NSTEP; s++)
        for (int y = 0; y < H; y++)
            for (int x = 0; x < W; x++) {
                top->ext_in_data = msg(0, x, y, ox, oy, s, 0, 1 /*REQ*/, 1 /*to PS*/);
                top->ext_in_valid = 1;
                top->eval();
                while (top->ext_in_full) { poll(); tick(); top->eval(); }
                poll();
                tick();
            }
    top->ext_in_valid = 0;
    top->eval();
    uint64_t guard = 0;
    while (got < expected && guard++ < 1000000) { poll(); tick(); top->eval(); }
    uint64_t t_out = cyc - t_out0;

    // ---- report ----
    FILE *fo = fopen((out + "_steps.txt").c_str(), "w");
    for (int s = 0; s < NSTEP; s++)
        for (int i = 0; i < W * H; i++) fprintf(fo, "%d%c", res[s * W * H + i], (i == W * H - 1) ? '\n' : ' ');
    fclose(fo);

    FILE *fj = fopen((out + "_timing.json").c_str(), "w");
    fprintf(fj, "{\"N\":%d,\"W\":%d,\"H\":%d,\"prog_words\":%zu,\"t_prog\":%llu,\"t_in\":%llu,"
                "\"t_run\":%llu,\"t_out\":%llu,\"readback_ok\":%s,\"marks\":{",
            N, W, H, prog.size(), (unsigned long long)t_prog, (unsigned long long)t_in,
            (unsigned long long)t_run, (unsigned long long)t_out, got == expected ? "true" : "false");
    bool first = true;
    for (auto &kv : marks) {
        fprintf(fj, "%s\"%d\":[", first ? "" : ",", kv.first);
        for (int t = 0; t < NT; t++) fprintf(fj, "%s%llu", t ? "," : "", (unsigned long long)kv.second[t]);
        fprintf(fj, "]");
        first = false;
    }
    fprintf(fj, "}}\n");
    fclose(fj);
    printf("N=%d %dx%d run=%llu cycles (%.2f cycles/pixel), in=%llu out=%llu readback=%zu/%zu\n",
           N, W, H, (unsigned long long)t_run, (double)t_run / (W * H),
           (unsigned long long)t_in, (unsigned long long)t_out, got, expected);
    delete top;
    return 0;
}
