`include "mpriscv_defs.vh"
// MPRISC-V: N x N 2-D mesh of Tiles. The image (IMG_W x IMG_H) is partitioned
// into N x N rectangular regions, one per Tile. The PS connects only to the
// central Tile through the EXT port.
module mpriscv #(
    parameter N = 3,
    parameter IMG_W = 48, IMG_H = 48,
    parameter NSTEP = 8,
    parameter RAM_WORDS = 2048,
    parameter FIFO_DEPTH = 4,
    parameter FAST_CORE = 0,
    parameter PM_BYPASS = 0,
    parameter USE_PPU = 0,
    parameter USE_KS = 0,
    parameter KS_ROUNDS = 20,
    parameter KS_QR = 4,
    parameter KS_GEOM = 0,
    parameter LBE_LEAN = 0, LBE_PERT = 0,   // orbit plane: fixed lean r, counter perturbation (lbe_dist.v)
    parameter LBE_EXT = 0,                  // orbit plane: byte extractor (lbe_ext.vh)
    parameter PLANE_REG = 0, ORB_REG = 0,   // orbit plane: registered plane inputs, registered global go/armed
    parameter ORB_MID = 0,                  // source arrangement: 0 original, 1 centered, 2 paired centers, 3 paired diagonal
    parameter KS_IMPL = 1,
    parameter GRAIN_P = 16, GRAIN_Z = 1,    // KS_IMPL = 7 (per-tile Grain, track E_baselines)
    parameter LBE_K = 4, LBE_T = 40,   // KS_IMPL = 4 (LBE generator): orbits and transient
    parameter PART_ALIGN = 1,    // Tile borders on multiples of this many pixels (8 = keystream-block aligned)
    parameter KS_ROWHOST = 0     // USE_KS == 2: 0 = one generator at the central Tile (S-shared),
                                 // 1 = one generator per row, in the central column (S-row)
) (
    input                   clk, rst,
    input                   cpu_resetn,
    input                   prog_we,
    input  [31:0]           prog_addr,
    input  [31:0]           prog_data,
    input                   ext_in_valid,
    input  [`MSG_W-1:0]     ext_in_data,
    output                  ext_in_full,
    output                  ext_out_valid,
    output [`MSG_W-1:0]     ext_out_data,
    output                  all_done,
    output                  noc_busy,
    output [N*N-1:0]        mark_valid,
    output [N*N*32-1:0]     mark_data
);
    // General partition rule (balanced block partition): Tile column i owns image
    // columns [floor(i*W/N), floor((i+1)*W/N)), likewise for rows, so Tile sizes differ by at
    // most one pixel for any W, H, N. Requires W/N >= 2 and H/N >= 2.
    // With PART_ALIGN = A > 1 the borders are rounded to multiples of A:
    //   X0(i) = min(W, A * floor(i * ceil(W/A) / N)), X0(N) = W
    // (A = 8 puts every 8x8 keystream block inside one Tile, at the cost of up to A-1 pixels of imbalance).
    localparam C  = (N - 1) / 2;           // central tile index (x = y = C)
    localparam WB = (IMG_W + PART_ALIGN - 1) / PART_ALIGN, HB = (IMG_H + PART_ALIGN - 1) / PART_ALIGN;
    function integer org; input integer i, len, nb;
        org = (i >= N) ? len : (PART_ALIGN * ((i * nb) / N) > len ? len : PART_ALIGN * ((i * nb) / N));
    endfunction
    localparam NT = N * N;

    // link wires indexed by tile; per tile: [0]N [1]S [2]E [3]W
    wire [3:0]          o_valid [0:NT-1];
    wire [4*`MSG_W-1:0] o_data  [0:NT-1];
    wire [3:0]          i_full  [0:NT-1];
    wire [NT-1:0] arrived, done_v, busy_v;
    // orbit plane (KS_IMPL = 5): row orbit R_y from tile (y, y), column orbit C_x from tile (x, (x+1) mod N),
    // broadcast along the row / column; global arm and go (lock step), like the barrier
    wire [31:0]   orb_row_src [0:NT-1];
    wire [31:0]   orb_col_src [0:NT-1];
    wire [NT-1:0] orb_armed_v, orb_ready_v;
    wire orb_all_armed_c = &orb_armed_v;
    wire orb_go_c = &orb_ready_v;
    reg  orb_all_armed_r = 0, orb_go_r = 0;   // ORB_REG: the two N^2-input ANDs become registered (one cycle late)
    always @(posedge clk) begin orb_all_armed_r <= orb_all_armed_c; orb_go_r <= orb_go_c; end
    wire orb_all_armed = ORB_REG ? orb_all_armed_r : orb_all_armed_c;
    wire orb_go = ORB_REG ? orb_go_r : orb_go_c;
    localparam RSX = ORB_MID ? N / 2 : -1;          // row-source column (-1: the diagonal, x == y)
    localparam CSY = ORB_MID ? (N - 1) / 2 : -1;    // column-source row (-1: (x + 1) mod N)
    wire bar_all = &arrived & ~|busy_v;   // barrier also waits for the NoC to drain
    assign all_done = &done_v;
    assign noc_busy = |busy_v;

    wire [NT-1:0] ext_in_full_v, ext_out_valid_v;
    wire [`MSG_W-1:0] ext_out_data_v [0:NT-1];
    assign ext_in_full   = ext_in_full_v[C*N + C];
    assign ext_out_valid = ext_out_valid_v[C*N + C];
    assign ext_out_data  = ext_out_data_v[C*N + C];

    genvar x, y;
    generate for (y = 0; y < N; y = y + 1) begin : g_row
        for (x = 0; x < N; x = x + 1) begin : g_col
            localparam T  = y * N + x;
            localparam TN = (y > 0)     ? T - N : T;
            localparam TS = (y < N - 1) ? T + N : T;
            localparam TE = (x < N - 1) ? T + 1 : T;
            localparam TWs = (x > 0)    ? T - 1 : T;
            localparam HAS_N = (y > 0), HAS_S = (y < N-1), HAS_E = (x < N-1), HAS_W = (x > 0);
            localparam IS_C = (x == C) && (y == C);
            localparam X0 = org(x, IMG_W, WB), X1 = org(x + 1, IMG_W, WB);
            localparam Y0 = org(y, IMG_H, HB), Y1 = org(y + 1, IMG_H, HB);
            // Experiment-only source arrangement. Modes 0/1 retain the original mapping.
            // Mode 2 alternates the two central indices for even N (odd N uses mode 1).
            // Mode 3 co-locates R_y and C_y on tile (y,y), reducing source-containing tiles.
            // Stream variants still depend only on row/column coordinates, never source location.
            localparam ROW_SRC_X = (ORB_MID == 3) ? y :
                ((ORB_MID == 2 && N % 2 == 0) ? (N - 1) / 2 + y % 2 : (ORB_MID ? RSX : y));
            localparam COL_SRC_Y = (ORB_MID == 3) ? x :
                ((ORB_MID == 2 && N % 2 == 0) ? (N - 1) / 2 + x % 2 : (ORB_MID ? CSY : (x + 1) % N));

            // inputs: my N input = north neighbour's S output, etc.
            wire [3:0] in_valid = {
                HAS_W ? o_valid[TWs][`P_E] : 1'b0,
                HAS_E ? o_valid[TE][`P_W]  : 1'b0,
                HAS_S ? o_valid[TS][`P_N]  : 1'b0,
                HAS_N ? o_valid[TN][`P_S]  : 1'b0 };
            wire [4*`MSG_W-1:0] in_data = {
                o_data[TWs][`P_E*`MSG_W +: `MSG_W],
                o_data[TE][`P_W*`MSG_W +: `MSG_W],
                o_data[TS][`P_N*`MSG_W +: `MSG_W],
                o_data[TN][`P_S*`MSG_W +: `MSG_W] };
            wire [3:0] out_full = {
                HAS_W ? i_full[TWs][`P_E] : 1'b1,
                HAS_E ? i_full[TE][`P_W]  : 1'b1,
                HAS_S ? i_full[TS][`P_N]  : 1'b1,
                HAS_N ? i_full[TN][`P_S]  : 1'b1 };

            tile #(.XINIT(X0), .YINIT(Y0), .TW(X1 - X0), .TH(Y1 - Y0),
                   .IMG_W(IMG_W), .IMG_H(IMG_H), .N(N), .TILE_ID(T),
                   .NSTEP(NSTEP), .RAM_WORDS(RAM_WORDS), .FIFO_DEPTH(FIFO_DEPTH),
                   .FAST_CORE(FAST_CORE), .PM_BYPASS(PM_BYPASS), .USE_PPU(USE_PPU),
                   .USE_KS(USE_KS), .KS_ROUNDS(KS_ROUNDS), .KS_QR(KS_QR), .KS_GEOM(KS_GEOM), .KS_IMPL(KS_IMPL), .LBE_K(LBE_K), .LBE_T(LBE_T),
                   .GRAIN_P(GRAIN_P), .GRAIN_Z(GRAIN_Z),
                   .LBE_LEAN(LBE_LEAN), .LBE_PERT(LBE_PERT), .LBE_EXT(LBE_EXT), .PLANE_REG(PLANE_REG), .ORB_REG(ORB_REG),
                   .PART_ALIGN(PART_ALIGN),
                   .ORB_ROW_SRC(x == ROW_SRC_X), .ORB_COL_SRC(y == COL_SRC_Y),
                   .ORB_ROW_VAR(2 * y), .ORB_COL_VAR(2 * x + 1),
                   .KS_HOST(KS_ROWHOST ? x == C : IS_C), .HOST_X(org(C, IMG_W, WB)),
                   .HOST_Y(KS_ROWHOST ? Y0 : org(C, IMG_H, HB))) u_tile (
                .clk(clk), .rst(rst), .cpu_resetn(cpu_resetn),
                .prog_we(prog_we), .prog_addr(prog_addr), .prog_data(prog_data),
                .lnk_in_valid(in_valid), .lnk_in_data(in_data), .lnk_in_full(i_full[T]),
                .lnk_out_valid(o_valid[T]), .lnk_out_data(o_data[T]), .lnk_out_full(out_full),
                .ext_in_valid(IS_C ? ext_in_valid : 1'b0), .ext_in_data(ext_in_data),
                .ext_in_full(ext_in_full_v[T]),
                .ext_out_valid(ext_out_valid_v[T]), .ext_out_data(ext_out_data_v[T]),
                .bar_arrived(arrived[T]), .bar_all(bar_all), .done(done_v[T]),
                .mark_valid(mark_valid[T]), .mark_data(mark_data[T*32 +: 32]),
                .busy(busy_v[T]),
                .orb_row_out(orb_row_src[T]), .orb_col_out(orb_col_src[T]),
                .orb_row_in(orb_row_src[y * N + ROW_SRC_X]),
                .orb_col_in(orb_col_src[COL_SRC_Y * N + x]),
                .orb_armed(orb_armed_v[T]), .orb_ready(orb_ready_v[T]),
                .orb_all_armed(orb_all_armed), .orb_go(orb_go));
        end
    end endgenerate
endmodule
