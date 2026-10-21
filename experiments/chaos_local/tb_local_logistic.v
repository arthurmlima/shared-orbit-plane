`timescale 1ns/1ps
module tb_local_logistic;
    parameter TILE_ID=0;
    localparam Q=8192;
    reg clk=0;
    always #5 clk=~clk;
    reg rst=1,cfg_we=0,take=0;
    reg [3:0] cfg_addr=0;
    reg [31:0] cfg_wdata=0;
    wire hit;
    wire [7:0] data;
    wire [31:0] made;
    local_logistic_unit #(.TILE_ID(TILE_ID)) dut(
        .clk(clk),.rst(rst),.cfg_we(cfg_we),.cfg_addr(cfg_addr),
        .cfg_wdata(cfg_wdata),.take(take),.hit(hit),.ks_byte(data),.bytes_made(made));
    reg [31:0] keys[0:21];
    reg [7:0] expected[0:3*Q-1];
    reg [7:0] held;
    reg held_valid;
    integer cs,w,cycle,count,checks,startup;
    task configure;
        input integer keyset;
        begin
            take=0;
            for(w=0;w<11;w=w+1) begin
                cfg_we=1;cfg_addr=w;cfg_wdata=keys[keyset*11+w];@(negedge clk);
            end
            cfg_addr=15;@(negedge clk);cfg_we=0;
        end
    endtask
    task restart;
        begin cfg_we=1;cfg_addr=15;@(negedge clk);cfg_we=0; end
    endtask
    initial begin
        $readmemh("keys.mem",keys);$readmemh("expected.mem",expected);
        repeat(5) @(negedge clk);rst=0;checks=0;
        for(cs=0;cs<3;cs=cs+1) begin
            configure(cs%2);
            // Restart once during configuration absorption and once during warmup.
            repeat(5) @(negedge clk);restart();
            repeat(25) @(negedge clk);restart();
            startup=0;
            while(!hit && startup<100) begin
                @(negedge clk);startup=startup+1;
            end
            if(startup!=76) $fatal(1,"Startup latency %0d expected 76",startup);
            // Long initial stall must preserve both output and generation counter.
            held=data;
            repeat(512) begin
                @(posedge clk);
                if(!hit || data!==held || made!=cs*Q) $fatal(1,"Long stall changed output or counter");
                @(negedge clk);
            end
            count=0;cycle=0;held_valid=0;
            while(count<Q && cycle<100000) begin
                take=cycle%7<4 && cycle%53>=11;
                @(posedge clk);
                if(held_valid && (!hit || data!==held)) $fatal(1,"Output changed while stalled");
                held_valid=hit && !take;held=data;
                if(take && hit) begin
                    if(data!==expected[cs*Q+count]) $fatal(1,"Reference mismatch tile=%0d case=%0d index=%0d got=%02x expected=%02x",TILE_ID,cs,count,data,expected[cs*Q+count]);
                    count=count+1;checks=checks+1;
                end
                cycle=cycle+1;@(negedge clk);
            end
            take=0;
            if(count!=Q || made!=(cs+1)*Q) $fatal(1,"Count mismatch");
        end
        rst=1;repeat(3) @(negedge clk);
        if(hit || made!=0) $fatal(1,"Reset failed");
        rst=0;configure(0);
        while(!hit) @(negedge clk);
        take=1;
        for(count=0;count<64;count=count+1) begin
            @(posedge clk);
            if(!hit || data!==expected[count]) $fatal(1,"Reference mismatch after reset");
            checks=checks+1;@(negedge clk);
        end
        take=0;
        if(made!=64) $fatal(1,"Reset counter mismatch");
        $display("PASS tile_id=%0d cases=3 byte_checks=%0d mismatches=0 startup_cycles=76 reset_restart_checks=64",TILE_ID,checks);
        $finish;
    end
endmodule
