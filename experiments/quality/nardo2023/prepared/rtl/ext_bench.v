// Level A microbenchmark: one byte extractor between an input register pair and an output register.
module ext_bench #(parameter EXT = 0) (
    input             clk,
    input  [31:0]     a_in, b_in,
    output reg [7:0]  byte_out
);
    reg [31:0] a_q, b_q;
    `include "lbe_ext.vh"
    always @(posedge clk) begin
        a_q <= a_in; b_q <= b_in;
        byte_out <= ext_byte(EXT, a_q, b_q);
    end
endmodule

// All four extractors on one input pair (simulation only, for the vector test).
module ext_bench4 (
    input             clk,
    input  [31:0]     a_in, b_in,
    output [7:0]      y0, y1, y2, y3
);
    ext_bench #(.EXT(0)) e0 (.clk(clk), .a_in(a_in), .b_in(b_in), .byte_out(y0));
    ext_bench #(.EXT(1)) e1 (.clk(clk), .a_in(a_in), .b_in(b_in), .byte_out(y1));
    ext_bench #(.EXT(2)) e2 (.clk(clk), .a_in(a_in), .b_in(b_in), .byte_out(y2));
    ext_bench #(.EXT(3)) e3 (.clk(clk), .a_in(a_in), .b_in(b_in), .byte_out(y3));
endmodule
