// Trivium keystream generator core (De Canniere & Preneel; eSTREAM portfolio), P steps per cycle.
// Bit-exact reference: mcsoc2027/tracks/E_baselines/ref/trivium_ref.py.
//   state s[i-1] = s_i (i = 1..288); key[i-1] = K_i, iv[i-1] = IV_i (spec order; the eSTREAM byte
//   convention, key byte p bit k = K_{80-8p-k}, is applied by the caller, see trivium_unit.v).
//   load : (s1..s93) = (K1..K80, 0..0), (s94..s177) = (IV1..IV80, 0..0), (s178..s288) = (0..0, 1, 1, 1)
//   step : P cipher steps; z[j] is the output bit of the j-th of the next P steps (z[0] first), so
//          with P = 8 one keystream byte (LSB first, eSTREAM packing) is z.
// The newest bit enters s1/s94/s178 and is read again at s66 at the earliest, so up to 64 steps per cycle
// are computed from the registered state with one logic level (no chaining); P = 8 here.
// Initialisation (4 x 288 = 1152 steps) is sequenced by the caller: 1152 / P cycles of `step`.
module trivium_core #(
    parameter P = 8
) (
    input              clk,
    input              load,
    input      [79:0]  key,
    input      [79:0]  iv,
    input              step,
    output     [P-1:0] z
);
    reg [287:0] s;

    // P sequential single steps; the loop unrolls into P independent update functions
    function [288+P-1:0] adv; input [287:0] st;
        integer j; reg [287:0] x; reg t1, t2, t3; reg [P-1:0] zz;
        begin
            x = st;
            for (j = 0; j < P; j = j + 1) begin
                t1 = x[65] ^ x[92];
                t2 = x[161] ^ x[176];
                t3 = x[242] ^ x[287];
                zz[j] = t1 ^ t2 ^ t3;
                t1 = t1 ^ (x[90] & x[91]) ^ x[170];
                t2 = t2 ^ (x[174] & x[175]) ^ x[263];
                t3 = t3 ^ (x[285] & x[286]) ^ x[68];
                x = {x[286:177], t2, x[175:93], t1, x[91:0], t3};
            end
            adv = {zz, x};
        end
    endfunction

    wire [288+P-1:0] nx = adv(s);
    assign z = nx[288 +: P];

    always @(posedge clk) begin
        if (load) s <= {3'b111, 108'd0, 4'd0, iv, 13'd0, key};
        else if (step) s <= nx[287:0];
    end
endmodule
