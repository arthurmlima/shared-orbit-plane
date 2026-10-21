// Per-tile Trivium keystream unit (KS_IMPL = 6), same configuration port and take/hit/byte interface
// as the ChaCha unit (ks_unit2) and the orbit-plane unit (lbe_dist). Reference: ref/tile_streams.py.
//
// One sequential stream per tile, position-independent like the orbit plane: byte j of a pass encrypts
// the tile's j-th pixel in the PPU's raster sweep; every start (cfg word 15) restarts the stream.
// Key/IV mapping (track E_baselines decision):
//   Trivium key = bytes 0..9 of the 256-bit key (key words 0..7 little-endian, as for ChaCha), i.e.
//                 the first 80 key bits; key bits 80..255 are unused.
//   Trivium IV  = nonce bytes 0..8 (nonce bits 0..71) || TILE_ID (IV byte 9); nonce bits 72..95 unused.
//   eSTREAM byte convention: byte p bit k -> K_{80-8p-k} (resp. IV), so the 80-bit port vector is the
//   bit reversal of the little-endian 80-bit integer.
// Timing: the start cycle loads the state, then INIT = 1152 / P cycles of initialisation; afterwards
// hit = 1 permanently (the next byte is a function of the state register) and every take advances P
// steps. No FIFO is needed. bytes_made counts bytes taken (statistics, read by the core).
module trivium_unit #(
    parameter TILE_ID = 0,
    parameter P = 8
) (
    input             clk, rst,
    input             cfg_we,
    input  [3:0]      cfg_addr,        // 0..7 key words, 8..10 nonce words, 15 = start
    input  [31:0]     cfg_wdata,
    input             take,
    output            hit,
    output [7:0]      ks_byte,
    output reg [31:0] bytes_made
);
    localparam INIT = 1152 / P;

    // only the bits that are used are stored, in flip-flops: key bits 0..79, nonce bits 0..71
    // (an 11-word register array was mapped to multi-port LUTRAM by Yosys: 120 LUTs; see synth/v0_kwarray)
    reg [79:0] k80;
    reg [71:0] n72;
    wire start = cfg_we && cfg_addr == 4'd15;
    always @(posedge clk) if (cfg_we) begin
        case (cfg_addr)
            4'd0:  k80[31:0]  <= cfg_wdata;
            4'd1:  k80[63:32] <= cfg_wdata;
            4'd2:  k80[79:64] <= cfg_wdata[15:0];
            4'd8:  n72[31:0]  <= cfg_wdata;
            4'd9:  n72[63:32] <= cfg_wdata;
            4'd10: n72[71:64] <= cfg_wdata[7:0];
            default: ;
        endcase
    end

    function [79:0] rev80; input [79:0] a; integer i;
        begin for (i = 0; i < 80; i = i + 1) rev80[i] = a[79 - i]; end
    endfunction
    wire [79:0] key_le = k80;
    wire [7:0]  tid = TILE_ID;
    wire [79:0] iv_le  = {tid, n72};

    reg        ready;
    reg [10:0] cnt;
    wire       adv = !ready ? (cnt != 0) : (take && ready);
    wire [P-1:0] z;
    trivium_core #(.P(P)) u_core (.clk(clk), .load(start), .key(rev80(key_le)), .iv(rev80(iv_le)),
                                  .step(adv && !start), .z(z));
    assign hit = ready;
    assign ks_byte = z[7:0];

    always @(posedge clk) begin
        if (rst) begin
            ready <= 0; cnt <= 0; bytes_made <= 0;
        end else if (start) begin
            ready <= 0; cnt <= INIT;
        end else begin
            if (!ready && cnt != 0) begin
                cnt <= cnt - 1'b1;
                if (cnt == 1) ready <= 1;
            end
            if (take && ready) bytes_made <= bytes_made + 1'b1;
        end
    end
endmodule
