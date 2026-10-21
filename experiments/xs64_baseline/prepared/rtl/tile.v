`include "mpriscv_defs.vh"
// MPRISC-V Tile = PicoRV32 (RV32IM) + local RAM + Pixel-Memory + Router (+ optional PPU).
//
// Architectural options
//   FAST_CORE : zero-wait-state local RAM via PicoRV32 look-ahead bus, single-cycle-ish
//               multiplier (ENABLE_FAST_MUL) and barrel shifter
//   PM_BYPASS : get_pixel of a pixel owned by this Tile reads the PM directly
//               instead of making a round trip through the Router
//   USE_PPU   : per-Tile Pixel Processing Unit: 1 = FSM PPU (ppu.v), 2 = streaming PPU (ppu_stream.v)
//
// Core memory map
//   0x0...       local RAM (program + data)
//   0x2...       get_pixel (load)  addr = 0x2000_0000 | f<<24 | s<<20 | y<<12 | x<<2
//   0x3...       set_pixel (store) local PM write, same encoding
//   0x4000_0000  barrier   (store, stalls until all Tiles arrived and the NoC is drained)
//   0x5000_0000  marker    (store)
//   0x6000_0000  done      (store)
//   0x7000_00xx  Tile configuration (load): XINIT YINIT TW TH IMG_W IMG_H N ID
//   0x9000_00xx  keystream unit: words 0..7 key, 8..10 nonce, 15 start (store); load = blocks made
//   0x8000_00xx  PPU registers: 0..8 coef, 9 scale, 10 shift, 11 thr, 12 hi, 13 lo,
//                16 CTRL (store starts the PPU and stalls until done), 17 SUM (load)
module tile #(
    parameter XINIT = 0, YINIT = 0, TW = 8, TH = 8,
    parameter IMG_W = 16, IMG_H = 16, N = 2, TILE_ID = 0,
    parameter PART_ALIGN = 1,         // partition granularity in pixels (reported to software)
    parameter NSTEP = 8,
    parameter RAM_WORDS = 2048,
    parameter FIFO_DEPTH = 4,
    parameter FAST_CORE = 0,
    parameter PM_BYPASS = 0,
    parameter USE_PPU = 0,
    parameter USE_KS = 0,             // 0: none, 1: S-local unit, 2: S-shared (blocks over the NoC)
    parameter KS_ROUNDS = 20,
    parameter KS_QR = 4,
    parameter KS_GEOM = 0,
    parameter KS_IMPL = 1,            // 1: register-buffer unit (ks_unit), 2: LUTRAM-buffer unit (ks_unit2),
                                      // 3: ks_unit2 with the fixed-wiring ChaCha core (chacha_core2)
                                      // 4: multi-pseudo-orbit LBE generator (lbe_unit), USE_KS = 1 only
    parameter LBE_K = 4,              // KS_IMPL = 4: pseudo-orbits (forms)
    parameter LBE_T = 40,             // KS_IMPL = 4: transient iterations per block (5: per pass)
    parameter LBE_LEAN = 0, LBE_PERT = 0, PLANE_REG = 0, ORB_REG = 0,   // KS_IMPL = 5 variants (see lbe_dist.v)
    parameter LBE_EXT = 0,            // KS_IMPL = 5 byte extractor (rtl/lbe_ext.vh)
                                      // KS_IMPL = 5: distributed orbits on the orbit plane (lbe_dist)
    parameter ORB_ROW_SRC = 0, ORB_COL_SRC = 0,  // this tile computes its row / column orbit
    parameter ORB_ROW_VAR = 0, ORB_COL_VAR = 1,  // finite-precision variants of those orbits
    parameter GRAIN_P = 16, GRAIN_Z = 1,  // KS_IMPL = 7: Grain pre-output clocks per cycle, byte = even bits (1) / all bits (0)
                                      // KS_IMPL = 6: per-tile Trivium (trivium_unit), 7: per-tile Grain-128AEADv2
                                      // keystream (grain_unit); one sequential stream per tile, USE_KS = 1 only
                                      // (track mcsoc2027/tracks/E_baselines)
    parameter KS_HOST = 0,            // this Tile hosts the shared generator (USE_KS == 2)
    parameter HOST_X = 0, HOST_Y = 0  // origin pixel of the host Tile
) (
    input                        clk, rst,
    input                        cpu_resetn,
    input                        prog_we,
    input  [31:0]                prog_addr,
    input  [31:0]                prog_data,
    input  [3:0]                 lnk_in_valid,
    input  [4*`MSG_W-1:0]        lnk_in_data,
    output [3:0]                 lnk_in_full,
    output [3:0]                 lnk_out_valid,
    output [4*`MSG_W-1:0]        lnk_out_data,
    input  [3:0]                 lnk_out_full,
    input                        ext_in_valid,
    input  [`MSG_W-1:0]          ext_in_data,
    output                       ext_in_full,
    output                       ext_out_valid,
    output [`MSG_W-1:0]          ext_out_data,
    output reg                   bar_arrived,
    input                        bar_all,
    output reg                   done,
    output reg                   mark_valid,
    output reg [31:0]            mark_data,
    output                       busy,
    // orbit plane (KS_IMPL = 5)
    output [31:0]                orb_row_out,
    output [31:0]                orb_col_out,
    input  [31:0]                orb_row_in,
    input  [31:0]                orb_col_in,
    output                       orb_armed,
    output                       orb_ready,
    input                        orb_all_armed,
    input                        orb_go
);
    localparam AW = $clog2((TW + 2) * (TH + 2) * NSTEP);
    `include "pm_index.vh"

    // ---------------- core ----------------
    wire        mem_valid, mem_instr, mem_la_read, mem_la_write;
    wire [31:0] mem_addr, mem_wdata, mem_la_addr;
    wire [3:0]  mem_wstrb;
    wire        mem_ready;
    wire [31:0] mem_rdata;

    picorv32 #(
        .ENABLE_COUNTERS(1), .ENABLE_COUNTERS64(0),
        .ENABLE_REGS_16_31(1), .ENABLE_REGS_DUALPORT(1),
        .TWO_STAGE_SHIFT(1), .BARREL_SHIFTER(FAST_CORE),
        .TWO_CYCLE_COMPARE(0), .TWO_CYCLE_ALU(0),
        .COMPRESSED_ISA(0), .CATCH_MISALIGN(0), .CATCH_ILLINSN(0),
        .ENABLE_PCPI(0), .ENABLE_MUL(!FAST_CORE), .ENABLE_FAST_MUL(FAST_CORE), .ENABLE_DIV(1),
        .ENABLE_IRQ(0), .ENABLE_TRACE(0),
        .PROGADDR_RESET(32'h0), .STACKADDR(RAM_WORDS*4)
    ) u_cpu (
        .clk(clk), .resetn(cpu_resetn),
        .mem_valid(mem_valid), .mem_instr(mem_instr), .mem_ready(mem_ready),
        .mem_addr(mem_addr), .mem_wdata(mem_wdata), .mem_wstrb(mem_wstrb),
        .mem_rdata(mem_rdata),
        .mem_la_read(mem_la_read), .mem_la_write(mem_la_write), .mem_la_addr(mem_la_addr),
        .pcpi_wr(1'b0), .pcpi_rd(32'b0), .pcpi_wait(1'b0), .pcpi_ready(1'b0),
        .irq(32'b0)
    );

    wire [3:0] region = mem_addr[31:28];
    reg        mmio_ready;
    reg [31:0] mmio_rdata;

    // ---------------- local RAM ----------------
    localparam RAW = $clog2(RAM_WORDS);
    (* ram_style = "block" *) reg [31:0] ram [0:RAM_WORDS-1];
    reg  [31:0] ram_q;
    reg         ram_pend, ram_pend2;   // baseline: 2 wait states (as in the reproduction)
    wire ram_access = mem_valid && region == 4'h0;
    // FAST: read is launched from the look-ahead address one cycle early -> zero wait states
    wire [RAW-1:0] rd_word = FAST_CORE ? mem_la_addr[RAW+1:2] : mem_addr[RAW+1:2];
    wire [RAW-1:0] ram_idx = prog_we ? prog_addr[RAW+1:2] :
                             (|mem_wstrb && ram_access) ? mem_addr[RAW+1:2] : rd_word;
    wire ram_wr = ram_access && |mem_wstrb && !(FAST_CORE ? 1'b0 : (ram_pend | ram_pend2));
    always @(posedge clk) begin
        if (prog_we) ram[ram_idx] <= prog_data;
        else if (ram_wr) begin
            if (mem_wstrb[0]) ram[ram_idx][ 7: 0] <= mem_wdata[ 7: 0];
            if (mem_wstrb[1]) ram[ram_idx][15: 8] <= mem_wdata[15: 8];
            if (mem_wstrb[2]) ram[ram_idx][23:16] <= mem_wdata[23:16];
            if (mem_wstrb[3]) ram[ram_idx][31:24] <= mem_wdata[31:24];
        end
        ram_q <= ram[ram_idx];
    end
    wire ram_ready = FAST_CORE ? ram_access : ram_pend2;

    // ---------------- PM bypass read (local get_pixel) ----------------
    wire [7:0] gp_x = mem_addr[9:2], gp_y = mem_addr[19:12];
    wire [3:0] gp_s = mem_addr[23:20];
    wire gp_local = gp_x >= XINIT && gp_x < XINIT + TW && gp_y >= YINIT && gp_y < YINIT + TH;
    reg  byp_pend;
    wire byp_rd = PM_BYPASS && mem_valid && region == 4'h2 && gp_local && !byp_pend;
    wire [15:0] pm_rd_data;

    // ---------------- PPU ----------------
    wire ppu_busy, ppu_done, ppu_rd_en, ppu_we, ppu_inj_valid;
    wire [AW-1:0] ppu_rd_idx, ppu_w_idx;
    wire [15:0] ppu_w_data;
    wire [31:0] ppu_sum;
    wire [`MSG_W-1:0] ppu_inj_msg;
    reg ppu_start, ppu_started;
    wire ppu_cfg_we = USE_PPU && mem_valid && !mem_ready && region == 4'h8 && |mem_wstrb && !ppu_started;
    wire [`NPORTS-1:0] r_in_full, r_in_afull, r_out_valid;

    wire r_pm_want;
    // keystream unit wiring
    wire [7:0] ks_cx, ks_cy, ks_byte;
    wire ks_hit, ks_take, ks_busy;
    wire [31:0] ks_blocks;
    wire ks_cfg_we = mem_valid && !mem_ready && region == 4'h9 && |mem_wstrb;
    wire               nq_valid, nr_valid;
    wire [`MSG_W-1:0]  nq_msg;
    wire [255:0]       ks_key;
    wire [95:0]        ks_nonce;
    wire               nq_full;
    generate if (USE_KS == 1 && KS_IMPL == 5) begin : g_dist
        // distributed pseudo-orbits: this tile pairs its row orbit with its column orbit
        lbe_dist #(.TW(TW), .TH(TH), .T(LBE_T), .ROW_SRC(ORB_ROW_SRC), .COL_SRC(ORB_COL_SRC),
                   .ROW_VAR(ORB_ROW_VAR), .COL_VAR(ORB_COL_VAR), .LEAN(LBE_LEAN), .PERT(LBE_PERT),
                   .PLANE_REG(PLANE_REG), .MARGIN(PLANE_REG + ORB_REG), .EXT(LBE_EXT)) u_ks (
            .clk(clk), .rst(rst), .cfg_we(ks_cfg_we), .cfg_addr(mem_addr[5:2]), .cfg_wdata(mem_wdata),
            .take(ks_take), .hit(ks_hit), .ks_byte(ks_byte), .bytes_made(ks_blocks),
            .row_out(orb_row_out), .col_out(orb_col_out), .row_in(orb_row_in), .col_in(orb_col_in),
            .armed(orb_armed), .ready(orb_ready), .all_armed(orb_all_armed), .go(orb_go));
        assign ks_busy = 0;
        assign nq_valid = 0; assign nq_msg = 0; assign ks_key = 0; assign ks_nonce = 0;
    end else if (USE_KS == 1 && KS_IMPL == 8) begin : g_xs64
        xs64_unit #(.TILE_ID(TILE_ID)) u_ks (
            .clk(clk), .rst(rst), .cfg_we(ks_cfg_we), .cfg_addr(mem_addr[5:2]), .cfg_wdata(mem_wdata),
            .take(ks_take), .hit(ks_hit), .ks_byte(ks_byte), .bytes_made(ks_blocks));
        assign ks_busy = 0;
        assign nq_valid = 0; assign nq_msg = 0; assign ks_key = 0; assign ks_nonce = 0;
    end else if (USE_KS == 1 && KS_IMPL == 6) begin : g_triv
        // per-tile Trivium: IV = nonce bits 0..71 || tile index
        trivium_unit #(.TILE_ID(TILE_ID)) u_ks (
            .clk(clk), .rst(rst), .cfg_we(ks_cfg_we), .cfg_addr(mem_addr[5:2]), .cfg_wdata(mem_wdata),
            .take(ks_take), .hit(ks_hit), .ks_byte(ks_byte), .bytes_made(ks_blocks));
        assign ks_busy = 0;
        assign nq_valid = 0; assign nq_msg = 0; assign ks_key = 0; assign ks_nonce = 0;
    end else if (USE_KS == 1 && KS_IMPL == 7) begin : g_grain
        // per-tile Grain-128AEADv2 keystream (no authentication): IV = nonce bits 0..87 || tile index
        grain_unit #(.TILE_ID(TILE_ID), .P(GRAIN_P), .Z(GRAIN_Z)) u_ks (
            .clk(clk), .rst(rst), .cfg_we(ks_cfg_we), .cfg_addr(mem_addr[5:2]), .cfg_wdata(mem_wdata),
            .take(ks_take), .hit(ks_hit), .ks_byte(ks_byte), .bytes_made(ks_blocks));
        assign ks_busy = 0;
        assign nq_valid = 0; assign nq_msg = 0; assign ks_key = 0; assign ks_nonce = 0;
    end else if (USE_KS == 1 && KS_IMPL == 4) begin : g_lbe
        // multi-pseudo-orbit (pairwise lower-bound-error) generator, S-local only
        lbe_unit #(.XINIT(XINIT), .YINIT(YINIT), .TW(TW), .TH(TH), .IMG_W(IMG_W), .GEOM(KS_GEOM),
                   .K(LBE_K), .T(LBE_T), .PERT(LBE_PERT)) u_ks (
            .clk(clk), .rst(rst), .cfg_we(ks_cfg_we), .cfg_addr(mem_addr[5:2]), .cfg_wdata(mem_wdata),
            .cx(ks_cx), .cy(ks_cy), .take(ks_take), .hit(ks_hit), .ks_byte(ks_byte),
            .busy(ks_busy), .blocks_made(ks_blocks));
        assign nq_valid = 0; assign nq_msg = 0; assign ks_key = 0; assign ks_nonce = 0;
    end else if (USE_KS != 0 && (KS_IMPL == 2 || KS_IMPL == 3)) begin : g_ks2
        ks_unit2 #(.XINIT(XINIT), .YINIT(YINIT), .TW(TW), .TH(TH), .IMG_W(IMG_W),
                  .ROUNDS(KS_ROUNDS), .QR(KS_QR), .GEOM(KS_GEOM), .CORE(KS_IMPL == 3),
                  .SHARED(USE_KS == 2), .HOST_X(HOST_X), .HOST_Y(HOST_Y)) u_ks (
            .clk(clk), .rst(rst), .cfg_we(ks_cfg_we), .cfg_addr(mem_addr[5:2]), .cfg_wdata(mem_wdata),
            .cx(ks_cx), .cy(ks_cy), .take(ks_take), .hit(ks_hit), .ks_byte(ks_byte),
            .busy(ks_busy), .blocks_made(ks_blocks), .key_o(ks_key), .nonce_o(ks_nonce),
            .nq_valid(nq_valid), .nq_msg(nq_msg), .nq_full(nq_full),
            .nr_valid(nr_valid), .nr_msg(r_out_data[`P_CORE*`MSG_W +: `MSG_W]));
    end else if (USE_KS != 0) begin : g_ks
        ks_unit #(.XINIT(XINIT), .YINIT(YINIT), .TW(TW), .TH(TH), .IMG_W(IMG_W),
                  .ROUNDS(KS_ROUNDS), .QR(KS_QR), .GEOM(KS_GEOM),
                  .SHARED(USE_KS == 2), .HOST_X(HOST_X), .HOST_Y(HOST_Y)) u_ks (
            .clk(clk), .rst(rst), .cfg_we(ks_cfg_we), .cfg_addr(mem_addr[5:2]), .cfg_wdata(mem_wdata),
            .cx(ks_cx), .cy(ks_cy), .take(ks_take), .hit(ks_hit), .ks_byte(ks_byte),
            .busy(ks_busy), .blocks_made(ks_blocks), .key_o(ks_key), .nonce_o(ks_nonce),
            .nq_valid(nq_valid), .nq_msg(nq_msg), .nq_full(nq_full),
            .nr_valid(nr_valid), .nr_msg(r_out_data[`P_CORE*`MSG_W +: `MSG_W]));
    end else begin : g_noks
        assign ks_hit = 0; assign ks_byte = 0; assign ks_busy = 0; assign ks_blocks = 0;
        assign nq_valid = 0; assign nq_msg = 0; assign ks_key = 0; assign ks_nonce = 0;
    end endgenerate

    generate if (!(USE_KS == 1 && KS_IMPL == 5)) begin : g_noorb
        assign orb_row_out = 0; assign orb_col_out = 0; assign orb_armed = 0; assign orb_ready = 1;
    end endgenerate

    generate if (USE_PPU == 2) begin : g_ppu2
        ppu_stream #(.XINIT(XINIT), .YINIT(YINIT), .TW(TW), .TH(TH), .IMG_W(IMG_W), .IMG_H(IMG_H),
              .NSTEP(NSTEP), .AW(AW), .KS_GEOM(KS_IMPL >= 5 ? 0 : KS_GEOM)) u_ppu (
            .clk(clk), .rst(rst),
            .cfg_we(ppu_cfg_we), .cfg_addr(mem_addr[6:2]), .cfg_wdata(mem_wdata),
            .start(ppu_start), .busy(ppu_busy), .done(ppu_done), .sum(ppu_sum),
            .rd_en(ppu_rd_en), .rd_idx(ppu_rd_idx), .rd_data(pm_rd_data),
            .we(ppu_we), .w_idx(ppu_w_idx), .w_data(ppu_w_data),
            .inj_valid(ppu_inj_valid), .inj_msg(ppu_inj_msg), .inj_full(r_in_full[`P_CORE]),
            .pm_want(r_pm_want),
            .ks_cx(ks_cx), .ks_cy(ks_cy), .ks_hit(ks_hit), .ks_byte(ks_byte), .ks_take(ks_take));
    end else if (USE_PPU == 1) begin : g_ppu
        ppu #(.XINIT(XINIT), .YINIT(YINIT), .TW(TW), .TH(TH), .IMG_W(IMG_W), .IMG_H(IMG_H),
              .NSTEP(NSTEP), .AW(AW)) u_ppu (
            .clk(clk), .rst(rst),
            .cfg_we(ppu_cfg_we), .cfg_addr(mem_addr[6:2]), .cfg_wdata(mem_wdata),
            .start(ppu_start), .busy(ppu_busy), .done(ppu_done), .sum(ppu_sum),
            .rd_en(ppu_rd_en), .rd_idx(ppu_rd_idx), .rd_data(pm_rd_data),
            .we(ppu_we), .w_idx(ppu_w_idx), .w_data(ppu_w_data),
            .inj_valid(ppu_inj_valid), .inj_msg(ppu_inj_msg), .inj_full(r_in_full[`P_CORE]));
    end else begin : g_noppu
        assign ppu_busy = 0; assign ppu_done = 0; assign ppu_rd_en = 0; assign ppu_we = 0;
        assign ppu_inj_valid = 0; assign ppu_rd_idx = 0; assign ppu_w_idx = 0;
        assign ppu_w_data = 0; assign ppu_sum = 0; assign ppu_inj_msg = 0;
    end endgenerate

    // ---------------- router / PM wiring ----------------
    reg                 core_req_valid;
    reg  [`MSG_W-1:0]   core_req_msg;
    wire                pm_resp_valid;
    wire [`MSG_W-1:0]   pm_resp_msg;
    wire [`NPORTS*`MSG_W-1:0] r_out_data;
    wire                pm_full, pm_pending, r_busy;

    // the CORE input port is shared by core requests and PPU halo injections
    // (the core is stalled while the PPU runs)
    wire               nq_go = nq_valid && !nq_full;
    assign nq_full = r_in_full[`P_CORE] | core_req_valid | ppu_inj_valid;
    wire               inj_v = core_req_valid | ppu_inj_valid | nq_go;
    wire [`MSG_W-1:0]  inj_m = ppu_inj_valid ? ppu_inj_msg : core_req_valid ? core_req_msg : nq_msg;

    // shared keystream generator (only in the host Tile)
    wire [`MSG_W-1:0]  pm_out_msg = r_out_data[`P_PM*`MSG_W +: `MSG_W];
    wire               to_host = pm_out_msg[`F_STEP] == 4'd15;
    wire               host_req_full, host_resp_valid, host_busy;
    wire [`MSG_W-1:0]  host_resp_msg;
    wire               host_resp_ready = !pm_resp_valid && !r_in_full[`P_PM];
    generate if (USE_KS == 2 && KS_HOST) begin : g_host
        ks_host #(.ROUNDS(KS_ROUNDS), .QR(KS_QR)) u_host (
            .clk(clk), .rst(rst), .key(ks_key), .nonce(ks_nonce),
            .req_valid(r_out_valid[`P_PM] && to_host), .req_msg(pm_out_msg), .req_full(host_req_full),
            .resp_valid(host_resp_valid), .resp_msg(host_resp_msg), .resp_ready(host_resp_ready),
            .busy(host_busy), .blocks_made());
    end else begin : g_nohost
        assign host_req_full = 0; assign host_resp_valid = 0; assign host_resp_msg = 0; assign host_busy = 0;
    end endgenerate
    wire               host_push = host_resp_valid && host_resp_ready;
    wire               pmq_v = pm_resp_valid | host_push;
    wire [`MSG_W-1:0]  pmq_m = pm_resp_valid ? pm_resp_msg : host_resp_msg;

    wire [`NPORTS-1:0] r_in_valid = {ext_in_valid, pmq_v, inj_v, lnk_in_valid};
    wire [`NPORTS*`MSG_W-1:0] r_in_data = {ext_in_data, pmq_m, inj_m, lnk_in_data};
    wire [`NPORTS-1:0] r_out_full = {1'b0, pm_full | host_req_full, 1'b0, lnk_out_full};

    router #(.XINIT(XINIT), .YINIT(YINIT), .TW(TW), .TH(TH), .DEPTH(FIFO_DEPTH)) u_router (
        .clk(clk), .rst(rst),
        .in_valid(r_in_valid), .in_data(r_in_data), .in_full(r_in_full), .in_afull(r_in_afull),
        .out_valid(r_out_valid), .out_data(r_out_data), .out_full(r_out_full), .busy(r_busy),
        .pm_want(r_pm_want));
    assign busy = r_busy | pm_pending | ppu_busy | core_req_valid | host_busy | (USE_KS == 2 && ks_busy);

    assign lnk_in_full   = r_in_full[3:0];
    assign ext_in_full   = r_in_full[`P_EXT];
    assign lnk_out_valid = r_out_valid[3:0];
    assign lnk_out_data  = r_out_data[4*`MSG_W-1:0];
    assign ext_out_valid = r_out_valid[`P_EXT];
    assign ext_out_data  = r_out_data[`P_EXT*`MSG_W +: `MSG_W];
    wire               core_out_ks = r_out_data[`P_CORE*`MSG_W + 48 +: 4] == 4'd15;   // step 15 = keystream word
    wire               core_resp_valid = r_out_valid[`P_CORE] && !core_out_ks;
    assign nr_valid = r_out_valid[`P_CORE] && core_out_ks;
    wire [`MSG_W-1:0]  core_resp_msg   = r_out_data[`P_CORE*`MSG_W +: `MSG_W];

    wire core_set = mem_valid && !mem_ready && region == 4'h3 && |mem_wstrb;
    wire [AW-1:0] core_set_idx = pm_index(mem_addr[9:2], mem_addr[19:12], mem_addr[23:20]);

    pixel_memory #(.XINIT(XINIT), .YINIT(YINIT), .TW(TW), .TH(TH), .NSTEP(NSTEP), .AW(AW)) u_pm (
        .clk(clk), .rst(rst),
        .a_we(ppu_we | core_set), .a_idx(ppu_we ? ppu_w_idx : core_set_idx),
        .a_data(ppu_we ? ppu_w_data : mem_wdata[15:0]),
        .rd_en(ppu_rd_en | byp_rd), .rd_idx(ppu_rd_en ? ppu_rd_idx : pm_index(gp_x, gp_y, gp_s)),
        .rd_data(pm_rd_data), .block_b(1'b0),
        .b_valid(r_out_valid[`P_PM] && !to_host), .b_msg(pm_out_msg),
        .resp_afull(r_in_afull[`P_PM]), .b_full(pm_full),
        .resp_valid(pm_resp_valid), .resp_msg(pm_resp_msg), .pending(pm_pending));

    // ---------------- bus ----------------
    assign mem_ready = ram_ready | mmio_ready | (byp_pend & mem_valid);
    assign mem_rdata = (region == 4'h0) ? ram_q :
                       byp_pend ? {{16{pm_rd_data[15]}}, pm_rd_data} : mmio_rdata;

    reg get_sent;
    always @(posedge clk) begin
        mmio_ready     <= 0;
        core_req_valid <= 0;
        mark_valid     <= 0;
        ppu_start      <= 0;
        if (rst || !cpu_resetn) begin
            ram_pend <= 0; ram_pend2 <= 0; get_sent <= 0; byp_pend <= 0;
            bar_arrived <= 0; done <= 0; ppu_started <= 0;
        end else begin
            ram_pend  <= !FAST_CORE && ram_access && !ram_pend && !ram_pend2 && !mem_ready;
            ram_pend2 <= ram_pend;
            byp_pend <= byp_rd;
            if (mem_valid && !mem_ready && !mmio_ready && region != 4'h0 && !byp_rd && !byp_pend) begin
                case (region)
                    4'h2: begin                               // get_pixel through the NoC
                        if (!get_sent) begin
                            get_sent <= 1;
                            core_req_valid <= 1;
                            core_req_msg <= 0;
                            core_req_msg[`F_TX]    <= gp_x;
                            core_req_msg[`F_TY]    <= gp_y;
                            core_req_msg[`F_STEP]  <= gp_s;
                            core_req_msg[`F_FRAME] <= mem_addr[27:24];
                            core_req_msg[`F_OX]    <= XINIT;
                            core_req_msg[`F_OY]    <= YINIT;
                            core_req_msg[`F_TYPE]  <= `T_REQ;
                        end else if (core_resp_valid) begin
                            get_sent   <= 0;
                            mmio_ready <= 1;
                            mmio_rdata <= {{16{core_resp_msg[15]}}, core_resp_msg[15:0]};
                        end
                    end
                    4'h3: mmio_ready <= 1;
                    4'h4: begin
                        if (!bar_arrived) bar_arrived <= 1;
                        else if (bar_all) begin bar_arrived <= 0; mmio_ready <= 1; end
                    end
                    4'h5: begin mark_valid <= 1; mark_data <= mem_wdata; mmio_ready <= 1; end
                    4'h6: begin done <= 1; mmio_ready <= 1; end
                    4'h7: begin
                        mmio_ready <= 1;
                        case (mem_addr[5:2])
                            4'd0: mmio_rdata <= XINIT;
                            4'd1: mmio_rdata <= YINIT;
                            4'd2: mmio_rdata <= TW;
                            4'd3: mmio_rdata <= TH;
                            4'd4: mmio_rdata <= IMG_W;
                            4'd5: mmio_rdata <= IMG_H;
                            4'd6: mmio_rdata <= N;
                            4'd8: mmio_rdata <= PART_ALIGN;
                            default: mmio_rdata <= TILE_ID;
                        endcase
                    end
                    4'h8: begin
                        if (|mem_wstrb && mem_addr[6:2] == 5'd16) begin   // CTRL: start + wait
                            if (!ppu_started) begin ppu_started <= 1; ppu_start <= 1; end
                            else if (ppu_done) begin ppu_started <= 0; mmio_ready <= 1; end
                        end else begin
                            mmio_ready <= 1;
                            mmio_rdata <= ppu_sum;
                        end
                    end
                    4'h9: begin mmio_ready <= 1; mmio_rdata <= ks_blocks; end   // keystream unit
                    default: begin mmio_ready <= 1; mmio_rdata <= 0; end
                endcase
            end
        end
    end

`ifdef PROFILE
    // stall accounting for bottleneck analysis
    reg [31:0] c_total, c_fetch_wait, c_get_wait, c_gets, c_instr, c_bar, c_flits, c_ksflits;
    wire [2:0] nflit = lnk_out_valid[0] + lnk_out_valid[1] + lnk_out_valid[2] + lnk_out_valid[3];
    reg [2:0]  nks;
    integer fi;
    always @* begin
        nks = 0;
        for (fi = 0; fi < 4; fi = fi + 1)
            if (lnk_out_valid[fi] && lnk_out_data[fi*`MSG_W + 48 +: 4] == 4'd15) nks = nks + 1;
    end
    always @(posedge clk) begin
        if (!cpu_resetn) begin
            c_total <= 0; c_fetch_wait <= 0; c_get_wait <= 0; c_gets <= 0; c_instr <= 0; c_bar <= 0;
            c_flits <= 0; c_ksflits <= 0;
        end else if (!done) begin
            c_flits <= c_flits + nflit;          // messages leaving this router on mesh links
            c_ksflits <= c_ksflits + nks;        // ... of which keystream traffic (step 15)
            c_total <= c_total + 1;
            if (mem_valid && !mem_ready && region == 4'h0) c_fetch_wait <= c_fetch_wait + 1;
            if (mem_valid && !mem_ready && region == 4'h2) c_get_wait <= c_get_wait + 1;
            if (mem_valid && mem_ready && region == 4'h2) c_gets <= c_gets + 1;
            if (mem_valid && mem_ready && mem_instr) c_instr <= c_instr + 1;
            if (mem_valid && !mem_ready && region == 4'h4) c_bar <= c_bar + 1;
        end
    end
    reg done_d;
    always @(posedge clk) begin
        done_d <= done;
        if (done && !done_d)
            $display("PROFILE tile %0d: cycles %0d instr %0d CPI %0.2f ram_wait %0d gets %0d get_wait %0d (%.1f cyc/get) barrier %0d link_flits %0d ks_flits %0d ks_blocks %0d",
                TILE_ID, c_total, c_instr, 1.0 * c_total / c_instr, c_fetch_wait, c_gets, c_get_wait,
                1.0 * c_get_wait / (c_gets + (c_gets == 0)), c_bar, c_flits, c_ksflits, ks_blocks);
    end
`endif
endmodule
