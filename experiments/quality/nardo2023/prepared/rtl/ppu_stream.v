`include "mpriscv_defs.vh"
// Streaming Pixel Processing Unit (PPU v2). Same programming model and op set as
// ppu.v, but fully pipelined:
//   R (issue PM read) -> D (data back, line buffers / window, compute) -> W (PM write,
//   enqueue halo record).
// CONV3 streams the halo-extended region (TW+2)x(TH+2) in raster order, reading each
// source pixel exactly once; two line buffers + a 3x3 window give one output per cycle.
// Unary ops (and SUM, THRESH) take one cycle per pixel, binary ops two.
// Halo messages are produced from a small record queue so the pipeline only throttles
// when the NoC injection port backs up.
module ppu_stream #(
    parameter XINIT = 0, YINIT = 0, TW = 8, TH = 8,
    parameter IMG_W = 16, IMG_H = 16, NSTEP = 8, AW = 16,
    parameter HQ_DEPTH = 8,
    parameter KS_GEOM = 0         // keystream block shape: 0 = 64x1 row segments, 1 = 8x8 squares
) (
    input                    clk, rst,
    input                    cfg_we,
    input  [4:0]             cfg_addr,
    input  [31:0]            cfg_wdata,
    input                    start,
    output                   busy,
    output                   done,
    output reg [31:0]        sum,
    output reg               rd_en,
    output reg [AW-1:0]      rd_idx,
    input  [15:0]            rd_data,
    output reg               we,
    output reg [AW-1:0]      w_idx,
    output reg [15:0]        w_data,
    output reg               inj_valid,
    output reg [`MSG_W-1:0]  inj_msg,
    input                    inj_full,
    input                    pm_want,       // router has a message for this PM: yield the port
    // keystream unit (XORKS op): lookup by the local coordinates being issued
    output [7:0]             ks_cx,
    output [7:0]             ks_cy,
    input                    ks_hit,
    input  [7:0]             ks_byte,
    output                   ks_take
);
    `include "pm_index.vh"

    localparam OP_CONV3 = 0, OP_ABS = 1, OP_MOV = 2, OP_THRESH = 3, OP_SUM = 4, OP_HALO = 5,
               OP_XORKS = 6,   // pixel XOR keystream byte (encrypt = decrypt)
               OP_ADD = 8, OP_SUB = 9, OP_MAX = 10, OP_MIN = 11, OP_ABSDIFF = 12;
    localparam HAS_W = XINIT > 0, HAS_E = XINIT + TW < IMG_W,
               HAS_N = YINIT > 0, HAS_S = YINIT + TH < IMG_H;
    localparam EW = TW + 2;

    // ---------------- configuration ----------------
    reg signed [15:0] coef [0:8];
    reg signed [17:0] scale;
    reg [4:0]         shift;
    reg signed [15:0] thr, hi, lo;
    reg [3:0] op, src_a, src_b, dst;
    reg       halo_en;
    reg       enc_out;                 // CTRL[17]: XOR the keystream into every written result
    integer i;
    always @(posedge clk) if (cfg_we) begin
        if (cfg_addr <= 8) coef[cfg_addr] <= cfg_wdata[15:0];
        case (cfg_addr)
            9:  scale <= cfg_wdata[17:0];
            10: shift <= cfg_wdata[4:0];
            11: thr   <= cfg_wdata[15:0];
            12: hi    <= cfg_wdata[15:0];
            13: lo    <= cfg_wdata[15:0];
            16: {enc_out, halo_en, dst, src_b, src_a, op} <= cfg_wdata[17:0];
            default: ;
        endcase
    end

    wire is_conv = op == OP_CONV3;
    wire is_bin  = op[3];
    wire writes  = op != OP_SUM && op != OP_HALO;
    wire do_halo = halo_en || op == OP_HALO;
    // encrypt-on-writeback: pointwise ops only (their issue coordinates are the output
    // coordinates, so the keystream lookup happens at issue, as for XORKS)
    wire fuse_ks = enc_out && writes && !is_conv && op != OP_XORKS;

    // ---------------- stage R: read issue ----------------
    reg        running;            // issue side active
    reg [7:0]  cx, cy;             // conv: ext coords (0..TW+1); others: local coords
    reg        ph;                 // binary op phase (0: A, 1: B)
    // halo record queue occupancy (declared here, used for throttling)
    reg [3:0]  hq_cnt;
    wire       is_xks = op == OP_XORKS;
    wire       use_ks = is_xks || fuse_ks;
    wire       can_issue = running && hq_cnt <= HQ_DEPTH - 3 && !pm_want && (!use_ks || ks_hit);
    // XORKS with 8x8 keystream blocks: visit pixels block by block (clipped to the Tile)
    // so each 64-byte keystream block is fully consumed before the next one is needed
    localparam BX0 = XINIT / 8, BX1 = (XINIT + TW - 1) / 8, BY0 = YINIT / 8, BY1 = (YINIT + TH - 1) / 8;
    reg [7:0] kbx, kby;
    wire blk_sweep = use_ks && KS_GEOM == 1;
    wire [11:0] gxc = XINIT + cx, gyc = YINIT + cy;
    wire [11:0] bxlo = (kbx * 8 > XINIT) ? kbx * 8 : XINIT;
    wire [11:0] bxhi = (kbx * 8 + 7 < XINIT + TW - 1) ? kbx * 8 + 7 : XINIT + TW - 1;
    wire [11:0] bylo = (kby * 8 > YINIT) ? kby * 8 : YINIT;
    wire [11:0] byhi = (kby * 8 + 7 < YINIT + TH - 1) ? kby * 8 + 7 : YINIT + TH - 1;
    wire blk_last = gxc == bxhi && gyc == byhi && kbx == BX1 && kby == BY1;
    assign ks_cx = cx;
    assign ks_cy = cy;
    assign ks_take = can_issue && use_ks && (!is_bin || ph);   // one take per pixel (binary ops issue twice)

    wire [7:0] xmax = is_conv ? TW + 1 : TW - 1;
    wire [7:0] ymax = is_conv ? TH + 1 : TH - 1;
    wire last_issue = cx == xmax && cy == ymax && (!is_bin || ph);
    wire skip_inner = op == OP_HALO && cx == 0 && cy != 0 && cy != TH - 1 && TW > 2;

    function [7:0] clamp8; input signed [11:0] v; input integer maxv;
        clamp8 = v < 0 ? 8'd0 : (v > maxv ? maxv[7:0] : v[7:0]);
    endfunction
    wire signed [11:0] egx = XINIT + cx - 1;
    wire signed [11:0] egy = YINIT + cy - 1;
    wire [7:0] lgx = XINIT + cx, lgy = YINIT + cy;

    always @* begin
        rd_en  = can_issue;
        rd_idx = is_conv ? pm_index(clamp8(egx, IMG_W - 1), clamp8(egy, IMG_H - 1), src_a)
                         : pm_index(lgx, lgy, (is_bin && ph) ? src_b : src_a);
    end

    // ---------------- stage D: data ----------------
    reg        d_v, d_ph;
    reg [7:0]  d_x, d_y;
    reg [7:0]  d_ks;                     // keystream byte travelling with the pixel
    reg signed [15:0] lb0 [0:EW-1];      // row y-1
    reg signed [15:0] lb1 [0:EW-1];      // row y-2
    reg signed [15:0] win [0:8];         // [row*3+col], col 2 = newest
    reg signed [15:0] ra;
    wire signed [15:0] din = rd_data;
    wire signed [15:0] c_top = lb1[d_x], c_mid = lb0[d_x];

    // effective 3x3 window including the column arriving now
    reg signed [15:0] weff [0:8];
    always @* begin
        weff[0] = win[1]; weff[1] = win[2]; weff[2] = c_top;
        weff[3] = win[4]; weff[4] = win[5]; weff[5] = c_mid;
        weff[6] = win[7]; weff[7] = win[8]; weff[8] = din;
    end

    reg signed [31:0] acc;
    reg signed [49:0] scaled;
    reg signed [15:0] result;
    reg signed [15:0] aop, bop;
    always @* begin
        acc = 0;
        for (i = 0; i < 9; i = i + 1) acc = acc + coef[i] * weff[i];
        scaled = acc * scale;
        aop = is_bin ? ra : din;
        bop = din;
        case (op)
            OP_CONV3:   result = scaled >>> shift;
            OP_ABS:     result = aop < 0 ? -aop : aop;
            OP_MOV:     result = aop;
            OP_THRESH:  result = aop > thr ? hi : lo;
            OP_XORKS:   result = aop ^ {8'h00, d_ks};
            OP_ADD:     result = aop + bop;
            OP_SUB:     result = aop - bop;
            OP_MAX:     result = aop > bop ? aop : bop;
            OP_MIN:     result = aop < bop ? aop : bop;
            OP_ABSDIFF: result = aop > bop ? aop - bop : bop - aop;
            default:    result = aop;
        endcase
        if (fuse_ks) result = result ^ {8'h00, d_ks};
    end
    // an output pixel is produced in D when...
    wire d_out = d_v && (is_conv ? (d_x >= 2 && d_y >= 2) : (!is_bin || d_ph));
    wire [7:0] d_lx = is_conv ? d_x - 2 : d_x;
    wire [7:0] d_ly = is_conv ? d_y - 2 : d_y;

    // ---------------- stage W: write + halo record ----------------
    reg        w_v;
    reg [7:0]  w_lx, w_ly;
    reg signed [15:0] w_res;
    wire bE = HAS_E && w_lx == TW - 1, bW = HAS_W && w_lx == 0;
    wire bN = HAS_N && w_ly == 0,      bS = HAS_S && w_ly == TH - 1;
    wire [7:0] w_mask = {bS & bW, bS & bE, bN & bW, bN & bE, bW, bE, bS, bN};
    wire [7:0] w_gx = XINIT + w_lx, w_gy = YINIT + w_ly;
    always @* begin
        we     = w_v && writes;
        w_idx  = pm_index(w_gx, w_gy, dst);
        w_data = w_res;
    end
    wire hq_push = w_v && do_halo && w_mask != 0;

    // halo record queue: {mask, value, gy, gx}
    localparam HR_W = 8 + 16 + 8 + 8;
    reg [HR_W-1:0] hq [0:HQ_DEPTH-1];
    reg [2:0] hq_rp, hq_wp;
    wire [HR_W-1:0] hhead = hq[hq_rp];
    reg  [7:0] hsent;                 // destinations of the head record already sent
    wire [7:0] cur_mask = hhead[39:32] & ~hsent;
    wire [2:0] hsel = cur_mask[0] ? 0 : cur_mask[1] ? 1 : cur_mask[2] ? 2 : cur_mask[3] ? 3 :
                      cur_mask[4] ? 4 : cur_mask[5] ? 5 : cur_mask[6] ? 6 : 7;
    reg signed [7:0] hdx, hdy;
    always @* begin
        case (hsel)
            0: begin hdx =  0; hdy = -1; end
            1: begin hdx =  0; hdy =  1; end
            2: begin hdx =  1; hdy =  0; end
            3: begin hdx = -1; hdy =  0; end
            4: begin hdx =  1; hdy = -1; end
            5: begin hdx = -1; hdy = -1; end
            6: begin hdx =  1; hdy =  1; end
            default: begin hdx = -1; hdy = 1; end
        endcase
    end
    wire [7:0] h_gx = hhead[7:0], h_gy = hhead[15:8];
    reg [3:0] h_step;
    wire hq_has = hq_cnt != 0;
    always @* begin
        inj_valid = hq_has && !inj_full;
        inj_msg = 0;
        inj_msg[`F_DATA] = hhead[31:16];
        inj_msg[`F_TX]   = h_gx + hdx;
        inj_msg[`F_TY]   = h_gy + hdy;
        inj_msg[`F_OX]   = h_gx;
        inj_msg[`F_OY]   = h_gy;
        inj_msg[`F_STEP] = h_step;
        inj_msg[`F_TYPE] = `T_HALO;
    end
    wire last_dest = (cur_mask & (cur_mask - 1)) == 0;
    wire hq_pop = inj_valid && last_dest;

    assign busy = running || d_v || w_v || hq_has;
    reg done_r;
    assign done = done_r;

    always @(posedge clk) begin
        if (rst) begin
            running <= 0; d_v <= 0; w_v <= 0; hq_cnt <= 0; hq_rp <= 0; hq_wp <= 0; hsent <= 0;
        end else begin
            // ---- R ----
            if (!running && !busy && start) begin
                running <= 1; cx <= 0; cy <= 0; ph <= 0; sum <= 0;
                kbx <= BX0; kby <= BY0;
            end else if (can_issue && blk_sweep) begin
                if (is_bin && !ph) ph <= 1;
                else begin
                    ph <= 0;
                    if (blk_last) running <= 0;
                    else if (gxc < bxhi) cx <= cx + 1;
                    else if (gyc < byhi) begin cx <= bxlo - XINIT; cy <= cy + 1; end
                    else if (kbx < BX1) begin
                        kbx <= kbx + 1; cx <= (kbx + 1) * 8 - XINIT; cy <= bylo - YINIT;
                    end else begin
                        kbx <= BX0; kby <= kby + 1; cx <= 0; cy <= (kby + 1) * 8 - YINIT;
                    end
                end
            end else if (can_issue) begin
                if (is_bin && !ph) ph <= 1;
                else begin
                    ph <= 0;
                    if (last_issue) running <= 0;
                    else if (skip_inner) cx <= TW - 1;
                    else if (cx == xmax) begin cx <= 0; cy <= cy + 1; end
                    else cx <= cx + 1;
                end
            end
            d_v <= can_issue; d_x <= cx; d_y <= cy; d_ph <= ph; d_ks <= ks_byte;

            // ---- D ----
            if (d_v) begin
                if (is_conv) begin
                    lb1[d_x] <= c_mid;
                    lb0[d_x] <= din;
                    // outputs only from ext column 2 on, so a plain shift suffices
                    win[0] <= win[1]; win[1] <= win[2]; win[2] <= c_top;
                    win[3] <= win[4]; win[4] <= win[5]; win[5] <= c_mid;
                    win[6] <= win[7]; win[7] <= win[8]; win[8] <= din;
                end
                if (is_bin && !d_ph) ra <= din;
                if (d_out && op == OP_SUM) sum <= sum + {{16{din[15]}}, din};
            end
            w_v <= d_out; w_lx <= d_lx; w_ly <= d_ly;
            w_res <= (op == OP_HALO) ? din : result;

            // ---- halo queue ----
            if (hq_push) begin
                hq[hq_wp] <= {w_mask, w_res, w_gy, w_gx};
                hq_wp <= hq_wp + 1'b1;
            end
            if (inj_valid) begin
                if (last_dest) begin hq_rp <= hq_rp + 1'b1; hsent <= 0; end
                else hsent <= hsent | (8'd1 << hsel);
            end
            hq_cnt <= hq_cnt + hq_push - hq_pop;
        end
    end

    // the halo step is the step whose pixels are being pushed
    always @(posedge clk) if (start) h_step <= (op == OP_HALO) ? src_a : dst;

    // done: one pulse once the issue side, pipeline and halo queue are all empty
    reg was_busy;
    always @(posedge clk) begin
        if (rst) was_busy <= 0;
        else if (start) was_busy <= 1;
        else if (was_busy && !busy) was_busy <= 0;
    end
    always @(posedge clk) if (!rst && was_busy && !busy && !start) done_r <= 1; else done_r <= 0;
endmodule
