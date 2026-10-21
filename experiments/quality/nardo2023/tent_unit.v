// Clean-room recurrence from Nardo et al., Electronics 12(8):1953 (2023),
// doi:10.3390/electronics12081953, Figure 2, at published width K=32.
// The configuration/seed adapter and low-byte selection are this study's.
// This core produces one byte/take, no warmup, and no security guarantee.
module tent_unit #(parameter TILE_ID=0) (
    input clk,rst,cfg_we,
    input [3:0] cfg_addr,
    input [31:0] cfg_wdata,
    input take,
    output hit,
    output [7:0] ks_byte,
    output reg [31:0] bytes_made
);
    reg [31:0] kw[0:10];
    reg [31:0] state;
    reg [63:0] mix;
    reg [3:0] index;
    reg mixing,ready;
    wire start=cfg_we && cfg_addr==15;
    localparam [63:0] GOLD=64'h9e3779b97f4a7c15;
    localparam [63:0] TILE_SALT=GOLD*(TILE_ID+1);
    function [63:0] xs64;
        input [63:0] value;
        reg [63:0] t;
        begin t=value^(value<<13); t=t^(t>>7); xs64=t^(t<<17); end
    endfunction
    function [31:0] tent_step;
        input [31:0] value;
        begin tent_step={value[30:0]^{31{value[31]}},value[1]^value[0]}; end
    endfunction
    wire [63:0] mix_next=xs64(mix+{kw[index],kw[index]^32'h9e3779b9});
    wire [63:0] seeded=xs64(mix_next^TILE_SALT);
    assign hit=ready && !start && !rst;
    assign ks_byte=state[7:0];
    always @(posedge clk) if(cfg_we && cfg_addr<11) kw[cfg_addr]<=cfg_wdata;
    always @(posedge clk) begin
        if(rst) begin
            state<=0;mix<=0;index<=0;mixing<=0;ready<=0;bytes_made<=0;
        end else if(start) begin
            mix<=0;index<=0;mixing<=1;ready<=0;
        end else if(mixing) begin
            mix<=mix_next;
            if(index==10) begin
                state<=seeded[31:0]==0 ? 32'h1 : seeded[31:0];
                mixing<=0;ready<=1;
            end else index<=index+1'b1;
        end else if(take && hit) begin
            state<=tent_step(state);
            bytes_made<=bytes_made+1'b1;
        end
    end
endmodule
