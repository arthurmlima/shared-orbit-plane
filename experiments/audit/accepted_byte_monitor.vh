// Simulation-only monitor, included inside one generated tile scope.
// This file is never read by the routed source tree.
integer byte_monitor_fd;
integer byte_monitor_pass = 0;
integer byte_monitor_index = 0;
integer byte_monitor_cycle = 0;
reg [4095:0] byte_monitor_directory;
initial begin
    if (!$value$plusargs("BYTE_TRACE_DIR=%s", byte_monitor_directory))
        $fatal(1, "BYTE_TRACE_DIR is required for accepted-byte validation");
    byte_monitor_fd = $fopen($sformatf("%0s/tile_%0d.accepted.tsv", byte_monitor_directory, T), "w");
    if (!byte_monitor_fd) $fatal(1, "Cannot open accepted-byte trace for tile %0d", T);
end
always @(posedge clk) begin
    byte_monitor_cycle = byte_monitor_cycle + 1;
    if (rst) begin
        byte_monitor_pass = 0;
        byte_monitor_index = 0;
    end else if (u_tile.ks_cfg_we && u_tile.mem_addr[5:2] == 4'd15) begin
        byte_monitor_pass = byte_monitor_pass + 1;
        byte_monitor_index = 0;
        $fwrite(byte_monitor_fd, "START\t%0d\t%0d\n", byte_monitor_pass, byte_monitor_cycle);
        $fflush(byte_monitor_fd);
    end else if (u_tile.ks_take && u_tile.ks_hit) begin
        if (byte_monitor_pass == 0) $fatal(1, "Accepted byte before initialization on tile %0d", T);
        $fwrite(byte_monitor_fd, "BYTE\t%0d\t%0d\t%0d\t%02x\n", byte_monitor_pass, byte_monitor_index, byte_monitor_cycle, u_tile.ks_byte);
        byte_monitor_index = byte_monitor_index + 1;
        $fflush(byte_monitor_fd);
    end
end
