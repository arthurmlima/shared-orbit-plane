// Grain-128AEADv2 pre-output generator (LFSR + NFSR + pre-output function), P clocks per cycle.
// Keystream mode only: the accumulator and shift register of the authenticator are NOT implemented,
// so no tag is produced. Bit-exact reference: mcsoc2027/tracks/E_baselines/ref/grain_ref.py.
//   nf[i] = b_{t+i}, lf[i] = s_{t+i} (i = 0..127); key[i] = k_i, iv[i] = IV_i.
//   load : b_i = k_i, s_i = IV_i (i < 96), s_96..s_126 = 1, s_127 = 0
//   adv  : P clocks in the given mode; y[j] = pre-output y of the j-th clock (y[0] first)
//     mode 1 (t = 0..319)   : y fed back into LFSR and NFSR
//     mode 2 (t = 320..383) : y fed back and key re-introduced, kl[j] = k_{t+j-256} into the LFSR,
//                             kn[j] = k_{t+j-320} into the NFSR
//     mode 0 (t >= 384)     : no feedback of y (t = 384..511 fill acc/register in AEAD, discarded here)
// New bits enter at index 127 and the highest tap is 96, so up to 32 clocks per cycle are computed from
// the registered state with no chaining; P = 8 or 16 here.
module grain_core #(
    parameter P = 16
) (
    input              clk,
    input              load,
    input      [127:0] key,
    input      [95:0]  iv,
    input              adv,
    input      [1:0]   mode,
    input      [P-1:0] kn,
    input      [P-1:0] kl,
    output     [P-1:0] y
`ifdef GRAIN_DBG
    , output [127:0] dbg_nf, output [127:0] dbg_lf      // testbench only (state check vs the spec)
`endif
);
    reg [127:0] nf;
    reg [127:0] lf;
`ifdef GRAIN_DBG
    assign dbg_nf = nf;
    assign dbg_lf = lf;
`endif

    function [256+P-1:0] clk_p; input [127:0] b0; input [127:0] s0; input [1:0] md;
        input [P-1:0] knv; input [P-1:0] klv;
        integer j; reg [127:0] b, s; reg h, yy, fl, fn, fb; reg [P-1:0] yv;
        begin
            b = b0; s = s0;
            for (j = 0; j < P; j = j + 1) begin
                h = (b[12] & s[8]) ^ (s[13] & s[20]) ^ (b[95] & s[42]) ^ (s[60] & s[79]) ^ (b[12] & b[95] & s[94]);
                yy = h ^ s[93] ^ b[2] ^ b[15] ^ b[36] ^ b[45] ^ b[64] ^ b[73] ^ b[89];
                yv[j] = yy;
                fl = s[0] ^ s[7] ^ s[38] ^ s[70] ^ s[81] ^ s[96];
                fn = s[0] ^ b[0] ^ b[26] ^ b[56] ^ b[91] ^ b[96] ^ (b[3] & b[67]) ^ (b[11] & b[13]) ^
                     (b[17] & b[18]) ^ (b[27] & b[59]) ^ (b[40] & b[48]) ^ (b[61] & b[65]) ^ (b[68] & b[84]) ^
                     (b[22] & b[24] & b[25]) ^ (b[70] & b[78] & b[82]) ^ (b[88] & b[92] & b[93] & b[95]);
                fb = (md != 2'd0) ? yy : 1'b0;
                s = {fl ^ fb ^ ((md == 2'd2) ? klv[j] : 1'b0), s[127:1]};
                b = {fn ^ fb ^ ((md == 2'd2) ? knv[j] : 1'b0), b[127:1]};
            end
            clk_p = {yv, b, s};
        end
    endfunction

    wire [256+P-1:0] nx = clk_p(nf, lf, mode, kn, kl);
    assign y = nx[256 +: P];

    always @(posedge clk) begin
        if (load) begin
            nf <= key;
            lf <= {1'b0, 31'h7FFFFFFF, iv};
        end else if (adv) begin
            nf <= nx[255:128];
            lf <= nx[127:0];
        end
    end
endmodule
