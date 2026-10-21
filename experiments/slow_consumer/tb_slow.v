`timescale 1ns/1ps
module tb_slow;
    parameter N=3, EXT=0, DEPTH=32, SLOW=4, PATTERN=0;
    localparam NT=N*N, TW=40, Q=1600;
    reg clk=0;
    always #5 clk=~clk;
    reg rst=1, cfg_we=0;
    reg [3:0] cfg_addr=0;
    reg [31:0] cfg_wdata=0;
    reg [NT-1:0] take_s=0, take_l=0;
    wire [NT-1:0] hit_s, hit_l, ready_s, ready_l;
    wire [NT*8-1:0] data_s, data_l;
    wire [NT*32-1:0] made_s, made_l;
    wire go_s, go_l;
    plane_mesh #(.N(N), .TW(TW), .TH(TW), .EXT(EXT), .DEPTH(DEPTH)) shared (
        .clk(clk), .rst(rst), .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata),
        .take(take_s), .hit(hit_s), .data(data_s), .made(made_s), .ready_o(ready_s), .go_o(go_s));
    plane_mesh #(.N(N), .TW(TW), .TH(TW), .EXT(EXT), .DEPTH(DEPTH), .PRIVATE(1), .LOCAL_GO(1)) private_local (
        .clk(clk), .rst(rst), .cfg_we(cfg_we), .cfg_addr(cfg_addr), .cfg_wdata(cfg_wdata),
        .take(take_l), .hit(hit_l), .data(data_l), .made(made_l), .ready_o(ready_l), .go_o(go_l));
    genvar gy,gx;
    generate for(gy=0;gy<N;gy=gy+1) begin: check_y
        for(gx=0;gx<N;gx=gx+1) begin: check_x
            always @(negedge clk) if(!rst) begin
                if(shared.gy[gy].gx[gx].u.u.cnt>DEPTH || private_local.gy[gy].gx[gx].u.u.cnt>DEPTH)
                    $fatal(1,"FIFO occupancy overflow tile=(%0d,%0d)",gx,gy);
            end
            always @(posedge clk) if(!rst) begin
                if(shared.gy[gy].gx[gx].u.u.cnt==DEPTH && shared.gy[gy].gx[gx].u.u.fifo_we && !shared.gy[gy].gx[gx].u.u.pop)
                    $fatal(1,"Shared FIFO write while full tile=(%0d,%0d)",gx,gy);
                if(private_local.gy[gy].gx[gx].u.u.cnt==DEPTH && private_local.gy[gy].gx[gx].u.u.fifo_we && !private_local.gy[gy].gx[gx].u.u.pop)
                    $fatal(1,"Private FIFO write while full tile=(%0d,%0d)",gx,gy);
            end
        end
    end endgenerate
    reg [31:0] keys[0:21];
    reg [7:0] expected[0:NT*Q-1];
    integer ns[0:NT-1], nl[0:NT-1];
    integer finish_s[0:NT-1], finish_l[0:NT-1];
    integer cycle, w, k, done, checks, stalls, fast_window_s, fast_window_l, slow_window_s, slow_window_l;
    initial begin
        $readmemh("keys.mem", keys);
        $readmemh("expected.mem", expected);
        repeat(5) @(negedge clk);
        rst=0;
        for(w=0; w<11; w=w+1) begin
            cfg_we=1; cfg_addr=w; cfg_wdata=keys[w]; @(negedge clk);
        end
        cfg_addr=15; cfg_wdata=0; @(negedge clk); cfg_we=0;
        for(k=0; k<NT; k=k+1) begin ns[k]=0; nl[k]=0; finish_s[k]=-1; finish_l[k]=-1; end
        cycle=0; done=0; checks=0; stalls=0;
        fast_window_s=0; fast_window_l=0; slow_window_s=0; slow_window_l=0;
        while(!done && cycle<50000) begin
            for(k=0; k<NT; k=k+1) begin
                take_s[k]=ns[k]<Q && (PATTERN ? cycle%256>=64 : (k!=0 || cycle%SLOW==0));
                take_l[k]=nl[k]<Q && (PATTERN ? cycle%256>=64 : (k!=0 || cycle%SLOW==0));
            end
            @(posedge clk);
            if(cycle>=256 && cycle<1280 && !go_s) stalls=stalls+1;
            done=1;
            for(k=0; k<NT; k=k+1) begin
                if(take_s[k] && hit_s[k]) begin
                    if(data_s[8*k+:8] !== expected[k*Q+ns[k]])
                        $fatal(1,"Shared reference mismatch tile=%0d byte=%0d",k,ns[k]);
                    ns[k]=ns[k]+1; checks=checks+1;
                    if(ns[k]==Q) finish_s[k]=cycle;
                    if(cycle>=256 && cycle<1280 && k==1) fast_window_s=fast_window_s+1;
                    if(cycle>=256 && cycle<1280 && k==0) slow_window_s=slow_window_s+1;
                end
                if(take_l[k] && hit_l[k]) begin
                    if(data_l[8*k+:8] !== expected[k*Q+nl[k]])
                        $fatal(1,"Private reference mismatch tile=%0d byte=%0d",k,nl[k]);
                    nl[k]=nl[k]+1; checks=checks+1;
                    if(nl[k]==Q) finish_l[k]=cycle;
                    if(cycle>=256 && cycle<1280 && k==1) fast_window_l=fast_window_l+1;
                    if(cycle>=256 && cycle<1280 && k==0) slow_window_l=slow_window_l+1;
                end
                if(ns[k]!=Q || nl[k]!=Q) done=0;
            end
            cycle=cycle+1; @(negedge clk);
        end
        if(!done) $fatal(1,"Timeout");
        for(k=0;k<NT;k=k+1)
            if(made_s[32*k+:32]!=Q || made_l[32*k+:32]!=Q) $fatal(1,"Incorrect generation count tile=%0d",k);
        $display("RESULT n=%0d ext=%0d depth=%0d slow_period=%0d coordinated=%0d cycles=%0d checks=%0d fast_finish_shared=%0d slow_finish_shared=%0d fast_finish_private=%0d slow_finish_private=%0d window_cycles=1024 fast_window_shared=%0d slow_window_shared=%0d fast_window_private=%0d slow_window_private=%0d global_stall_window=%0d mismatches=0",N,EXT,DEPTH,SLOW,PATTERN,cycle,checks,finish_s[1],finish_s[0],finish_l[1],finish_l[0],fast_window_s,slow_window_s,fast_window_l,slow_window_l,stalls);
        $finish;
    end
endmodule
