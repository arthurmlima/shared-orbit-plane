// Candidate conventional nonsecurity baseline. No statistical-quality claim.
// Interface matches the sequential per-tile byte units. Configuration words
// 0..10 are absorbed in 11 cycles after word15=start; no warmup is applied.
// bytes_made is cumulative between resets, as in the other byte units.
module xs64_unit #(parameter TILE_ID=0) (
    input clk,rst,cfg_we,
    input [3:0] cfg_addr,
    input [31:0] cfg_wdata,
    input take,
    output hit,
    output [7:0] ks_byte,
    output reg [31:0] bytes_made
);
    reg [31:0] kw[0:10];
    reg [63:0] state,mix;
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
    wire [63:0] mix_next=xs64(mix+{kw[index],kw[index]^32'h9e3779b9});
    wire [63:0] seeded=xs64(mix_next^TILE_SALT);
    assign hit=ready && !start && !rst;
    assign ks_byte=state[7:0];
    always @(posedge clk) if(cfg_we && cfg_addr<11) kw[cfg_addr]<=cfg_wdata;
    always @(posedge clk) begin
        if(rst) begin
            state<=0; mix<=0; index<=0; mixing<=0; ready<=0; bytes_made<=0;
        end else if(start) begin
            mix<=0; index<=0; mixing<=1; ready<=0;
        end else if(mixing) begin
            mix<=mix_next;
            if(index==10) begin
                state<=seeded==0 ? GOLD : seeded;
                mixing<=0; ready<=1;
            end else index<=index+1'b1;
        end else if(take && hit) begin
            state<=xs64(state);
            bytes_made<=bytes_made+1'b1;
        end
    end
endmodule
