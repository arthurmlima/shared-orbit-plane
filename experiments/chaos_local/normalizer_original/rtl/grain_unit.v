// Per-tile Grain-128AEADv2 keystream unit (KS_IMPL = 7), same configuration port and take/hit/byte
// interface as trivium_unit / ks_unit2 / lbe_dist. Keystream mode only: no authentication (the AEAD
// accumulator and shift register are not implemented, no tag). Reference: ref/grain_ref.py.
//   P = 16, Z = 1 (headline "G16z"): 16 pre-output clocks per cycle; the byte is the 8 even pre-output
//       bits = 8 bits of the AEADv2 encryption keystream z_i = y_{512+2i} per cycle (bit i = z_{8m+i}).
//   P = 8,  Z = 0 ("G8y"): 8 pre-output clocks per cycle; the byte is all 8 pre-output bits y_{512+8m+i}.
//       This is NOT the AEADv2 encryption keystream (which would give 4 bits per cycle at P = 8).
// Key/IV mapping (track decision, by analogy with trivium_unit): key = bytes 0..15 of the 256-bit key,
// IV = nonce bytes 0..10 || TILE_ID (IV byte 11); bytes are read LSB first (k_{8p+j} = bit j of byte p).
// Timing: start cycle loads, then 512 / P initialisation cycles (320/P with y feedback, 64/P with y
// feedback and the key re-introduced, 128/P plain), then hit = 1 and every take advances P clocks.
module grain_unit #(
    parameter TILE_ID = 0,
    parameter P = 16,
    parameter Z = 1
) (
    input             clk, rst,
    input             cfg_we,
    input  [3:0]      cfg_addr,
    input  [31:0]     cfg_wdata,
    input             take,
    output            hit,
    output [7:0]      ks_byte,
    output reg [31:0] bytes_made
`ifdef GRAIN_DBG
    , output [127:0] dbg_nf, output [127:0] dbg_lf
`endif
);
    localparam C1 = 320 / P, C2 = 64 / P, NI = 512 / P;

    // only the bits that are used are stored, in flip-flops: key bits 0..127, nonce bits 0..87
    reg [127:0] key;
    reg [87:0]  n88;
    wire start = cfg_we && cfg_addr == 4'd15;
    always @(posedge clk) if (cfg_we) begin
        case (cfg_addr)
            4'd0:  key[31:0]   <= cfg_wdata;
            4'd1:  key[63:32]  <= cfg_wdata;
            4'd2:  key[95:64]  <= cfg_wdata;
            4'd3:  key[127:96] <= cfg_wdata;
            4'd8:  n88[31:0]   <= cfg_wdata;
            4'd9:  n88[63:32]  <= cfg_wdata;
            4'd10: n88[87:64]  <= cfg_wdata[23:0];
            default: ;
        endcase
    end
    wire [7:0]   tid = TILE_ID;
    wire [95:0]  iv  = {tid, n88};

    reg        ready, busy;
    reg [7:0]  ic;                               // initialisation cycle 0 .. NI-1
    wire [1:0] mode = !busy ? 2'd0 : (ic < C1) ? 2'd1 : (ic < C1 + C2) ? 2'd2 : 2'd0;
    wire [7:0] kc = ic - C1;                     // key slice index during mode 2
    wire [P-1:0] kn = key >> (kc * P);           // k_{t-320} for the P clocks of this cycle
    wire [P-1:0] kl = key >> (64 + kc * P);      // k_{t-256}
    wire [P-1:0] y;
    wire       adv = (busy || (take && ready)) && !start;
    grain_core #(.P(P)) u_core (.clk(clk), .load(start), .key(key), .iv(iv), .adv(adv), .mode(mode),
                                .kn(kn), .kl(kl), .y(y)
`ifdef GRAIN_DBG
                                , .dbg_nf(dbg_nf), .dbg_lf(dbg_lf)
`endif
                                );
    assign hit = ready;
    genvar i;
    generate for (i = 0; i < 8; i = i + 1) begin : g_b
        assign ks_byte[i] = Z ? y[2 * i] : y[i];
    end endgenerate

    always @(posedge clk) begin
        if (rst) begin
            ready <= 0; busy <= 0; ic <= 0; bytes_made <= 0;
        end else if (start) begin
            ready <= 0; busy <= 1; ic <= 0;
        end else begin
            if (busy) begin
                ic <= ic + 1'b1;
                if (ic == NI - 1) begin busy <= 0; ready <= 1; end
            end
            if (take && ready) bytes_made <= bytes_made + 1'b1;
        end
    end
endmodule
