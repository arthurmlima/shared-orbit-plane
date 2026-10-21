// Generator-and-distribution subsystem (Level B): N x N orbit-plane units with the mesh's ownership map, the row and
// column broadcast wires and the registered global all_armed / go reduction of mpriscv.v (ORB_REG = 1), without the
// RISC-V cores, routers, memories and PPUs. PRIVATE = 1 gives every tile both datapaths consuming their own state (the
// matched private control that produces the same bytes). MODE follows ORB_MID of mpriscv.v (1 centred, 2 paired
// central, 3 paired diagonal; 0 = original). Bytes, variants and interfaces are those of lbe_dist.v.
module plane_mesh #(
    parameter N = 4, TW = 30, TH = 30, MODE = 3, PRIVATE = 0, EXT = 0, LEAN = 6, PERT = 8, T = 64, DEPTH = 32,
    parameter LOCAL_GO = 0            // simulation check only: each tile steps on its own registered ready
) (
    input                clk, rst, cfg_we,
    input  [3:0]         cfg_addr,
    input  [31:0]        cfg_wdata,
    input  [N*N-1:0]     take,
    output [N*N-1:0]     hit,
    output [8*N*N-1:0]   data,
    output [32*N*N-1:0]  made,
    output [N*N-1:0]     ready_o,
    output               go_o
);
    wire [31:0] orb_row_src [0:N*N-1];
    wire [31:0] orb_col_src [0:N*N-1];
    wire [N*N-1:0] armed, ready;
    reg all_armed = 0, go = 0;
    reg [N*N-1:0] local_go = 0;
    always @(posedge clk) begin all_armed <= &armed; go <= &ready; local_go <= ready; end
    assign ready_o = ready;
    assign go_o = go;
    localparam RSX = MODE ? N / 2 : -1;
    localparam CSY = MODE ? (N - 1) / 2 : -1;
    genvar x, y;
    generate for (y = 0; y < N; y = y + 1) begin : gy
        for (x = 0; x < N; x = x + 1) begin : gx
            localparam I = N * y + x;
            // same expressions as mpriscv.v (ROW_SRC_X, COL_SRC_Y)
            localparam RX = (MODE == 3) ? y :
                ((MODE == 2 && N % 2 == 0) ? (N - 1) / 2 + y % 2 : (MODE ? RSX : y));
            localparam CY = (MODE == 3) ? x :
                ((MODE == 2 && N % 2 == 0) ? (N - 1) / 2 + x % 2 : (MODE ? CSY : (x + 1) % N));
            matched_tile #(.ROW_SRC(PRIVATE || x == RX), .COL_SRC(PRIVATE || y == CY),
                           .ROW_VAR(2 * y), .COL_VAR(2 * x + 1), .EXT(EXT),
                           .TW(TW), .TH(TH), .T(T), .LEAN(LEAN), .PERT(PERT), .DEPTH(DEPTH)) u (
                .clk(clk), .rst(rst), .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata),
                .take(take[I]), .hit(hit[I]), .ks_byte(data[8*I +: 8]), .bytes_made(made[32*I +: 32]),
                .row_external(orb_row_src[N * y + RX]), .col_external(orb_col_src[N * CY + x]),
                .row_out(orb_row_src[I]), .col_out(orb_col_src[I]), .armed(armed[I]), .ready(ready[I]),
                .all_armed(all_armed), .go(LOCAL_GO ? local_go[I] : go));
        end
    end endgenerate
endmodule
