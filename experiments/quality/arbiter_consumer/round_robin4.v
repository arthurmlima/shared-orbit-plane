// Four-requestor, work-conserving round-robin arbiter.
// Every nonzero grant is accepted at this clock edge (no downstream stall).
// Reset starts priority at requestor0; an idle cycle retains priority.
module round_robin4 (
    input clk,rst,
    input [3:0] req,
    output reg [3:0] grant
);
    reg [1:0] head;
    reg [1:0] head_next;
    reg found;
    integer offset,index;
    always @* begin
        grant=0;
        head_next=head;
        found=0;
        index=0;
        for(offset=0;offset<4;offset=offset+1) begin
            index=(head+offset)&3;
            if(!found && req[index]) begin
                grant[index]=1'b1;
                head_next=(index+1)&3;
                found=1;
            end
        end
    end
    always @(posedge clk) begin
        if(rst) head<=0;
        else head<=head_next;
    end
endmodule
