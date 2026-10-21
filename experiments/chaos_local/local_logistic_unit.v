// In-house single-orbit chaos control. Not a reproduction of a published PRNG.
// Same U0.32 LEAN=6 form_v(0) recurrence and PERT=8 xs64 perturbation as lbe_dist.
// Eleven configuration words, independent tile-dependent seed, T+1 discarded
// transitions (matching lbe_dist), native demand-driven byte advance.
// Output is x[15:8]. No statistical, independence, security or period claim.
module local_logistic_unit #(
    parameter TILE_ID=0, parameter T=64, parameter LEAN=6, parameter PERT=8
) (
    input clk,rst,cfg_we,
    input [3:0] cfg_addr,
    input [31:0] cfg_wdata,
    input take,
    output hit,
    output [7:0] ks_byte,
    output reg [31:0] bytes_made
);
    reg [31:0] kw[0:10];
    reg [31:0] state,mix32;
    reg [63:0] perturb,mix64;
    reg [3:0] index;
    reg [7:0] warm_count;
    reg mixing,warming,ready;
    wire start=cfg_we && cfg_addr==15;
    localparam [31:0] GOLD32=32'h9e3779b9;
    localparam [63:0] GOLD64=64'h9e3779b97f4a7c15;
    localparam [31:0] TILE_SALT32=GOLD32*(TILE_ID+1);
    localparam [63:0] TILE_SALT64=GOLD64*(TILE_ID+1);
    function [31:0] xs32;
        input [31:0] value;
        reg [31:0] temp;
        begin temp=value^(value<<13); temp=temp^(temp>>17); xs32=temp^(temp<<5); end
    endfunction
    function [63:0] xs64;
        input [63:0] value;
        reg [63:0] temp;
        begin temp=value^(value<<13); temp=temp^(temp>>7); xs64=temp^(temp<<17); end
    endfunction
    function [31:0] logistic;
        input [31:0] value;
        reg [41:0] xx,rx,one;
        reg [83:0] product;
        begin
            xx={10'd0,value}; one=42'd1<<32;
            rx=(xx<<2)-(xx>>LEAN);
            product=rx*(one-xx);
            logistic=product>>32;
        end
    endfunction
    wire [31:0] mix32_next=xs32(mix32^kw[index]);
    wire [63:0] mix64_next=xs64(mix64+{kw[index],kw[index]^GOLD32});
    wire [31:0] seeded32=xs32(xs32(mix32_next^TILE_SALT32));
    wire [63:0] seeded64=xs64(mix64_next^TILE_SALT64);
    wire [63:0] perturb_next=xs64(perturb);
    wire [31:0] perturb_mask=PERT ? ((32'd1<<PERT)-1) : 32'd0;
    wire [31:0] state_next=logistic(state)^(perturb_next[31:0]&perturb_mask);
    assign hit=ready && !start && !rst;
    assign ks_byte=state[15:8];
    always @(posedge clk) if(cfg_we && cfg_addr<11) kw[cfg_addr]<=cfg_wdata;
    always @(posedge clk) begin
        if(rst) begin
            state<=0; perturb<=0; mix32<=0; mix64<=0; index<=0;
            mixing<=0; warming<=0; warm_count<=0; ready<=0; bytes_made<=0;
        end else if(start) begin
            mix32<=0; mix64<=0; index<=0; mixing<=1; warming<=0; ready<=0;
        end else if(mixing) begin
            mix32<=mix32_next; mix64<=mix64_next;
            if(index==10) begin
                state<={2'b01,seeded32[29:0]};
                perturb<=seeded64==0 ? GOLD64 : seeded64;
                mixing<=0; warming<=1; warm_count<=0;
            end else index<=index+1'b1;
        end else if(warming) begin
            state<=state_next; perturb<=perturb_next;
            if(warm_count==T) begin warming<=0; ready<=1; end
            else warm_count<=warm_count+1'b1;
        end else if(take && hit) begin
            state<=state_next; perturb<=perturb_next;
            bytes_made<=bytes_made+1'b1;
        end
    end
endmodule
