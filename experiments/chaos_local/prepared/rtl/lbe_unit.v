`include "mpriscv_defs.vh"
// Multi-pseudo-orbit keystream unit (lower-bound-error generator), same interface and block layout as
// ks_unit2 (S-local placement). Bit-exact reference: scripts/lbe_ref.py.
//
// K mathematically equivalent forms of the logistic map x' = r x (1 - x) run side by side in unsigned
// Q0.32 fixed point with truncating multiplies, all from the same seed x0(block). Their roundings differ,
// so the pseudo-orbits drift apart; after T transient iterations every pair (i, j) yields one byte per
// iteration from D = |x_i - x_j|: the mantissa bits 9..16 below its leading one (the fractional part of
// log2 of the lower bound error) XOR the mantissa bits 1..8, which hides the cycle relations between pairs. K orbits give P = K(K-1)/2 bytes per iteration, so one 64-byte block
// needs T + ceil(64 / P) iterations, one per cycle.
// Pair p keeps its bytes in its own small LUT RAM (2 slots x L entries), so P bytes are written per cycle;
// byte i of a block lives in pair i mod P, entry i div P.
module lbe_unit #(
    parameter XINIT = 0, YINIT = 0, TW = 8, TH = 8, IMG_W = 16,
    parameter GEOM = 1,
    parameter K = 4,              // pseudo-orbits (forms), 2..6
    parameter T = 40,             // transient iterations
    parameter EARLY = 1,          // serve bytes of a block while it is still being generated
    parameter PERT = 0            // keyed perturbation bits shared by all forms (see lbe_dist.v)
) (
    input             clk, rst,
    input             cfg_we,
    input  [3:0]      cfg_addr,
    input  [31:0]     cfg_wdata,
    input  [7:0]      cx, cy,
    input             take,
    output            hit,
    output [7:0]      ks_byte,
    output            busy,
    output reg [31:0] blocks_made
);
    localparam P  = K * (K - 1) / 2;
    localparam L  = (64 + P - 1) / P;
    localparam LA = (L <= 2) ? 1 : $clog2(L);
    localparam BPR = GEOM ? (IMG_W + 7) / 8 : (IMG_W + 63) / 64;
    localparam B0 = GEOM ? XINIT / 8 : XINIT / 64, B1 = GEOM ? (XINIT + TW - 1) / 8 : (XINIT + TW - 1) / 64;
    localparam R0 = GEOM ? YINIT / 8 : YINIT,       R1 = GEOM ? (YINIT + TH - 1) / 8 : YINIT + TH - 1;

    // ---------------- configuration: key words 0..7, nonce 8..10, 15 = start ----------------
    reg [31:0] kw [0:10];                         // key words 0..7, nonce words 8..10
    wire start = cfg_we && cfg_addr == 4'd15;
    always @(posedge clk) if (cfg_we && cfg_addr < 4'd11) kw[cfg_addr] <= cfg_wdata;
    wire [33:0] R = 34'h3E6666666 + {6'd0, kw[2][31:4]};
    // key schedule (scripts/lbe_ref.py): two chains over the 11 words, run once after start: kmix = xorshift32
    // chain (XOR absorption), kmix64 = xorshift64 chain with additive absorption of {w, w ^ GOLD}.
    // mixw(v, c) = xs(xs(kmix ^ (v + 1) * GOLD) ^ c). All K forms of block c start from the same
    // x0 = {01, mixw(0, c)[29:0]} in [0.25, 0.5) (so every pair is an LBE pair); the perturbation state of
    // block c starts from xs64(kmix64 ^ c) (GOLD64 if 0) and steps once per iteration (xorshift64).
    function [31:0] xs; input [31:0] a; reg [31:0] b;
        begin b = a ^ (a << 13); b = b ^ (b >> 17); xs = b ^ (b << 5); end
    endfunction
    function [63:0] xs64; input [63:0] a; reg [63:0] b;
        begin b = a ^ (a << 13); b = b ^ (b >> 7); xs64 = b ^ (b << 17); end
    endfunction
    function [31:0] mixw; input integer v; input [31:0] km; input [31:0] c;
        begin mixw = xs(xs(km ^ (32'h9E3779B9 * (v + 1))) ^ c); end
    endfunction
    function [31:0] seed_v; input integer v; input [31:0] km; input [31:0] c; reg [31:0] a;
        begin a = mixw(v, km, c); seed_v = {2'b01, a[29:0]}; end
    endfunction
    function [63:0] pert_seed; input [63:0] km64; input [31:0] c; reg [63:0] s;
        begin s = xs64(km64 ^ {32'd0, c}); pert_seed = (s == 64'd0) ? 64'h9E3779B97F4A7C15 : s; end
    endfunction
    reg  [63:0] kmix64;
    reg  [63:0] ps;
    wire [63:0] ps_n = xs64(ps);
    wire [31:0] pmask = PERT ? ((32'd1 << PERT) - 1) : 32'd0;
    reg        mixing;
    reg [3:0]  mix_i;
    reg [31:0] kmix;

    // ---------------- block iterator (same order as the PPU's block-major sweep) ----------------
    reg [7:0] it_r, it_b;
    reg       it_done, active;
    wire [31:0] it_ctr = it_r * BPR + it_b;

    // ---------------- request decode ----------------
    wire [7:0]  gx = XINIT + cx, gy = YINIT + cy;
    wire [31:0] req = GEOM ? (gy >> 3) * BPR + (gx >> 3) : gy * BPR + (gx >> 6);
    wire [5:0]  off = GEOM ? {gy[2:0], gx[2:0]} : gx[5:0];
    wire [5:0]  t_req = off / P;
    wire [3:0]  p_req = off % P;

    // ---------------- slots ----------------
    reg  [1:0]  valid;
    reg  [31:0] kc [0:1];
    reg         h, wslot;
    reg         f_act, f_slot;
    reg  [31:0] f_ctr;
    reg  [6:0]  f_cnt;                            // output iterations of the block being generated
    wire hit_h = valid[h] && kc[h] == req;
    wire hit_s = valid[~h] && kc[~h] == req;
    wire fh = EARLY && f_act && f_ctr == req && f_cnt > t_req;
    assign hit = hit_h | hit_s | fh;
    wire rslot = hit_h ? h : hit_s ? ~h : f_slot;
    wire pop = take && !hit_h && (hit_s || (fh && f_slot != h));

    // ---------------- generator: K forms, one iteration per cycle ----------------
    reg         c_start, c_discard, run, c_done;
    reg  [31:0] c_ctr;
    reg  [6:0]  cnt;                              // iterations applied
    reg  [31:0] x [0:K-1];
    wire c_busy = run;

    function [33:0] mul; input [33:0] a; input [33:0] b;
        reg [67:0] pr; begin pr = a * b; mul = pr[65:32]; end
    endfunction
    function [31:0] form; input integer f; input [31:0] xv;
        reg [33:0] xx, one_m, rx;
        begin
            xx = {2'b00, xv}; one_m = 34'h100000000 - xx; rx = mul(R, xx);
            case (f)
                0: form = mul(rx, one_m);
                1: form = rx - mul(rx, xx);
                2: form = mul(R, xx - mul(xx, xx));
                3: form = mul(xx, R - rx);
                4: form = mul(R, mul(xx, one_m));
                default: form = rx - mul(R, mul(xx, xx));
            endcase
        end
    endfunction
    // lower-bound-error byte: bits 9..16 below the leading one of |a - b| XOR bits 1..8 below it
    function [7:0] lbe_byte; input [31:0] a; input [31:0] b;
        reg [31:0] d, n; integer i, lz; reg found;
        begin
            d = (a > b) ? a - b : b - a;
            lz = 0; found = 0;
            for (i = 31; i >= 0; i = i - 1)
                if (!found) begin if (d[i]) found = 1; else lz = lz + 1; end
            n = d << lz;
            lbe_byte = (d == 0) ? 8'd0 : n[22:15] ^ n[30:23];
        end
    endfunction

    wire        w_valid = run && cnt >= T + 1;
    wire [6:0]  w_t = cnt - (T + 1);
    wire        first_w = w_valid && w_t == 0;
    wire        tslot = first_w ? (valid[h] ? ~h : h) : wslot;

    // per-pair byte memories
    wire [8*P-1:0] rbyte;
    genvar gi, gj;
    generate for (gi = 0; gi < K; gi = gi + 1) begin : g_i
        for (gj = gi + 1; gj < K; gj = gj + 1) begin : g_j
            localparam PI = gi * K - gi * (gi + 1) / 2 + (gj - gi - 1);   // pair index in (0,1),(0,2)..order
            reg [7:0] mem [0:2 * (1 << LA) - 1];
            always @(posedge clk)
                if (w_valid && !c_discard) mem[{tslot, w_t[LA-1:0]}] <= lbe_byte(x[gi], x[gj]);
            assign rbyte[8 * PI +: 8] = mem[{rslot, t_req[LA-1:0]}];
        end
    end endgenerate
    assign ks_byte = rbyte[8 * p_req +: 8];

    wire [1:0] occ = valid[0] + valid[1] + (c_busy | c_start | c_done);
    assign busy = c_busy | c_start;

    integer f;
    always @(posedge clk) begin
        c_start <= 0; c_done <= 0;
        if (rst) begin
            run <= 0;
        end else if (c_start) begin
            for (f = 0; f < K; f = f + 1) x[f] <= seed_v(0, kmix, c_ctr);
            ps <= pert_seed(kmix64, c_ctr);
            cnt <= 0; run <= 1;
        end else if (run) begin
            if (cnt == T + L) begin run <= 0; c_done <= 1; end
            else begin
                for (f = 0; f < K; f = f + 1) x[f] <= form(f, x[f]) ^ (ps_n[31:0] & pmask);
                ps <= ps_n;
                cnt <= cnt + 1'b1;
            end
        end
        if (rst) begin
            valid <= 0; h <= 0; active <= 0; it_done <= 1; c_discard <= 0; blocks_made <= 0; f_act <= 0; mixing <= 0;
        end else if (start) begin
            valid <= 0; h <= 0; active <= 1; it_done <= 0; f_act <= 0;
            it_r <= R0; it_b <= B0;
            c_discard <= c_busy | c_start;
            mixing <= 1; mix_i <= 0; kmix <= 0; kmix64 <= 0;
        end else begin
            if (mixing) begin
                kmix <= xs(kmix ^ kw[mix_i]);
                kmix64 <= xs64(kmix64 + {kw[mix_i], kw[mix_i] ^ 32'h9E3779B9});
                mix_i <= mix_i + 1'b1;
                if (mix_i == 4'd10) mixing <= 0;
            end
            if (first_w) wslot <= tslot;
            if (first_w && !c_discard) begin f_act <= 1; f_slot <= tslot; f_ctr <= c_ctr; f_cnt <= 1; end
            else if (w_valid && !c_discard) f_cnt <= f_cnt + 1'b1;
            if (pop) begin valid[h] <= 1'b0; h <= ~h; end
            if (c_done) begin
                f_act <= 0;
                if (c_discard) c_discard <= 0;
                else begin valid[wslot] <= 1'b1; kc[wslot] <= c_ctr; blocks_made <= blocks_made + 1; end
            end
            if (active && !it_done && !mixing && !c_busy && !c_start && !c_done && !c_discard && occ < 2) begin
                c_ctr <= it_ctr; c_start <= 1;
                if (it_b == B1) begin
                    it_b <= B0;
                    if (it_r == R1) it_done <= 1; else it_r <= it_r + 1;
                end else it_b <= it_b + 1;
            end
        end
    end
endmodule
