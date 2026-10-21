`include "mpriscv_defs.vh"
// Per-Tile keystream unit (placement S-local).
// Produces the partition-invariant pixel keystream for this Tile's region:
//   counter(x, y) = y * ceil(W/64) + x / 64,   byte = ChaCha(key, counter, nonce)[x % 64]
// so every Tile computes exactly the bytes of its own pixels and the ciphertext does not
// depend on how many Tiles the image is split into.
// A small in-order FIFO of 64-byte blocks is filled ahead of the PPU sweep: the block
// iterator walks the blocks this Tile needs, row by row, in the order the PPU visits them.
module ks_unit #(
    parameter XINIT = 0, YINIT = 0, TW = 8, TH = 8, IMG_W = 16,
    parameter ROUNDS = 20, QR = 4,
    parameter GEOM = 0,         // 0: blocks are 64x1 row segments, 1: blocks are 8x8 squares
    parameter SHARED = 0,       // 0: local ChaCha core (S-local); 1: fetch blocks over the NoC (S-shared)
    parameter HOST_X = 0, HOST_Y = 0
) (
    input             clk, rst,
    input             cfg_we,
    input  [3:0]      cfg_addr,        // 0..7 key words, 8..10 nonce words, 15 = start
    input  [31:0]     cfg_wdata,
    input  [7:0]      cx, cy,          // local coordinates being looked up (from the PPU)
    input             take,            // the PPU consumes this byte now
    output            hit,
    output [7:0]      ks_byte,
    output            busy,
    output reg [31:0] blocks_made,     // statistics
    output [255:0]    key_o,
    output [95:0]     nonce_o,
    // S-shared: block requests out through the router, keystream words back
    output                  nq_valid,
    output [`MSG_W-1:0]     nq_msg,
    input                   nq_full,
    input                   nr_valid,
    input  [`MSG_W-1:0]     nr_msg
);
    // GEOM 0: counter = y * ceil(W/64) + x/64,        byte = x % 64
    // GEOM 1: counter = (y/8) * ceil(W/8) + x/8,     byte = (y % 8) * 8 + x % 8
    localparam BPR = GEOM ? (IMG_W + 7) / 8 : (IMG_W + 63) / 64;
    localparam B0 = GEOM ? XINIT / 8 : XINIT / 64, B1 = GEOM ? (XINIT + TW - 1) / 8 : (XINIT + TW - 1) / 64;
    localparam R0 = GEOM ? YINIT / 8 : YINIT,       R1 = GEOM ? (YINIT + TH - 1) / 8 : YINIT + TH - 1;

    reg [255:0] key;
    reg [95:0]  nonce;
    assign key_o = key;
    assign nonce_o = nonce;
    wire start = cfg_we && cfg_addr == 4'd15;
    always @(posedge clk) if (cfg_we) begin
        if (cfg_addr < 8)  key[32 * cfg_addr +: 32] <= cfg_wdata;
        else if (cfg_addr < 11) nonce[32 * (cfg_addr - 8) +: 32] <= cfg_wdata;
    end

    // ---------------- block iterator (sweep order) ----------------
    reg [7:0]  it_r;
    reg [7:0]  it_b;
    reg        it_done, active;
    wire [31:0] it_ctr = it_r * BPR + it_b;

    // ---------------- block source: local ChaCha core or remote generator ----------------
    reg         c_start, c_discard;
    reg [31:0]  c_ctr;
    wire        c_busy, c_done;
    wire [511:0] c_blk;
    generate if (!SHARED) begin : g_local
        chacha_core #(.ROUNDS(ROUNDS), .QR(QR)) u_core (
            .clk(clk), .rst(rst), .key(key), .nonce(nonce), .counter(c_ctr),
            .start(c_start), .busy(c_busy), .done(c_done), .blk(c_blk));
        assign nq_valid = 1'b0;
        assign nq_msg = 0;
    end else begin : g_remote
        reg pend, wait_r, done_r;
        reg [4:0] cnt;
        reg [511:0] buf_r;
        assign c_busy = pend | wait_r;
        assign c_done = done_r;
        assign c_blk = buf_r;
        assign nq_valid = pend;
        reg [`MSG_W-1:0] m;
        always @* begin
            m = 0;
            m[`F_DATA] = c_ctr[15:0];
            m[`F_TX] = HOST_X; m[`F_TY] = HOST_Y;
            m[`F_OX] = XINIT;  m[`F_OY] = YINIT;
            m[`F_STEP] = 4'd15; m[`F_TYPE] = `T_REQ;
        end
        assign nq_msg = m;
        always @(posedge clk) begin
            done_r <= 0;
            if (rst) begin pend <= 0; wait_r <= 0; cnt <= 0; end
            else begin
                if (c_start) pend <= 1;
                else if (pend && !nq_full) begin pend <= 0; wait_r <= 1; cnt <= 0; end
                if (nr_valid && wait_r) begin
                    buf_r[16 * nr_msg[36:32] +: 16] <= nr_msg[`F_DATA];
                    cnt <= cnt + 1'b1;
                    if (cnt == 31) begin wait_r <= 0; done_r <= 1; end
                end
            end
        end
    end endgenerate

    // ---------------- 2-entry in-order block FIFO ----------------
    reg         v0, v1;
    reg [31:0]  k0, k1;
    reg [511:0] d0, d1;
    wire [7:0]  gx = XINIT + cx;
    wire [7:0]  gy = YINIT + cy;
    wire [31:0] req = GEOM ? (gy >> 3) * BPR + (gx >> 3) : gy * BPR + (gx >> 6);
    wire [5:0]  off = GEOM ? {gy[2:0], gx[2:0]} : gx[5:0];
    wire hit0 = v0 && k0 == req, hit1 = v1 && k1 == req;
    assign hit = hit0 | hit1;
    assign ks_byte = hit0 ? d0[8 * off +: 8] : d1[8 * off +: 8];
    assign busy = c_busy | c_start;

    wire pop = take && hit1 && !hit0;
    // count the block being pushed this cycle (c_done) too, or a launch can overrun the FIFO
    wire [1:0] occ = v0 + v1 + (c_busy | c_start | c_done);

    always @(posedge clk) begin
        c_start <= 0;
        if (rst) begin
            v0 <= 0; v1 <= 0; active <= 0; it_done <= 1; c_discard <= 0; blocks_made <= 0;
        end else if (start) begin
            v0 <= 0; v1 <= 0; active <= 1; it_done <= 0;
            it_r <= R0; it_b <= B0;
            c_discard <= c_busy | c_start;              // drop a block still in flight
        end else begin
            // consume / push
            if (pop) begin
                v0 <= v1; k0 <= k1; d0 <= d1; v1 <= 0;
            end
            if (c_done) begin
                if (c_discard) c_discard <= 0;
                else begin
                    blocks_made <= blocks_made + 1;
                    if (pop ? 1'b1 : v0) begin v1 <= 1; k1 <= c_ctr; d1 <= c_blk; end
                    else begin v0 <= 1; k0 <= c_ctr; d0 <= c_blk; end
                end
            end
            // launch the next block when there is room
            if (active && !it_done && !c_busy && !c_start && !c_discard && occ < 2) begin
                c_ctr <= it_ctr; c_start <= 1;
                if (it_b == B1) begin
                    it_b <= B0;
                    if (it_r == R1) it_done <= 1; else it_r <= it_r + 1;
                end else it_b <= it_b + 1;
            end
        end
    end
`ifdef DEBUG_KS
    always @(posedge clk) begin
        if (start) $display("%0t KS start", $time);
        if (c_start) $display("%0t KS launch ctr=%0d", $time, c_ctr);
        if (c_done) $display("%0t KS done ctr=%0d discard=%0d v0=%0d v1=%0d", $time, c_ctr, c_discard, v0, v1);
        if (pop) $display("%0t KS pop", $time);
    end
    reg [31:0] lastreq;
    always @(posedge clk) if (req != lastreq) begin lastreq <= req; $display("%0t KS req=%0d cx=%0d cy=%0d hit=%0d k0=%0d(%0d) k1=%0d(%0d)", $time, req, cx, cy, hit, k0, v0, k1, v1); end
`endif
endmodule
