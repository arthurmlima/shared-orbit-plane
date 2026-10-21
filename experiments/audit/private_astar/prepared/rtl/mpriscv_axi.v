`include "mpriscv_defs.vh"
// AXI4-Lite wrapper so the Zynq UltraScale+ PS (Cortex-A53) can drive MPRISC-V.
// Register map (byte offsets, 32-bit registers):
//   0x00 CTRL      [0] mesh reset (1 = held in reset)  [1] cpu_resetn (1 = cores run)
//   0x04 STATUS    [0] all_done [1] noc_busy [2] ext_in_full [3] out FIFO not empty [4] out FIFO overflow
//   0x08 PROG_ADDR byte address in the Tiles' program RAM
//   0x0C PROG_DATA write = broadcast one program word to every Tile
//   0x10 EXT_IN_LO message bits [31:0]
//   0x14 EXT_IN_HI message bits [58:32]; write = inject the message at the central Tile
//   0x18 EXT_OUT_LO head of the response FIFO, bits [31:0]
//   0x1C EXT_OUT_HI head bits [58:32]; read = pop
//   0x20 CYCLES_LO / 0x24 CYCLES_HI  cycles from cpu_resetn rising to all_done
//   0x28 OUT_COUNT number of messages in the response FIFO
//   0x2C INFO      [7:0] N, [15:8] placement (0 none, 1 S-local, 2 S-shared, 3 S-row), [31:16] IMG_W
module mpriscv_axi #(
    parameter N = 3, IMG_W = 120, IMG_H = 120,
    parameter FAST_CORE = 1, PM_BYPASS = 1, USE_PPU = 2,
    parameter USE_KS = 1, KS_ROUNDS = 20, KS_QR = 4, KS_GEOM = 1, KS_IMPL = 3, KS_ROWHOST = 0,
    parameter LBE_K = 4, LBE_T = 64,     // KS_IMPL = 4: orbits per tile and transient per block; 5: transient per pass
    parameter LBE_LEAN = 0, LBE_PERT = 0, PLANE_REG = 0, ORB_REG = 0, ORB_MID = 0,   // orbit-plane variants
    parameter ORB_PRIVATE = 0,            // retains the mesh's collective advance
    parameter LBE_EXT = 0,               // orbit-plane byte extractor (lbe_ext.vh)
    parameter OUT_DEPTH = 1024
) (
    input             s_axi_aclk,
    input             s_axi_aresetn,
    input      [7:0]  s_axi_awaddr,
    input             s_axi_awvalid,
    output reg        s_axi_awready,
    input      [31:0] s_axi_wdata,
    input      [3:0]  s_axi_wstrb,
    input             s_axi_wvalid,
    output reg        s_axi_wready,
    output     [1:0]  s_axi_bresp,
    output reg        s_axi_bvalid,
    input             s_axi_bready,
    input      [7:0]  s_axi_araddr,
    input             s_axi_arvalid,
    output reg        s_axi_arready,
    output reg [31:0] s_axi_rdata,
    output     [1:0]  s_axi_rresp,
    output reg        s_axi_rvalid,
    input             s_axi_rready
);
    wire clk = s_axi_aclk;
    assign s_axi_bresp = 2'b00;
    assign s_axi_rresp = 2'b00;

    // ---------------- control registers ----------------
    reg        mesh_rst, cpu_resetn;
    reg [31:0] prog_addr, prog_data, in_lo;
    reg        prog_we, in_push;
    reg [`MSG_W-1:0] in_msg;
    wire       all_done, noc_busy, ext_in_full, ext_out_valid;
    wire [`MSG_W-1:0] ext_out_data;

    mpriscv #(.N(N), .IMG_W(IMG_W), .IMG_H(IMG_H), .FAST_CORE(FAST_CORE), .PM_BYPASS(PM_BYPASS),
              .USE_PPU(USE_PPU), .USE_KS(USE_KS), .KS_ROUNDS(KS_ROUNDS), .KS_QR(KS_QR),
              .KS_GEOM(KS_GEOM), .KS_IMPL(KS_IMPL), .KS_ROWHOST(KS_ROWHOST), .LBE_K(LBE_K), .LBE_T(LBE_T),
              .LBE_LEAN(LBE_LEAN), .LBE_PERT(LBE_PERT), .PLANE_REG(PLANE_REG), .ORB_REG(ORB_REG), .ORB_MID(ORB_MID), .ORB_PRIVATE(ORB_PRIVATE), .LBE_EXT(LBE_EXT)) u_mesh (
        .clk(clk), .rst(mesh_rst), .cpu_resetn(cpu_resetn),
        .prog_we(prog_we), .prog_addr(prog_addr), .prog_data(prog_data),
        .ext_in_valid(in_push), .ext_in_data(in_msg), .ext_in_full(ext_in_full),
        .ext_out_valid(ext_out_valid), .ext_out_data(ext_out_data),
        .all_done(all_done), .noc_busy(noc_busy), .mark_valid(), .mark_data());

    // ---------------- response FIFO (the EXT port never back-pressures) ----------------
    localparam OW = $clog2(OUT_DEPTH);
    reg [`MSG_W-1:0] ofifo [0:OUT_DEPTH-1];
    reg [OW-1:0] o_rp, o_wp;
    reg [OW:0]   o_cnt;
    reg          o_ovf;
    reg          o_pop;
    wire [`MSG_W-1:0] o_head = ofifo[o_rp];
    always @(posedge clk) begin
        if (!s_axi_aresetn) begin o_rp <= 0; o_wp <= 0; o_cnt <= 0; o_ovf <= 0; end
        else begin
            if (ext_out_valid) begin
                if (o_cnt == OUT_DEPTH) o_ovf <= 1;
                else begin ofifo[o_wp] <= ext_out_data; o_wp <= o_wp + 1'b1; end
            end
            if (o_pop && o_cnt != 0) o_rp <= o_rp + 1'b1;
            o_cnt <= o_cnt + (ext_out_valid && o_cnt != OUT_DEPTH) - (o_pop && o_cnt != 0);
        end
    end

    // ---------------- cycle counter ----------------
    reg [63:0] cycles;
    always @(posedge clk) begin
        if (!cpu_resetn) cycles <= 0;
        else if (!all_done) cycles <= cycles + 1;
    end

    // ---------------- AXI4-Lite write channel ----------------
    reg [7:0] aw;
    reg       aw_ok, w_ok;
    reg [31:0] wd;
    always @(posedge clk) begin
        prog_we <= 0; in_push <= 0;
        if (!s_axi_aresetn) begin
            s_axi_awready <= 0; s_axi_wready <= 0; s_axi_bvalid <= 0; aw_ok <= 0; w_ok <= 0;
            mesh_rst <= 1; cpu_resetn <= 0;
        end else begin
            s_axi_awready <= !aw_ok && s_axi_awvalid && !s_axi_awready;
            s_axi_wready  <= !w_ok && s_axi_wvalid && !s_axi_wready;
            if (s_axi_awvalid && s_axi_awready) begin aw <= s_axi_awaddr; aw_ok <= 1; end
            if (s_axi_wvalid && s_axi_wready) begin wd <= s_axi_wdata; w_ok <= 1; end
            if (aw_ok && w_ok && !s_axi_bvalid) begin
                case (aw[7:2])
                    6'h00: begin mesh_rst <= wd[0]; cpu_resetn <= wd[1]; end
                    6'h02: prog_addr <= wd;
                    6'h03: begin prog_data <= wd; prog_we <= 1; end
                    6'h04: in_lo <= wd;
                    6'h05: begin in_msg <= {wd[`MSG_W-33:0], in_lo}; in_push <= 1; end
                    default: ;
                endcase
                s_axi_bvalid <= 1; aw_ok <= 0; w_ok <= 0;
            end
            if (s_axi_bvalid && s_axi_bready) s_axi_bvalid <= 0;
        end
    end

    // ---------------- AXI4-Lite read channel ----------------
    always @(posedge clk) begin
        o_pop <= 0;
        if (!s_axi_aresetn) begin s_axi_arready <= 0; s_axi_rvalid <= 0; end
        else begin
            s_axi_arready <= s_axi_arvalid && !s_axi_arready && !s_axi_rvalid;
            if (s_axi_arvalid && s_axi_arready) begin
                s_axi_rvalid <= 1;
                case (s_axi_araddr[7:2])
                    6'h00: s_axi_rdata <= {30'd0, cpu_resetn, mesh_rst};
                    6'h01: s_axi_rdata <= {27'd0, o_ovf, o_cnt != 0, ext_in_full, noc_busy, all_done};
                    6'h02: s_axi_rdata <= prog_addr;
                    6'h06: s_axi_rdata <= o_head[31:0];
                    6'h07: begin s_axi_rdata <= {{(64 - `MSG_W){1'b0}}, o_head[`MSG_W-1:32]}; o_pop <= 1; end
                    6'h08: s_axi_rdata <= cycles[31:0];
                    6'h09: s_axi_rdata <= cycles[63:32];
                    6'h0A: s_axi_rdata <= o_cnt;
                    6'h0B: s_axi_rdata <= {IMG_W[15:0], USE_KS[7:0] + (KS_ROWHOST ? 8'd1 : 8'd0), N[7:0]};
                    default: s_axi_rdata <= 32'hdeadbeef;
                endcase
            end
            if (s_axi_rvalid && s_axi_rready) s_axi_rvalid <= 0;
        end
    end
endmodule
