// Index into a Tile's Pixel-Memory. The PM keeps, for every step, the Tile region
// plus a one-pixel halo ring: local coords (-1..TW, -1..TH) -> (0..TW+1, 0..TH+1).
// Needs localparams XINIT, YINIT, TW, TH, NSTEP and AW in the including module.
function [AW-1:0] pm_index;
    input [7:0] gx, gy;
    input [3:0] s;
    reg signed [11:0] lx, ly;
    begin
        lx = $signed({4'b0, gx}) - XINIT + 1;
        ly = $signed({4'b0, gy}) - YINIT + 1;
        pm_index = (ly * (TW + 2) + lx) * NSTEP + s;
    end
endfunction
