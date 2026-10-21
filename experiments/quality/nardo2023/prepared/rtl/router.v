`include "mpriscv_defs.vh"
// MPRISC-V router: 7 buffered inputs (N,S,E,W,CORE,PM,EXT) -> 7 outputs.
// Routing is done on global pixel coordinates: a Tile owns the rectangle
// [XINIT, XINIT+TW) x [YINIT, YINIT+TH). Minimal XY routing; when a message
// needs to move in both dimensions the router toggles between X-first and
// Y-first to spread load. Messages that originate from / are destined to the
// local Tile (CORE/PM/EXT) win arbitration over pass-through traffic.
module router #(
    parameter XINIT = 0, YINIT = 0, TW = 8, TH = 8,
    parameter DEPTH = 4,
    parameter TOGGLE_XY = 1
) (
    input                          clk, rst,
    // input side (one per port)
    input  [`NPORTS-1:0]           in_valid,
    input  [`NPORTS*`MSG_W-1:0]    in_data,
    output [`NPORTS-1:0]           in_full,     // to upstream
    output [`NPORTS-1:0]           in_afull,
    // output side
    output reg [`NPORTS-1:0]       out_valid,
    output reg [`NPORTS*`MSG_W-1:0] out_data,
    input  [`NPORTS-1:0]           out_full,    // from downstream
    output                         busy,
    output reg                     pm_want   // some input head is destined to the PM
);
    wire [`MSG_W-1:0] head [0:`NPORTS-1];
    wire [`NPORTS-1:0] empty;
    reg  [`NPORTS-1:0] pop;

    genvar gi;
    generate for (gi = 0; gi < `NPORTS; gi = gi + 1) begin : g_in
        msg_fifo #(.DEPTH(DEPTH)) u_fifo (
            .clk(clk), .rst(rst),
            .push(in_valid[gi]), .din(in_data[gi*`MSG_W +: `MSG_W]),
            .pop(pop[gi]), .dout(head[gi]),
            .empty(empty[gi]), .full(in_full[gi]), .afull(in_afull[gi]));
    end endgenerate

    assign busy = ~&empty;

    reg toggle;   // 0: X first, 1: Y first

    // routing decision per input head
    function [2:0] route;
        input [`MSG_W-1:0] m;
        input              tg;
        reg [7:0] tx, ty;
        reg goW, goE, goN, goS;
        begin
            tx = m[`F_TX]; ty = m[`F_TY];
            goW = (tx < XINIT);
            goE = (tx >= XINIT + TW);
            goN = (ty < YINIT);
            goS = (ty >= YINIT + TH);
            if (!(goW|goE|goN|goS)) begin
                if (m[`F_TYPE] == `T_RESP) route = m[`F_OSINK] ? `P_EXT : `P_CORE;
                else                        route = `P_PM;
            end else if ((goW|goE) && (!(goN|goS) || !tg || !TOGGLE_XY))
                route = goW ? `P_W : `P_E;
            else
                route = goN ? `P_N : `P_S;
        end
    endfunction

    reg [2:0] want [0:`NPORTS-1];
    reg [2:0] rr   [0:`NPORTS-1];   // round-robin pointer per output
    reg [`NPORTS-1:0] req, hi, sel;
    reg [2:0] grant_in [0:`NPORTS-1];
    reg [`NPORTS-1:0] grant_ok;
    integer i, o, k, idx;
    reg found;
    reg any_choice;

    always @* begin
        for (i = 0; i < `NPORTS; i = i + 1) want[i] = route(head[i], toggle);
        pop = 0;
        out_valid = 0;
        out_data = 0;
        any_choice = 0;
        pm_want = 0;
        for (o = 0; o < `NPORTS; o = o + 1) begin
            grant_ok[o] = 0;
            grant_in[o] = 0;
            for (i = 0; i < `NPORTS; i = i + 1)
                req[i] = !empty[i] && (want[i] == o);
            if (o == `P_PM) pm_want = |req;
            // local-traffic priority: inputs from CORE/PM/EXT, or any message
            // that is delivered locally (o >= CORE)
            hi = req & 7'b1110000;
            sel = (o >= `P_CORE || hi == 0) ? req : hi;
            found = 0;
            for (k = 0; k < `NPORTS; k = k + 1) begin
                idx = rr[o] + k;
                if (idx >= `NPORTS) idx = idx - `NPORTS;
                if (!found && sel[idx]) begin
                    found = 1;
                    grant_in[o] = idx[2:0];
                end
            end
            if (found && !out_full[o]) begin
                grant_ok[o] = 1;
                pop[grant_in[o]] = 1'b1;
                out_valid[o] = 1'b1;
                out_data[o*`MSG_W +: `MSG_W] = head[grant_in[o]];
                if (o < `P_CORE) any_choice = 1;
            end
        end
    end

    always @(posedge clk) begin
        if (rst) begin
            toggle <= 0;
            for (o = 0; o < `NPORTS; o = o + 1) rr[o] <= 0;
        end else begin
            if (any_choice) toggle <= ~toggle;
            for (o = 0; o < `NPORTS; o = o + 1)
                if (grant_ok[o]) rr[o] <= (grant_in[o] == `NPORTS-1) ? 3'd0 : grant_in[o] + 3'd1;
        end
    end
endmodule
