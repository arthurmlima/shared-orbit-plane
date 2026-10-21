// Byte extractors of the orbit plane. Included inside module scope by lbe_dist.v and ext_bench.v,
// so that the RTL, the microbenchmark and the matched wrappers share one definition. Inputs a = R_y, b = C_x.
// EXT 0  lbe_byte   original normalized fold (verbatim from the baseline lbe_dist.v):
//                   D = |a - b|, n = D with its leading one at bit 31, byte = n[22:15] ^ n[30:23], 0 if D = 0
// EXT 1  ext_window fixed difference window: byte = D[15:8] (D = 0 gives 0 by itself)
// EXT 2  ext_xor    pairwise XOR: byte = (a ^ b)[15:8]
// EXT 3  ext_nwin   normalized window: byte = n[22:15], 0 if D = 0 (the normalizer without the fold)
function [7:0] lbe_byte; input [31:0] a; input [31:0] b;
    reg [31:0] d, n; integer i, lz; reg found;
    begin
        d = (a > b) ? a - b : b - a;
        lz = 0; found = 0;
        for (i = 31; i >= 0; i = i - 1)
            if (!found) begin if (d[i]) found = 1; else lz = lz + 1; end
        n = d << lz;
        lbe_byte = (d == 0) ? 8'd0 : n[22:15] ^ n[30:23];
    end
endfunction
function [7:0] ext_window; input [31:0] a; input [31:0] b;
    reg [31:0] d;
    begin
        d = (a > b) ? a - b : b - a;
        ext_window = d[15:8];
    end
endfunction
function [7:0] ext_xor; input [31:0] a; input [31:0] b;
    reg [31:0] x;
    begin
        x = a ^ b;
        ext_xor = x[15:8];
    end
endfunction
function [7:0] ext_nwin; input [31:0] a; input [31:0] b;
    reg [31:0] d, n; integer i, lz; reg found;
    begin
        d = (a > b) ? a - b : b - a;
        lz = 0; found = 0;
        for (i = 31; i >= 0; i = i - 1)
            if (!found) begin if (d[i]) found = 1; else lz = lz + 1; end
        n = d << lz;
        ext_nwin = (d == 0) ? 8'd0 : n[22:15];
    end
endfunction
function [7:0] ext_byte; input integer sel; input [31:0] a; input [31:0] b;
    begin
        case (sel)
            1: ext_byte = ext_window(a, b);
            2: ext_byte = ext_xor(a, b);
            3: ext_byte = ext_nwin(a, b);
            default: ext_byte = lbe_byte(a, b);
        endcase
    end
endfunction
