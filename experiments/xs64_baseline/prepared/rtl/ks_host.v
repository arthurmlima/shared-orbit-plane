`include "mpriscv_defs.vh"
// Shared keystream generator (placement S-shared), attached to the central Tile's router.
// Tiles send one T_REQ per 64-byte block (step field = 15, data = block counter, origin =
// requesting Tile). The host computes the ChaCha block and returns it as 32 T_RESP
// messages of 16 bits each (step = 15, OX = word index), routed back hop by hop.
// The keystream therefore crosses the NoC links: the placement the security analysis warns about.
module ks_host #(
    parameter ROUNDS = 20, QR = 4, QDEPTH = 64
) (
    input                    clk, rst,
    input      [255:0]       key,
    input      [95:0]        nonce,
    // requests from the router (PM output port, step == 15)
    input                    req_valid,
    input  [`MSG_W-1:0]      req_msg,
    output                   req_full,
    // responses into the router (shares the PM input port)
    output                   resp_valid,
    output reg [`MSG_W-1:0]  resp_msg,
    input                    resp_ready,
    output                   busy,
    output reg [31:0]        blocks_made
);
    localparam QW = $clog2(QDEPTH);
    reg [15:0] q_ctr [0:QDEPTH-1];
    reg [7:0]  q_ox  [0:QDEPTH-1];
    reg [7:0]  q_oy  [0:QDEPTH-1];
    reg [QW-1:0] q_rp, q_wp;
    reg [QW:0]   q_cnt;
    assign req_full = q_cnt >= QDEPTH - 1;

    reg         c_start;
    wire        c_busy, c_done;
    wire [511:0] c_blk;
    reg [15:0]  c_ctr;
    reg [7:0]   c_ox, c_oy;
    chacha_core #(.ROUNDS(ROUNDS), .QR(QR)) u_core (
        .clk(clk), .rst(rst), .key(key), .nonce(nonce), .counter({16'd0, c_ctr}),
        .start(c_start), .busy(c_busy), .done(c_done), .blk(c_blk));

    reg         held;                      // a finished block waiting for the emitter
    reg         emit;                      // emitter active
    reg [511:0] e_blk;
    reg [7:0]   e_ox, e_oy;
    reg [4:0]   e_i;
    assign resp_valid = emit;
    always @* begin
        resp_msg = 0;
        resp_msg[`F_DATA]  = e_blk[16 * e_i +: 16];
        resp_msg[`F_TX]    = e_ox;
        resp_msg[`F_TY]    = e_oy;
        resp_msg[`F_OX]    = {3'd0, e_i};
        resp_msg[`F_STEP]  = 4'd15;
        resp_msg[`F_TYPE]  = `T_RESP;
        resp_msg[`F_OSINK] = 1'b0;
    end
    assign busy = q_cnt != 0 || c_busy || c_start || held || emit;

    wire push = req_valid && req_msg[`F_TYPE] == `T_REQ;
    wire pop  = !c_busy && !c_start && !c_done && !held && q_cnt != 0;   // keep c_ox until handed off
    always @(posedge clk) begin
        c_start <= 0;
        if (rst) begin
            q_rp <= 0; q_wp <= 0; q_cnt <= 0; held <= 0; emit <= 0; blocks_made <= 0;
        end else begin
            if (push) begin
                q_ctr[q_wp] <= req_msg[`F_DATA];
                q_ox[q_wp] <= req_msg[`F_OX];
                q_oy[q_wp] <= req_msg[`F_OY];
                q_wp <= q_wp + 1'b1;
            end
            if (pop) begin
                c_ctr <= q_ctr[q_rp]; c_ox <= q_ox[q_rp]; c_oy <= q_oy[q_rp];
                c_start <= 1; q_rp <= q_rp + 1'b1;
            end
            q_cnt <= q_cnt + push - pop;
            if (c_done) begin held <= 1; blocks_made <= blocks_made + 1; end
            // hand the finished block to the emitter (frees the core for the next block)
            if ((held || c_done) && (!emit || (resp_ready && e_i == 31))) begin
                held <= 0; emit <= 1; e_blk <= c_blk; e_ox <= c_ox; e_oy <= c_oy; e_i <= 0;
            end else if (emit && resp_ready) begin
                if (e_i == 31) emit <= 0;
                e_i <= e_i + 1'b1;
            end
        end
    end
endmodule
