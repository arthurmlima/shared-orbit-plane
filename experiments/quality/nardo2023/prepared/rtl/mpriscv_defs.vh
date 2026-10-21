// MPRISC-V message format (one flit = one message)
`ifndef MPRISCV_DEFS_VH
`define MPRISCV_DEFS_VH

`define MSG_W        59
`define F_DATA       15:0    // pixel value (signed 16-bit)
`define F_TX         23:16   // routing target X (global pixel coordinate)
`define F_TY         31:24   // routing target Y
`define F_OX         39:32   // origin X (pixel coordinate inside origin tile)
`define F_OY         47:40   // origin Y
`define F_STEP       51:48
`define F_FRAME      55:52
`define F_TYPE       57:56
`define F_OSINK      58      // 0: origin is the RISC-V core, 1: origin is the PS (EXT port)

`define T_WR   2'd0          // forward: write pixel into PM (image distribution)
`define T_REQ  2'd1          // forward: read request to PM
`define T_RESP 2'd2          // backward: read response
`define T_HALO 2'd3          // forward: halo copy, pixel coords in OX/OY, routed by TX/TY

// router port indices
`define P_N    0
`define P_S    1
`define P_E    2
`define P_W    3
`define P_CORE 4
`define P_PM   5
`define P_EXT  6
`define NPORTS 7

`endif
