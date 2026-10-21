`timescale 1ns/1ps
module tb_tent;
    parameter TILE_ID=0;
    localparam Q=1024;
    reg clk=0;
    always #5 clk=~clk;
    reg rst=1,cfg_we=0,take=0;
    reg [3:0] cfg_addr=0;
    reg [31:0] cfg_wdata=0;
    wire hit;
    wire [7:0] data;
    wire [31:0] made;
    tent_unit #(.TILE_ID(TILE_ID)) dut(.clk(clk),.rst(rst),.cfg_we(cfg_we),.cfg_addr(cfg_addr),.cfg_wdata(cfg_wdata),.take(take),.hit(hit),.ks_byte(data),.bytes_made(made));
    reg [31:0] keys[0:21];
    reg [7:0] expected[0:3*Q-1];
    reg [7:0] held;
    reg held_valid;
    integer cs,w,cycle,count,checks;
    initial begin
        $readmemh("keys.mem",keys); $readmemh("expected.mem",expected);
        repeat(5) @(negedge clk);
        rst=0; checks=0;
        for(cs=0;cs<3;cs=cs+1) begin
            take=0;
            for(w=0;w<11;w=w+1) begin
                cfg_we=1;cfg_addr=w;cfg_wdata=keys[(cs%2)*11+w];@(negedge clk);
            end
            cfg_addr=15; @(negedge clk);cfg_we=0;
            count=0;cycle=0;held_valid=0;
            while(count<Q && cycle<10000) begin
                take=cycle%7<4 && cycle%53>=11;
                @(posedge clk);
                if(held_valid && (!hit || data!==held)) $fatal(1,"Output changed while stalled");
                held_valid=hit && !take;held=data;
                if(take && hit) begin
                    if(data!==expected[cs*Q+count]) $fatal(1,"Reference mismatch tile=%0d case=%0d index=%0d",TILE_ID,cs,count);
                    count=count+1;checks=checks+1;
                end
                cycle=cycle+1;@(negedge clk);
            end
            take=0;
            if(count!=Q || made!=(cs+1)*Q) $fatal(1,"Count mismatch");
        end
        $display("PASS tile_id=%0d cases=3 byte_checks=%0d mismatches=0",TILE_ID,checks);
        $finish;
    end
endmodule
