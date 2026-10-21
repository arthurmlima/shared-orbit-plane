`include "mpriscv_defs.vh"
// Simple synchronous FIFO used as router input buffer
module msg_fifo #(parameter DEPTH = 4, parameter W = `MSG_W) (
    input              clk, rst,
    input              push,
    input  [W-1:0]     din,
    input              pop,
    output [W-1:0]     dout,
    output             empty,
    output             full,
    output             afull      // at most one free slot
);
    localparam AW = (DEPTH <= 2) ? 1 : $clog2(DEPTH);
    reg [W-1:0] mem [0:DEPTH-1];
    reg [AW-1:0] rp, wp;
    reg [AW:0]   cnt;
    assign empty = (cnt == 0);
    assign full  = (cnt == DEPTH);
    assign afull = (cnt >= DEPTH-1);
    assign dout  = mem[rp];
    wire do_push = push && !full;
    wire do_pop  = pop && !empty;
    always @(posedge clk) begin
        if (rst) begin
            rp <= 0; wp <= 0; cnt <= 0;
        end else begin
            if (do_push) begin
                mem[wp] <= din;
                wp <= (wp == DEPTH-1) ? 0 : wp + 1'b1;
            end
            if (do_pop) rp <= (rp == DEPTH-1) ? 0 : rp + 1'b1;
            cnt <= cnt + do_push - do_pop;
        end
    end
endmodule
