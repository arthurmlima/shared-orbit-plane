// Iterative ChaCha block function (RFC 8439 state layout: 32-bit counter, 96-bit nonce).
//   ROUNDS : 8, 12 or 20
//   QR     : quarter-round units working in parallel (1, 2 or 4)
// Latency from start to done = 1 + ROUNDS * 4 / QR + 1 cycles; one 64-byte block per call.
// Output byte k of the block is blk[8k+7:8k] (little-endian words, as in the RFC).
module chacha_core #(
    parameter ROUNDS = 20,
    parameter QR = 4,
    parameter STREAM = 0        // 1: no 512-bit output register; the block is emitted as 16 words
) (
    input              clk, rst,
    input      [255:0] key,
    input      [95:0]  nonce,
    input      [31:0]  counter,
    input              start,
    output             busy,
    output reg         done,
    output reg [511:0] blk,
    // STREAM = 1: word i of the block on ow_data when ow_valid (i = ow_idx), 16 cycles;
    // key, nonce and counter must stay stable until done.
    output             ow_valid,
    output     [3:0]   ow_idx,
    output     [31:0]  ow_data
);
    localparam SUB = 4 / QR;                    // cycles per round
    localparam STEPS = ROUNDS * SUB;

    reg [31:0] x [0:15];                        // input words (kept for the final add)
    reg [31:0] s [0:15];                        // working state
    reg [9:0]  step;
    reg        run, fin, emit;
    reg [3:0]  e;
    assign busy = run | fin | emit;
    // STREAM: input words recomputed from the (stable) inputs instead of being stored
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
    assign ow_valid = STREAM && emit;
    assign ow_idx = e;
    assign ow_data = s[e] + xin(e);

    function [31:0] rotl; input [31:0] v; input integer c;
        rotl = (v << c) | (v >> (32 - c));
    endfunction

    // one round step: QR quarter-rounds selected by (round parity, sub-step)
    integer j, q, ia, ib, ic, id;
    reg [31:0] n [0:15];
    reg [31:0] a, b, c, d;
    wire odd = (step / SUB) % 2;                // 0: column round, 1: diagonal round
    wire [9:0] sub = step % SUB;
    always @* begin
        for (j = 0; j < 16; j = j + 1) n[j] = s[j];
        for (j = 0; j < QR; j = j + 1) begin
            q = sub * QR + j;
            ia = q;
            ib = odd ? 4 + ((q + 1) % 4) : q + 4;
            ic = odd ? 8 + ((q + 2) % 4) : q + 8;
            id = odd ? 12 + ((q + 3) % 4) : q + 12;
            a = s[ia]; b = s[ib]; c = s[ic]; d = s[id];
            a = a + b; d = rotl(d ^ a, 16);
            c = c + d; b = rotl(b ^ c, 12);
            a = a + b; d = rotl(d ^ a, 8);
            c = c + d; b = rotl(b ^ c, 7);
            n[ia] = a; n[ib] = b; n[ic] = c; n[id] = d;
        end
    end

    integer k;
    always @(posedge clk) begin
        done <= 0;
        if (rst) begin
            run <= 0; fin <= 0; step <= 0; emit <= 0;
        end else if (start && !busy) begin
            x[0] <= 32'h61707865; x[1] <= 32'h3320646e; x[2] <= 32'h79622d32; x[3] <= 32'h6b206574;
            s[0] <= 32'h61707865; s[1] <= 32'h3320646e; s[2] <= 32'h79622d32; s[3] <= 32'h6b206574;
            for (k = 0; k < 8; k = k + 1) begin
                x[4 + k] <= key[32 * k +: 32];
                s[4 + k] <= key[32 * k +: 32];
            end
            x[12] <= counter; s[12] <= counter;
            for (k = 0; k < 3; k = k + 1) begin
                x[13 + k] <= nonce[32 * k +: 32];
                s[13 + k] <= nonce[32 * k +: 32];
            end
            step <= 0; run <= 1;
        end else if (run) begin
            for (k = 0; k < 16; k = k + 1) s[k] <= n[k];
            if (step == STEPS - 1) begin
                run <= 0;
                if (STREAM) begin emit <= 1; e <= 0; end else fin <= 1;
            end
            step <= step + 1'b1;
        end else if (emit) begin
            e <= e + 1'b1;
            if (e == 15) begin emit <= 0; done <= 1; end
        end else if (fin) begin
            for (k = 0; k < 16; k = k + 1) blk[32 * k +: 32] <= s[k] + x[k];
            fin <= 0; done <= 1;
        end
    end
endmodule
