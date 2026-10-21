`include "mpriscv_defs.vh"
// Pixel-Memory: per step, the Tile region plus a 1-pixel halo ring; 16-bit pixels.
//  Port A : write-only  (local core set_pixel, or the PPU result write)
//  Port B : read/write  (router: WR / HALO writes and remote REQ reads;
//                        or a local read - core bypass / PPU - which blocks the router that cycle)
module pixel_memory #(
    parameter XINIT = 0, YINIT = 0, TW = 8, TH = 8, NSTEP = 8,
    parameter AW = 16
) (
    input                   clk, rst,
    input                   a_we,
    input  [AW-1:0]         a_idx,
    input  [15:0]           a_data,
    input                   rd_en,          // local read (blocks router this cycle)
    input  [AW-1:0]         rd_idx,
    output [15:0]           rd_data,        // valid the cycle after rd_en
    input                   block_b,        // additional router block request
    input                   b_valid,
    input  [`MSG_W-1:0]     b_msg,
    input                   resp_afull,
    output                  b_full,
    output reg              resp_valid,
    output reg [`MSG_W-1:0] resp_msg,
    output                  pending
);
    localparam DEPTH = (TW + 2) * (TH + 2) * NSTEP;
    `include "pm_index.vh"
    (* ram_style = "block" *) reg [15:0] mem [0:DEPTH-1];

    always @(posedge clk)
        if (a_we) mem[a_idx] <= a_data;

    wire is_halo = b_msg[`F_TYPE] == `T_HALO;
    wire [AW-1:0] bidx = rd_en   ? rd_idx :
                         is_halo ? pm_index(b_msg[`F_OX], b_msg[`F_OY], b_msg[`F_STEP])
                                 : pm_index(b_msg[`F_TX], b_msg[`F_TY], b_msg[`F_STEP]);
    wire b_wr = !rd_en && b_valid && (b_msg[`F_TYPE] == `T_WR || is_halo);
    reg [15:0] rdata;
    assign rd_data = rdata;
    assign b_full = resp_afull | rd_en | block_b;

    always @(posedge clk) begin
        if (b_wr) mem[bidx] <= b_msg[`F_DATA];
        rdata <= mem[bidx];
    end

`ifdef DEBUG_HALO
    always @(posedge clk) if (b_wr && is_halo && XINIT == 0 && YINIT == 0)
        $display("T0 halo wr ox=%0d oy=%0d idx=%0d d=%0d", b_msg[`F_OX], b_msg[`F_OY], bidx, b_msg[`F_DATA]);
`endif
    reg rd_pend;
    reg [`MSG_W-1:0] pend_msg;
    assign pending = rd_pend;
    always @(posedge clk) begin
        if (rst) rd_pend <= 0;
        else     rd_pend <= !rd_en && b_valid && b_msg[`F_TYPE] == `T_REQ;
        pend_msg <= b_msg;
    end
    always @* begin
        resp_valid = rd_pend;
        resp_msg = pend_msg;
        resp_msg[`F_DATA] = rdata;
        resp_msg[`F_TX]   = pend_msg[`F_OX];
        resp_msg[`F_TY]   = pend_msg[`F_OY];
        resp_msg[`F_OX]   = pend_msg[`F_TX];
        resp_msg[`F_OY]   = pend_msg[`F_TY];
        resp_msg[`F_TYPE] = `T_RESP;
    end
endmodule
