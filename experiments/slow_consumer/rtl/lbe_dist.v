`include "mpriscv_defs.vh"
// Distributed multi-pseudo-orbit keystream unit (KS_IMPL = 5). Bit-exact reference: scripts/lbe_dist_ref.py.
//
// The mesh runs 2N pseudo-orbits of the logistic map: one row orbit R_y (computed by tile (y, y), or
// (N/2, y) with ORB_MID) and one column orbit C_x (computed by tile (x, (x+1) mod N), or (x, (N-1)/2)), each a
// different finite-precision variant of the same map. A second NoC plane, the orbit plane, broadcasts R_y
// along row y and C_x along column x (32 bits per cycle, separate from the 16-bit packet plane). Every tile
// (x, y) receives R_y and C_x and turns their lower bound error into one keystream byte per iteration:
// bits 9..16 below the leading one of |R_y - C_x| XOR bits 1..8 below it. N^2 tiles get N^2 distinct pairs
// from only 2N orbits, so most tiles hold no orbit datapath at all.
// All 2N orbits of a pass start from the SAME seed x0 (key schedule below) and differ only by their
// finite-precision variant, so |R_y - C_x| is twice the lower bound error of a genuine LBE pair. PERT > 0
// adds a keyed perturbation shared by every orbit: a 64-bit xorshift state ps, seeded from the key mix,
// steps once per iteration and its low PERT bits are XORed into every new orbit value
// (x' = F(x) ^ (ps' mod 2^PERT)). The orbits become non-autonomous (no exact period below 2^64 - 1) and the
// per-pass secret grows from x0 alone to x0 + ps (94 bits). LEAN > 0 fixes r = 4 - 2^-LEAN so
// r*t = (t << 2) - (t >> LEAN): one multiplier per orbit step instead of two (the key bits of r are unused).
// All tiles iterate in lock step: a pass starts when every tile has armed (ks_start), and an iteration
// happens only when every tile's byte FIFO has room (global AND, like the barrier). Each tile takes
// exactly TW*TH bytes per pass (byte j -> its j-th pixel in raster order), then stops filling, so tiles
// that finish early never stall the others. PLANE_REG = 1 registers the incoming orbit values and delays
// the byte by one cycle, so the plane wire and the byte logic are not in the orbit's cycle; MARGIN is the
// FIFO head-room needed when the push (PLANE_REG) and the global go (ORB_REG at the top) are registered.
module lbe_dist #(
    parameter TW = 8, TH = 8,
    parameter T = 64,                 // transient iterations per pass
    parameter ROW_SRC = 0,            // this tile computes the row orbit of its row
    parameter COL_SRC = 0,            // this tile computes the column orbit of its column
    parameter ROW_VAR = 0,            // finite-precision variant of the row orbit (2y)
    parameter COL_VAR = 1,            // variant of the column orbit (2x+1)
    parameter LEAN = 0,               // 0: r from the key; k: r = 4 - 2^-k, shift-subtract
    parameter PERT = 0,               // keyed perturbation bits XORed into every orbit after each step
    parameter PLANE_REG = 0,          // register row_in/col_in, byte one cycle later
    parameter MARGIN = 0,             // FIFO head-room for registered push / go
    parameter DEPTH = 32,             // byte FIFO
    parameter EXT = 0                 // byte extractor (lbe_ext.vh): 0 normalized fold, 1 D[15:8], 2 (R^C)[15:8], 3 n[22:15]
) (
    input             clk, rst,
    input             cfg_we,
    input  [3:0]      cfg_addr,
    input  [31:0]     cfg_wdata,
    input             take,
    output            hit,
    output [7:0]      ks_byte,
    output reg [31:0] bytes_made,
    // orbit plane
    output [31:0]     row_out,        // R_y (valid in the row source tile)
    output [31:0]     col_out,        // C_x (valid in the column source tile)
    input  [31:0]     row_in,         // R_y broadcast along the row
    input  [31:0]     col_in,         // C_x broadcast along the column
    output reg        armed,
    output            ready,
    input             all_armed,
    input             go
);
    localparam Q = TW * TH;
    localparam DW = $clog2(DEPTH);

    // key words 0..7 and nonce words 8..10 (same registers as the ChaCha unit)
    reg [31:0] kw [0:10];
    wire start = cfg_we && cfg_addr == 4'd15;
    always @(posedge clk) if (cfg_we && cfg_addr < 4'd11) kw[cfg_addr] <= cfg_wdata;
    wire [33:0] R = 34'h3E6666666 + {6'd0, kw[2][31:4]};
    // key schedule (scripts/lbe_ref.py): after start, two chains run over the 11 words in 11 cycles (the tile
    // arms when they are done): kmix = xorshift32 chain (XOR absorption) and kmix64 = xorshift64 chain with
    // additive absorption of {w, w ^ GOLD}. Every orbit starts from x0 = {01, mixw(0)[29:0]} with
    // mixw(v) = xs(xs(kmix ^ (v + 1) * GOLD)), a value in [0.25, 0.5) (never 0, 1 or 1 - 2^-32); the
    // perturbation state starts from xs64(kmix64) (GOLD64 if that is 0). x0 and the perturbation seed are
    // different functions of the key, so the per-pass secret is 30 + 64 bits.
    function [31:0] xs; input [31:0] a; reg [31:0] b;
        begin b = a ^ (a << 13); b = b ^ (b >> 17); xs = b ^ (b << 5); end
    endfunction
    function [63:0] xs64; input [63:0] a; reg [63:0] b;
        begin b = a ^ (a << 13); b = b ^ (b >> 7); xs64 = b ^ (b << 17); end
    endfunction
    function [31:0] mixw; input integer v; input [31:0] km;
        begin mixw = xs(xs(km ^ (32'h9E3779B9 * (v + 1)))); end
    endfunction
    function [31:0] seed_v; input integer v; input [31:0] km; reg [31:0] a;
        begin a = mixw(v, km); seed_v = {2'b01, a[29:0]}; end
    endfunction
    function [63:0] pert_seed; input [63:0] km64; input [31:0] c; reg [63:0] s;
        begin s = xs64(km64 ^ {32'd0, c}); pert_seed = (s == 64'd0) ? 64'h9E3779B97F4A7C15 : s; end
    endfunction
    reg        mixing;
    reg [3:0]  mix_i;
    reg [31:0] kmix;
    reg [63:0] kmix64;

    // r * t: multiply by R (keyed) or shift-subtract (LEAN), on values with g guard bits
    function [41:0] rmul; input [41:0] t; input [41:0] rr; input integer g; reg [83:0] p;
        begin
            if (LEAN) rmul = (t << 2) - (t >> LEAN);
            else begin p = rr * t; rmul = p >> (32 + g); end
        end
    endfunction
    // variant v of the map: expression v mod 6, g = v div 6 guard bits
    function [31:0] form_v; input integer v; input [31:0] xv;
        integer e, g; reg [41:0] xx, rr, one, rx; reg [83:0] p;
        begin
            e = v % 6; g = v / 6;
            xx = {10'd0, xv} << g; one = 42'd1 << (32 + g);
            rr = LEAN ? ((42'd1 << 34) - (42'd1 << (32 - LEAN))) << g : {8'd0, R} << g;
            rx = rmul(xx, rr, g);
            case (e)
                0: begin p = rx * (one - xx); form_v = (p >> (32 + g)) >> g; end
                1: begin p = rx * xx; form_v = (rx - (p >> (32 + g))) >> g; end
                2: begin p = xx * xx; form_v = rmul(xx - (p >> (32 + g)), rr, g) >> g; end
                3: begin p = xx * (rr - rx); form_v = (p >> (32 + g)) >> g; end
                4: begin p = xx * (one - xx); form_v = rmul(p >> (32 + g), rr, g) >> g; end
                default: begin p = xx * xx; form_v = (rx - rmul(p >> (32 + g), rr, g)) >> g; end
            endcase
        end
    endfunction
    `include "lbe_ext.vh"

    // orbit registers: only the source tiles hold a datapath
    reg [31:0] xr, xc;
    reg [63:0] ps;                    // keyed perturbation state (xorshift64), stepped with the orbits
    wire [63:0] ps_n = xs64(ps);
    wire [31:0] pmask = PERT ? ((32'd1 << PERT) - 1) : 32'd0;
    assign row_out = ROW_SRC ? xr : 32'd0;
    assign col_out = COL_SRC ? xc : 32'd0;

    // registered plane inputs (PLANE_REG): the byte is formed from last cycle's values, one cycle later
    reg [31:0] row_q, col_q;
    reg        push_q;
    always @(posedge clk) begin row_q <= row_in; col_q <= col_in; end
    wire [31:0] row_b = PLANE_REG ? row_q : row_in;
    wire [31:0] col_b = PLANE_REG ? col_q : col_in;

    // byte FIFO
    reg [7:0]  mem [0:DEPTH-1];
    reg [DW-1:0] rp, wp;
    reg [DW:0]   cnt;
    assign hit = cnt != 0;
    assign ks_byte = mem[rp];
    wire pop = take && hit;

    reg        running;
    reg [7:0]  it;                    // iterations applied, saturating at T + 1
    reg [15:0] pushed;
    wire       emit = it >= T + 1 && pushed != Q;
    assign ready = !running || pushed == Q || cnt < DEPTH - MARGIN;
    wire push = running && go && emit;
    wire fifo_we = PLANE_REG ? push_q : push;

    always @(posedge clk) begin
        if (rst) begin
            armed <= 0; running <= 0; rp <= 0; wp <= 0; cnt <= 0; bytes_made <= 0; mixing <= 0; push_q <= 0;
        end else if (start) begin
            armed <= 0; running <= 0; rp <= 0; wp <= 0; cnt <= 0; push_q <= 0;
            mixing <= 1; mix_i <= 0; kmix <= 0; kmix64 <= 0;
        end else begin
            if (mixing) begin
                kmix <= xs(kmix ^ kw[mix_i]);
                kmix64 <= xs64(kmix64 + {kw[mix_i], kw[mix_i] ^ 32'h9E3779B9});
                mix_i <= mix_i + 1'b1;
                if (mix_i == 4'd10) begin mixing <= 0; armed <= 1; end
            end
            if (armed && all_armed) begin
                armed <= 0; running <= 1; it <= 0; pushed <= 0;
                if (ROW_SRC) xr <= seed_v(0, kmix);
                if (COL_SRC) xc <= seed_v(0, kmix);
                ps <= pert_seed(kmix64, 32'd0);
            end else if (running && go) begin
                if (ROW_SRC) xr <= form_v(ROW_VAR, xr) ^ (ps_n[31:0] & pmask);
                if (COL_SRC) xc <= form_v(COL_VAR, xc) ^ (ps_n[31:0] & pmask);
                ps <= ps_n;
                if (it <= T) it <= it + 1'b1;
                if (emit) pushed <= pushed + 1'b1;
            end
            push_q <= push;
            if (fifo_we) begin mem[wp] <= ext_byte(EXT, row_b, col_b); wp <= wp + 1'b1; bytes_made <= bytes_made + 1; end
            if (pop) rp <= rp + 1'b1;
            cnt <= cnt + fifo_we - pop;
        end
    end
endmodule
