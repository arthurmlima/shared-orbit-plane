`timescale 1ns/1ps
// Shared versus private equivalence of the orbit plane for any N and extractor EXT (generalizes the baseline
// tb_equivalence.v): three plane_mesh instances (shared with global go, private with global go, private with local
// go), two key sets, asymmetric consumer stalls, every byte checked against the private copy and the software reference.
module tb_equiv;
    parameter N = 4, EXT = 0, MODE = 3;
    localparam TW = 120 / N;
    localparam Q = TW * TW;
    localparam NT = N * N;
    reg clk = 0;
    always #5 clk = ~clk;
    reg rst = 1, cfg_we = 0;
    reg [3:0] cfg_addr = 0;
    reg [31:0] cfg_wdata = 0;
    reg [NT-1:0] take_s = 0, take_l = 0;
    wire [NT-1:0] hit_s, hit_p, hit_l, ready_s, ready_p, ready_l;
    wire [8*NT-1:0] data_s, data_p, data_l;
    wire [32*NT-1:0] made_s, made_p, made_l;
    wire go_s, go_p, go_l;
    plane_mesh #(.N(N), .TW(TW), .TH(TW), .MODE(MODE), .PRIVATE(0), .EXT(EXT), .LOCAL_GO(0)) shared (
        .clk(clk), .rst(rst), .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata),
        .take(take_s), .hit(hit_s), .data(data_s), .made(made_s), .ready_o(ready_s), .go_o(go_s));
    plane_mesh #(.N(N), .TW(TW), .TH(TW), .MODE(MODE), .PRIVATE(1), .EXT(EXT), .LOCAL_GO(0)) private_sync (
        .clk(clk), .rst(rst), .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata),
        .take(take_s), .hit(hit_p), .data(data_p), .made(made_p), .ready_o(ready_p), .go_o(go_p));
    plane_mesh #(.N(N), .TW(TW), .TH(TW), .MODE(MODE), .PRIVATE(1), .EXT(EXT), .LOCAL_GO(1)) private_local (
        .clk(clk), .rst(rst), .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata),
        .take(take_l), .hit(hit_l), .data(data_l), .made(made_l), .ready_o(ready_l), .go_o(go_l));
    reg [31:0] key_words [0:21];
    reg [7:0] expected [0:2*NT*Q-1];
    integer ns[0:NT-1], nl[0:NT-1];
    integer cs, cycle, k, w, all_done, stalls, divergent, comparisons, limit;
    reg [1023:0] exp_path;
    initial begin
        $readmemh("keys.mem", key_words);
        if (!$value$plusargs("EXPECTED=%s", exp_path)) exp_path = "expected.mem";
        $readmemh(exp_path, expected);
        comparisons = 0;
        limit = 400 * Q + 2000 * NT;
        for (cs = 0; cs < 2; cs = cs + 1) begin
            @(negedge clk); rst = 1; cfg_we = 0; take_s = 0; take_l = 0;
            repeat (5) @(negedge clk);
            rst = 0;
            for (w = 0; w < 11; w = w + 1) begin
                cfg_we = 1; cfg_addr = w; cfg_wdata = key_words[cs*11 + w];
                @(negedge clk);
            end
            cfg_addr = 15; cfg_wdata = 0;
            @(negedge clk); cfg_we = 0;
            for (k = 0; k < NT; k = k + 1) begin ns[k] = 0; nl[k] = 0; end
            cycle = 0; all_done = 0; stalls = 0; divergent = 0;
            while (!all_done && cycle < limit) begin
                for (k = 0; k < NT; k = k + 1) begin
                    take_s[k] = ns[k] < Q && cycle > 120 + 19*k && ((cycle + 3*k) % 13 < 7) && !(cycle % 257 < 53);
                    take_l[k] = nl[k] < Q && cycle > 300 + 37*k && ((cycle + 5*k) % (17 + k%7) < 10) && !((cycle + 11*k) % 173 < 47);
                end
                @(posedge clk);
                if (hit_s !== hit_p || ready_s !== ready_p || go_s !== go_p || made_s !== made_p)
                    $fatal(1, "Lockstep status mismatch case=%0d cycle=%0d", cs, cycle);
                if (cycle > 100 && !go_s) stalls = stalls + 1;
                if (made_s !== made_l) divergent = divergent + 1;
                all_done = 1;
                for (k = 0; k < NT; k = k + 1) begin
                    if (take_s[k] && hit_s[k]) begin
                        if (data_s[8*k +: 8] !== data_p[8*k +: 8])
                            $fatal(1, "Shared/private mismatch case=%0d tile=%0d index=%0d", cs, k, ns[k]);
                        if (data_s[8*k +: 8] !== expected[cs*NT*Q + k*Q + ns[k]])
                            $fatal(1, "Reference mismatch shared case=%0d tile=%0d index=%0d got=%02x ref=%02x",
                                   cs, k, ns[k], data_s[8*k +: 8], expected[cs*NT*Q + k*Q + ns[k]]);
                        ns[k] = ns[k] + 1; comparisons = comparisons + 2;
                    end
                    if (take_l[k] && hit_l[k]) begin
                        if (data_l[8*k +: 8] !== expected[cs*NT*Q + k*Q + nl[k]])
                            $fatal(1, "Reference mismatch local private case=%0d tile=%0d index=%0d got=%02x ref=%02x",
                                   cs, k, nl[k], data_l[8*k +: 8], expected[cs*NT*Q + k*Q + nl[k]]);
                        nl[k] = nl[k] + 1; comparisons = comparisons + 1;
                    end
                    if (ns[k] != Q || nl[k] != Q) all_done = 0;
                end
                cycle = cycle + 1;
                @(negedge clk);
            end
            take_s = 0; take_l = 0;
            if (!all_done) $fatal(1, "Timeout case=%0d", cs);
            if (stalls == 0 || divergent == 0) $fatal(1, "No effective stalls/scheduling divergence");
            for (k = 0; k < NT; k = k + 1)
                if (made_s[32*k +: 32] != Q || made_p[32*k +: 32] != Q || made_l[32*k +: 32] != Q)
                    $fatal(1, "Wrong made count case=%0d tile=%0d", cs, k);
            $display("CASE_PASS N=%0d EXT=%0d case=%0d cycles=%0d global_stall_cycles=%0d divergent_schedule_cycles=%0d",
                     N, EXT, cs, cycle, stalls, divergent);
        end
        $display("PASS N=%0d EXT=%0d cases=2 tiles=%0d bytes_per_stream=%0d hardware_byte_checks=%0d mismatches=0",
                 N, EXT, NT, Q, comparisons);
        $finish;
    end
endmodule
