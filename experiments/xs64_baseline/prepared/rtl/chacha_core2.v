// Area-optimised iterative ChaCha block function (RFC 8439 state layout), streaming output.
// Same interface and output as chacha_core with STREAM = 1, without the 512-bit block port.
//
// Fixed quarter-round wiring: the QR units always work on state columns 0..QR-1, so their
// inputs and outputs are plain wires (no variable-index multiplexers). After every cycle each
// state row r is rotated left by a constant so the next columns move into place:
//   inside a half-round           : QR
//   last cycle of a column round  : QR + r   (diagonalise: diagonal i becomes column i)
//   last cycle of a diagonal round: QR - r   (undo it)
// so every state word sees at most three rotation choices, a load and a 1-word shift.
// The block is emitted in index order through a 16:1 word multiplexer (cheaper on an FPGA
// than giving all 512 state bits an extra shift input).
//   ROUNDS : 8, 12 or 20 (must be even)      QR : 1, 2 or 4 quarter-round units
// Latency from start to done = 1 + ROUNDS * 4 / QR + 16 cycles (same as chacha_core STREAM).
module chacha_core2 #(
    parameter ROUNDS = 20,
    parameter QR = 4
) (
    input              clk, rst,
    input      [255:0] key,
    input      [95:0]  nonce,
    input      [31:0]  counter,
    input              start,
    output             busy,
    output reg         done,
    // word i of the block on ow_data when ow_valid (i = ow_idx), 16 consecutive cycles;
    // key, nonce and counter must stay stable until done
    output             ow_valid,
    output     [3:0]   ow_idx,
    output     [31:0]  ow_data
);
    localparam SUB = 4 / QR;                    // cycles per half-round
    localparam STEPS = ROUNDS * SUB;

    // state as one flat vector: word i = st[32*i +: 32] (row i/4, column i%4). A reg array
    // with a variable-index read would be inferred as a memory with many write ports.
    reg [511:0] st;
    reg [6:0]  step;
    reg [1:0]  sub;
    reg        odd;                             // 0: column round, 1: diagonal round
    reg        run, emit;
    reg [3:0]  e;
    assign busy = run | emit;
    wire last_sub = sub == SUB - 1;

    // fixed rotations as plain rewiring (a rotate with an integer function argument can be
    // synthesised as a barrel shifter)
    function [31:0] r16; input [31:0] v; r16 = {v[15:0], v[31:16]}; endfunction
    function [31:0] r12; input [31:0] v; r12 = {v[19:0], v[31:20]}; endfunction
    function [31:0] r8;  input [31:0] v; r8  = {v[23:0], v[31:24]}; endfunction
    function [31:0] r7;  input [31:0] v; r7  = {v[24:0], v[31:25]}; endfunction

    // feed-forward input word i, recomputed from the (stable) inputs
    function [31:0] xin; input [3:0] i;
        case (i)
            0: xin = 32'h61707865; 1: xin = 32'h3320646e; 2: xin = 32'h79622d32; 3: xin = 32'h6b206574;
            12: xin = counter;
            13: xin = nonce[31:0]; 14: xin = nonce[63:32]; 15: xin = nonce[95:64];
            // constant part-selects: a variable one becomes a 256:1 multiplexer per bit
            4: xin = key[31:0];     5: xin = key[63:32];    6: xin = key[95:64];    7: xin = key[127:96];
            8: xin = key[159:128];  9: xin = key[191:160]; 10: xin = key[223:192]; default: xin = key[255:224];
        endcase
    endfunction

    // quarter-rounds on columns 0..QR-1 (constant indices only)
    reg [511:0] p;
    reg [31:0] a, b, c, d;
    integer j;
    always @* begin
        p = st;
        for (j = 0; j < QR; j = j + 1) begin
            a = st[32 * j +: 32]; b = st[32 * (4 + j) +: 32]; c = st[32 * (8 + j) +: 32]; d = st[32 * (12 + j) +: 32];
            a = a + b; d = r16(d ^ a);
            c = c + d; b = r12(b ^ c);
            a = a + b; d = r8(d ^ a);
            c = c + d; b = r7(b ^ c);
            p[32 * j +: 32] = a; p[32 * (4 + j) +: 32] = b; p[32 * (8 + j) +: 32] = c; p[32 * (12 + j) +: 32] = d;
        end
    end

    // next state after a round cycle: row r rotated left by QR (inside a half-round), QR + r (end
    // of a column round) or QR - r (end of a diagonal round). Where two choices pick the same
    // word the select is removed at elaboration, so rows 0 and 2 of the 4-QR core need none.
    wire [511:0] nxt;
    genvar gr, gk;
    generate for (gr = 0; gr < 4; gr = gr + 1) begin : g_r
        for (gk = 0; gk < 4; gk = gk + 1) begin : g_k
            localparam IM = 4 * gr + (gk + QR) % 4;
            localparam IC = 4 * gr + (gk + QR + gr) % 4;
            localparam ID = 4 * gr + (gk + QR + 4 - gr) % 4;
            wire [31:0] w_end;
            if (IC == ID) begin : g_same
                assign w_end = p[32 * IC +: 32];
            end else begin : g_sel
                assign w_end = odd ? p[32 * ID +: 32] : p[32 * IC +: 32];
            end
            if (SUB == 1 || IM == IC && IM == ID) begin : g_one
                assign nxt[32 * (4 * gr + gk) +: 32] = w_end;
            end else begin : g_two
                assign nxt[32 * (4 * gr + gk) +: 32] = last_sub ? w_end : p[32 * IM +: 32];
            end
        end
    end endgenerate

    // output: word e of the final state (16:1 multiplexer on 32 bits) plus the input word
    reg [31:0] wsel;
    always @* begin
        wsel = st[31:0];
        for (j = 1; j < 16; j = j + 1) if (e == j) wsel = st[32 * j +: 32];
    end
    assign ow_valid = emit;
    assign ow_idx = e;
    assign ow_data = wsel + xin(e);

    always @(posedge clk) begin
        done <= 0;
        if (rst) begin
            run <= 0; emit <= 0;
        end else if (start && !busy) begin
            st <= {nonce, counter, key, 32'h6b206574, 32'h79622d32, 32'h3320646e, 32'h61707865};
            step <= 0; sub <= 0; odd <= 0; run <= 1;
        end else if (run) begin
            st <= nxt;
            sub <= last_sub ? 2'd0 : sub + 1'b1;
            if (last_sub) odd <= ~odd;
            step <= step + 1'b1;
            if (step == STEPS - 1) begin run <= 0; emit <= 1; e <= 0; end
        end else if (emit) begin
            e <= e + 1'b1;
            if (e == 15) begin emit <= 0; done <= 1; end
        end
    end
endmodule
