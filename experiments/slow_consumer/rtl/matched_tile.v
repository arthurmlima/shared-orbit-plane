// Experiment-only common boundary. Original lbe_dist is unmodified.
module matched_tile #(
    parameter ROW_SRC=0, COL_SRC=0, ROW_VAR=0, COL_VAR=1, EXT=0,
    parameter TW=30, TH=30, T=64, LEAN=6, PERT=8, DEPTH=32
) (
    input clk, rst, cfg_we,
    input [3:0] cfg_addr,
    input [31:0] cfg_wdata,
    input take, all_armed, go,
    input [31:0] row_external, col_external,
    output hit, armed, ready,
    output [7:0] ks_byte,
    output [31:0] bytes_made, row_out, col_out
);
    // A source-containing tile consumes its own state, in both alternatives.
    wire [31:0] row_in = ROW_SRC ? row_out : row_external;
    wire [31:0] col_in = COL_SRC ? col_out : col_external;
    lbe_dist #(.TW(TW), .TH(TH), .T(T), .ROW_SRC(ROW_SRC),
        .COL_SRC(COL_SRC), .ROW_VAR(ROW_VAR), .COL_VAR(COL_VAR),
        .LEAN(LEAN), .PERT(PERT), .PLANE_REG(1), .MARGIN(2), .DEPTH(DEPTH), .EXT(EXT)) u (
        .clk(clk), .rst(rst), .cfg_we(cfg_we), .cfg_addr(cfg_addr),
        .cfg_wdata(cfg_wdata), .take(take), .hit(hit), .ks_byte(ks_byte),
        .bytes_made(bytes_made), .row_out(row_out), .col_out(col_out),
        .row_in(row_in), .col_in(col_in), .armed(armed), .ready(ready),
        .all_armed(all_armed), .go(go));
endmodule

// Identical to the original ORB_REG=1 reduction/register behavior.
module matched_control (
    input clk,
    input [15:0] armed, ready,
    output reg all_armed = 0,
    output reg go = 0
);
    always @(posedge clk) begin
        all_armed <= &armed;
        go <= &ready;
    end
endmodule

// The N x N mesh of matched tiles is plane_mesh.v (generalizes the former matched_mesh to any N and EXT).
