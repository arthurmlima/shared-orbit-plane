`include "mpriscv_defs.vh"
// Pixel Processing Unit (PPU): a per-Tile, core-programmed engine that sweeps the
// Tile region of the Pixel-Memory and applies one IP/CV primitive per call:
//   0 CONV3   3x3 convolution, 9 signed coefs, out = (sum * scale) >>> shift
//   1 ABS     2 MOV     3 THRESH (a > thr ? hi : lo)
//   4 SUM     (reduction, no write; result in SUM register)
//   5 HALO    (border sweep only: push src pixels into the neighbours' halo cells)
//   8 ADD  9 SUB  10 MAX  11 MIN  12 ABSDIFF       (binary, srcA op srcB)
// CONV3 slides a 3x3 window along each row (9 reads at row start, then 3 per pixel)
// and reads the neighbour pixels from the PM halo ring, so the NoC is never on the
// critical path. With HALO_EN set, every border output pixel is pushed as a T_HALO
// message to the 1..3 neighbouring Tiles that need it for the next step.
module ppu #(
    parameter XINIT = 0, YINIT = 0, TW = 8, TH = 8,
    parameter IMG_W = 16, IMG_H = 16, NSTEP = 8, AW = 16
) (
    input                    clk, rst,
    input                    cfg_we,
    input  [4:0]             cfg_addr,
    input  [31:0]            cfg_wdata,
    input                    start,
    output                   busy,
    output reg               done,
    output reg [31:0]        sum,
    // Pixel-Memory
    output reg               rd_en,
    output reg [AW-1:0]      rd_idx,
    input  [15:0]            rd_data,
    output reg               we,
    output reg [AW-1:0]      w_idx,
    output reg [15:0]        w_data,
    // NoC injection (halo messages)
    output reg               inj_valid,
    output reg [`MSG_W-1:0]  inj_msg,
    input                    inj_full
);
    `include "pm_index.vh"

    localparam OP_CONV3 = 0, OP_ABS = 1, OP_MOV = 2, OP_THRESH = 3, OP_SUM = 4, OP_HALO = 5,
               OP_ADD = 8, OP_SUB = 9, OP_MAX = 10, OP_MIN = 11, OP_ABSDIFF = 12;
    localparam HAS_W = XINIT > 0, HAS_E = XINIT + TW < IMG_W,
               HAS_N = YINIT > 0, HAS_S = YINIT + TH < IMG_H;

    // ---------------- configuration ----------------
    reg signed [15:0] coef [0:8];
    reg signed [17:0] scale;
    reg [4:0]         shift;
    reg signed [15:0] thr, hi, lo;
    reg [3:0] op, src_a, src_b, dst;
    reg       halo_en;
    integer i;
    always @(posedge clk) begin
        if (cfg_we) begin
            if (cfg_addr <= 8) coef[cfg_addr] <= cfg_wdata[15:0];
            case (cfg_addr)
                9:  scale <= cfg_wdata[17:0];
                10: shift <= cfg_wdata[4:0];
                11: thr   <= cfg_wdata[15:0];
                12: hi    <= cfg_wdata[15:0];
                13: lo    <= cfg_wdata[15:0];
                16: {halo_en, dst, src_b, src_a, op} <= cfg_wdata[16:0];   // CTRL
                default: ;
            endcase
        end
    end

    // ---------------- sweep FSM ----------------
    localparam S_IDLE = 0, S_RD = 1, S_WB = 2, S_HALO = 3;
    reg [1:0] state;
    assign busy = state != S_IDLE;
    reg [7:0] lx, ly;
    reg [3:0] k;
    reg signed [15:0] win [0:8];      // conv window, index row*3+col
    reg signed [15:0] ra, rb;         // unary / binary operands
    reg        tag_v;
    reg [3:0]  tag_k;
    reg [7:0]  hmask;                 // pending halo destinations
    reg signed [15:0] hval;
    reg [3:0]  hstep;

    wire is_conv  = op == OP_CONV3;
    wire is_bin   = op[3];
    wire row_start = lx == 0;
    wire [3:0] nreads = is_conv ? (row_start ? 4'd9 : 4'd3) : (is_bin ? 4'd2 : 4'd1);
    wire writes  = op != OP_SUM && op != OP_HALO;
    wire do_halo = halo_en || op == OP_HALO;

    // conv read k -> (col,row)
    wire [1:0] kcol = !row_start ? 2'd2 : (k >= 6 ? 2'd2 : (k >= 3 ? 2'd1 : 2'd0));
    wire [1:0] krow = !row_start ? k[1:0] : (k >= 6 ? k - 6 : (k >= 3 ? k - 3 : k));

    function [7:0] clampx; input signed [11:0] v; input integer maxv;
        clampx = v < 0 ? 8'd0 : (v > maxv ? maxv[7:0] : v[7:0]);
    endfunction

    wire signed [11:0] cgx = XINIT + lx + kcol - 1;
    wire signed [11:0] cgy = YINIT + ly + krow - 1;
    wire [7:0] gx = XINIT + lx, gy = YINIT + ly;
    wire [AW-1:0] conv_idx = pm_index(clampx(cgx, IMG_W - 1), clampx(cgy, IMG_H - 1), src_a);
    wire [AW-1:0] a_idx = pm_index(gx, gy, src_a);
    wire [AW-1:0] b_idx = pm_index(gx, gy, src_b);

    // effective operands (bypass the read that lands in the S_WB cycle)
    reg signed [15:0] weff [0:8];
    reg signed [15:0] aeff, beff;
    always @* begin
        for (i = 0; i < 9; i = i + 1) weff[i] = win[i];
        aeff = ra; beff = rb;
        if (tag_v) begin
            if (is_conv) weff[(row_start ? (tag_k >= 6 ? tag_k - 6 : (tag_k >= 3 ? tag_k - 3 : tag_k)) : tag_k) * 3 + 2] = rd_data;
            else if (tag_k == 0) aeff = rd_data;
            else beff = rd_data;
        end
    end

    // datapath
    reg signed [31:0] acc;
    reg signed [49:0] scaled;
    reg signed [15:0] result;
    always @* begin
        acc = 0;
        for (i = 0; i < 9; i = i + 1) acc = acc + coef[i] * weff[i];
        scaled = acc * scale;
        case (op)
            OP_CONV3:   result = scaled >>> shift;
            OP_ABS:     result = aeff < 0 ? -aeff : aeff;
            OP_MOV:     result = aeff;
            OP_THRESH:  result = aeff > thr ? hi : lo;
            OP_ADD:     result = aeff + beff;
            OP_SUB:     result = aeff - beff;
            OP_MAX:     result = aeff > beff ? aeff : beff;
            OP_MIN:     result = aeff < beff ? aeff : beff;
            OP_ABSDIFF: result = aeff > beff ? aeff - beff : beff - aeff;
            default:    result = aeff;
        endcase
    end

    // halo destinations of the current pixel: {SW,SE,NW,NE,W,E,S,N}
    wire bE = HAS_E && lx == TW - 1, bW = HAS_W && lx == 0;
    wire bN = HAS_N && ly == 0,      bS = HAS_S && ly == TH - 1;
    wire [7:0] mask_now = {bS & bW, bS & bE, bN & bW, bN & bE, bW, bE, bS, bN};
    wire [2:0] hsel = hmask[0] ? 0 : hmask[1] ? 1 : hmask[2] ? 2 : hmask[3] ? 3 :
                      hmask[4] ? 4 : hmask[5] ? 5 : hmask[6] ? 6 : 7;
    reg signed [2:0] hdx, hdy;
    always @* begin
        case (hsel)
            0: begin hdx =  0; hdy = -1; end   // N
            1: begin hdx =  0; hdy =  1; end   // S
            2: begin hdx =  1; hdy =  0; end   // E
            3: begin hdx = -1; hdy =  0; end   // W
            4: begin hdx =  1; hdy = -1; end   // NE
            5: begin hdx = -1; hdy = -1; end   // NW
            6: begin hdx =  1; hdy =  1; end   // SE
            default: begin hdx = -1; hdy = 1; end // SW
        endcase
    end

    // next pixel (HALO op only visits the border ring)
    wire last_px = (lx == TW - 1) && (ly == TH - 1);
    wire [7:0] nx_raw = (lx == TW - 1) ? 8'd0 : lx + 1;
    wire [7:0] ny_raw = (lx == TW - 1) ? ly + 1 : ly;
    wire skip_inner = op == OP_HALO && lx == 0 && ly != 0 && ly != TH - 1 && TW > 2;
    wire [7:0] nx = skip_inner ? TW - 1 : nx_raw;
    wire [7:0] ny = skip_inner ? ly : ny_raw;

    // combinational PM read / write / inject
    always @* begin
        rd_en = state == S_RD;
        rd_idx = is_conv ? conv_idx : (k == 0 ? a_idx : b_idx);
        we = state == S_WB && writes;
        w_idx = pm_index(gx, gy, dst);
        w_data = result;
        inj_valid = state == S_HALO && !inj_full;
        inj_msg = 0;
        inj_msg[`F_DATA] = hval;
        inj_msg[`F_TX]   = gx + {{5{hdx[2]}}, hdx};
        inj_msg[`F_TY]   = gy + {{5{hdy[2]}}, hdy};
        inj_msg[`F_OX]   = gx;
        inj_msg[`F_OY]   = gy;
        inj_msg[`F_STEP] = hstep;
        inj_msg[`F_TYPE] = `T_HALO;
    end

    reg advance;
    always @* advance = (state == S_WB && !(do_halo && mask_now != 0)) ||
                        (state == S_HALO && !inj_full && (hmask & (hmask - 1)) == 0);

    always @(posedge clk) begin
        done <= 0;
        tag_v <= state == S_RD;
        tag_k <= k;
        if (rst) begin
            state <= S_IDLE;
        end else begin
            // capture read data
            if (tag_v) begin
                if (is_conv) win[(row_start ? (tag_k >= 6 ? tag_k - 6 : (tag_k >= 3 ? tag_k - 3 : tag_k)) : tag_k) * 3 +
                                 (row_start ? (tag_k >= 6 ? 2 : (tag_k >= 3 ? 1 : 0)) : 2)] <= rd_data;
                else if (tag_k == 0) ra <= rd_data;
                else rb <= rd_data;
            end
            case (state)
                S_IDLE: if (start) begin
                    lx <= 0; ly <= 0; k <= 0; sum <= 0;
                    state <= S_RD;
                end
                S_RD: begin
                    if (k == nreads - 1) begin k <= 0; state <= S_WB; end
                    else k <= k + 1;
                end
                S_WB: begin
                    if (op == OP_SUM) sum <= sum + {{16{aeff[15]}}, aeff};
                    if (do_halo && mask_now != 0) begin
                        hmask <= mask_now;
                        hval  <= op == OP_HALO ? aeff : result;
                        hstep <= op == OP_HALO ? src_a : dst;
                        state <= S_HALO;
                    end
                end
                S_HALO: if (!inj_full) hmask[hsel] <= 1'b0;
                default: ;
            endcase
            if (advance) begin
                if (last_px) begin
                    state <= S_IDLE; done <= 1;
                end else begin
                    if (is_conv && nx != 0) begin       // slide window left
                        for (i = 0; i < 3; i = i + 1) begin
                            win[i*3+0] <= weff[i*3+1];
                            win[i*3+1] <= weff[i*3+2];
                        end
                    end
                    lx <= nx; ly <= ny; state <= S_RD;
                end
            end
        end
    end
endmodule
