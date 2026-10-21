`timescale 1ns/1ps
module tb_arbiter;
    localparam L=62500;
    reg clk=0;
    always #5 clk=~clk;
    reg rst=1;
    reg [3:0] req=0;
    wire [3:0] grant;
    round_robin4 dut(.clk(clk),.rst(rst),.req(req),.grant(grant));
    reg [3:0] masks[0:L-1];
    // Golden word: {head_before[1:0],head_after[1:0],grant[3:0]}.
    reg [7:0] expected[0:L-1];
    integer histogram[0:15];
    integer grant_histogram[0:3];
    integer cycle,i,support,accepted;
    initial begin
        $readmemh("masks.mem",masks);
        $readmemh("expected.mem",expected);
        for(i=0;i<16;i=i+1) histogram[i]=0;
        for(i=0;i<4;i=i+1) grant_histogram[i]=0;
        accepted=0;
        repeat(3) @(negedge clk);
        rst=0;
        for(cycle=0;cycle<L;cycle=cycle+1) begin
            req=masks[cycle];
            #1;
            if(dut.head!==expected[cycle][7:6])
                $fatal(1,"Golden head-before mismatch cycle=%0d",cycle);
            if(grant!==expected[cycle][3:0])
                $fatal(1,"Golden grant mismatch cycle=%0d req=%h grant=%h expected=%h",cycle,req,grant,expected[cycle][3:0]);
            if(grant!=0 && (grant&(grant-1'b1))!=0)
                $fatal(1,"Grant is not one-hot cycle=%0d grant=%h",cycle,grant);
            if((grant&~req)!=0)
                $fatal(1,"Granted an inactive requestor cycle=%0d",cycle);
            if(req!=0 && grant==0)
                $fatal(1,"Nonempty request set has no grant cycle=%0d",cycle);
            if(req==0 && grant!=0)
                $fatal(1,"Idle request set has a grant cycle=%0d",cycle);
            histogram[req]=histogram[req]+1;
            if(grant!=0) accepted=accepted+1;
            for(i=0;i<4;i=i+1) if(grant[i]) grant_histogram[i]=grant_histogram[i]+1;
            @(posedge clk);
            #1;
            if(dut.head!==expected[cycle][5:4])
                $fatal(1,"Golden head-after mismatch cycle=%0d",cycle);
            @(negedge clk);
        end
        support=0;
        for(i=0;i<16;i=i+1) if(histogram[i]!=0) support=support+1;
        $display("PASS cycles=%0d golden_grant_checks=%0d golden_state_checks=%0d mask_support=%0d accepted_grants=%0d",L,L,2*L,support,accepted);
        $display("GRANTS %0d %0d %0d %0d",grant_histogram[0],grant_histogram[1],grant_histogram[2],grant_histogram[3]);
        $finish;
    end
endmodule
