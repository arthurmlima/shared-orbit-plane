`include "mpriscv_defs.vh"
// Area-optimised keystream unit (same function and interface as ks_unit.v).
// Differences: the two prefetched 64-byte blocks live in a 2 x 16-word distributed RAM
// instead of 1,536 flip-flops, the ChaCha core streams its block out one word per cycle
// (no 512-bit output register, no stored input copy), and FIFO pops move a head pointer
// instead of copying 512 bits.
module ks_unit2 #(
    parameter XINIT = 0, YINIT = 0, TW = 8, TH = 8, IMG_W = 16,
    parameter ROUNDS = 20, QR = 4,
    parameter GEOM = 0,
    parameter CORE = 0,          // 0: chacha_core (STREAM), 1: chacha_core2 (fixed QR wiring)
    parameter EARLY = 1,         // 1: serve bytes of a block while it is still being written
    parameter SHARED = 0,
    parameter HOST_X = 0, HOST_Y = 0
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
    output reg [31:0] blocks_made,
    output [255:0]    key_o,
    output [95:0]     nonce_o,
    output                  nq_valid,
    output [`MSG_W-1:0]     nq_msg,
    input                   nq_full,
    input                   nr_valid,
    input  [`MSG_W-1:0]     nr_msg
);
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

    // ---------------- block iterator ----------------
    reg [7:0] it_r, it_b;
    reg       it_done, active;
    wire [31:0] it_ctr = it_r * BPR + it_b;

    // ---------------- slots: 2 x 16 words in distributed RAM ----------------
    reg [15:0] mem_lo [0:31];
    reg [15:0] mem_hi [0:31];
    reg  [1:0] valid;
    reg [31:0] kc [0:1];
    reg        h;                                  // head slot
    reg        wslot;                              // slot being filled
    reg        we_lo, we_hi;
    reg  [4:0] waddr;
    reg [15:0] wd_lo, wd_hi;
    always @(posedge clk) begin
        if (we_lo) mem_lo[waddr] <= wd_lo;
        if (we_hi) mem_hi[waddr] <= wd_hi;
    end

    wire [7:0]  gx = XINIT + cx, gy = YINIT + cy;
    wire [31:0] req = GEOM ? (gy >> 3) * BPR + (gx >> 3) : gy * BPR + (gx >> 6);
    wire [5:0]  off = GEOM ? {gy[2:0], gx[2:0]} : gx[5:0];
    wire hit_h = valid[h] && kc[h] == req;
    wire hit_s = valid[~h] && kc[~h] == req;
    // early hit: the block being filled arrives in word order, so a byte can be served as soon
    // as its 32-bit word has been written (saves up to 16 cycles per block on short tile rows)
    reg        f_act, f_slot;
    reg [31:0] f_ctr;
    reg [4:0]  f_cnt;                              // complete 32-bit words written so far
    wire fh = EARLY && f_act && f_ctr == req && f_cnt > off[5:2];
    assign hit = hit_h | hit_s | fh;
    wire [4:0]  raddr = {hit_h ? h : hit_s ? ~h : f_slot, off[5:2]};
    wire [31:0] rword = {mem_hi[raddr], mem_lo[raddr]};
    assign ks_byte = rword[8 * off[1:0] +: 8];
    wire pop = take && !hit_h && (hit_s || (fh && f_slot != h));

    // ---------------- block source ----------------
    reg         c_start, c_discard;
    reg [31:0]  c_ctr;
    wire        c_busy, c_done;
    wire        w_valid;                           // a word (local) or half-word (remote) arrives
    wire [4:0]  w_idx;                             // word index (local) or half-word index (remote)
    wire [31:0] w_data;
    generate if (!SHARED) begin : g_local
        wire [3:0] oi;
        if (CORE) begin : g_c2
            chacha_core2 #(.ROUNDS(ROUNDS), .QR(QR)) u_core (
                .clk(clk), .rst(rst), .key(key), .nonce(nonce), .counter(c_ctr),
                .start(c_start), .busy(c_busy), .done(c_done),
                .ow_valid(w_valid), .ow_idx(oi), .ow_data(w_data));
        end else begin : g_c1
            chacha_core #(.ROUNDS(ROUNDS), .QR(QR), .STREAM(1)) u_core (
                .clk(clk), .rst(rst), .key(key), .nonce(nonce), .counter(c_ctr),
                .start(c_start), .busy(c_busy), .done(c_done), .blk(),
                .ow_valid(w_valid), .ow_idx(oi), .ow_data(w_data));
        end
        assign w_idx = {1'b0, oi};
        assign nq_valid = 1'b0;
        assign nq_msg = 0;
    end else begin : g_remote
        reg pend, wait_r, done_r;
        reg [4:0] cnt;
        assign c_busy = pend | wait_r;
        assign c_done = done_r;
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
        assign w_valid = nr_valid && wait_r;
        assign w_idx = nr_msg[36:32];
        assign w_data = {16'd0, nr_msg[`F_DATA]};
        always @(posedge clk) begin
            done_r <= 0;
            if (rst) begin pend <= 0; wait_r <= 0; cnt <= 0; end
            else begin
                if (c_start) pend <= 1;
                else if (pend && !nq_full) begin pend <= 0; wait_r <= 1; cnt <= 0; end
                if (w_valid) begin
                    cnt <= cnt + 1'b1;
                    if (cnt == 31) begin wait_r <= 0; done_r <= 1; end
                end
            end
        end
    end endgenerate

    // write port: target slot chosen when the first word of a block arrives
    wire first_w = w_valid && w_idx == 0;
    wire tslot = first_w ? (valid[h] ? ~h : h) : wslot;
    always @* begin
        we_lo = 0; we_hi = 0; waddr = 0; wd_lo = w_data[15:0]; wd_hi = w_data[31:16];
        if (w_valid && !c_discard) begin
            if (!SHARED) begin we_lo = 1; we_hi = 1; waddr = {tslot, w_idx[3:0]}; end
            else begin
                waddr = {tslot, w_idx[4:1]};
                we_lo = !w_idx[0]; we_hi = w_idx[0];
                wd_hi = w_data[15:0];
            end
        end
    end

    wire [1:0] occ = valid[0] + valid[1] + (c_busy | c_start | c_done);
    assign busy = c_busy | c_start;

    always @(posedge clk) begin
        c_start <= 0;
        if (rst) begin
            valid <= 0; h <= 0; active <= 0; it_done <= 1; c_discard <= 0; blocks_made <= 0; f_act <= 0;
        end else if (start) begin
            valid <= 0; h <= 0; active <= 1; it_done <= 0; f_act <= 0;
            it_r <= R0; it_b <= B0;
            c_discard <= c_busy | c_start;
        end else begin
            if (first_w) wslot <= tslot;
            if (first_w && !c_discard) begin f_act <= 1; f_slot <= tslot; f_ctr <= c_ctr; end
            if (first_w && !c_discard) f_cnt <= SHARED ? 5'd0 : 5'd1;   // remote: half-word 0 = low half
            else if (w_valid && !c_discard && (!SHARED || w_idx[0])) f_cnt <= f_cnt + 1'b1;
            if (pop) begin valid[h] <= 1'b0; h <= ~h; end
            if (c_done) begin
                f_act <= 0;
                if (c_discard) c_discard <= 0;
                else begin valid[wslot] <= 1'b1; kc[wslot] <= c_ctr; blocks_made <= blocks_made + 1; end
            end
            if (active && !it_done && !c_busy && !c_start && !c_discard && occ < 2) begin
                c_ctr <= it_ctr; c_start <= 1;
                if (it_b == B1) begin
                    it_b <= B0;
                    if (it_r == R1) it_done <= 1; else it_r <= it_r + 1;
                end else it_b <= it_b + 1;
            end
        end
    end
endmodule
