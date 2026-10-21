# E7: Vivado reproduction of the baseline per-profile matched-sharing method (synthesis only, out of context,
# flatten rebuilt). usage: vivado -mode batch -nojournal -nolog -source profiles.tcl -tclargs <N> <EXT>
# Profiles: pair (no source), row<v> (row source only), col<v> (column source only), dual_r<v>_c<w>, control.
set N   [lindex $argv 0]
set EXT [lindex $argv 1]
set here [file normalize [file dirname [info script]]]
set rtl  [file normalize "$here/../rtl"]
set out  "$here/profiles_N${N}_ext${EXT}"
file mkdir $out
set_param general.maxThreads 4
set tw [expr {120 / $N}]
set profiles {}
lappend profiles [list pair 0 0 0 1]
for {set y 0} {$y < $N} {incr y} { lappend profiles [list row[expr {2*$y}] 1 0 [expr {2*$y}] 1] }
for {set x 0} {$x < $N} {incr x} { lappend profiles [list col[expr {2*$x+1}] 0 1 0 [expr {2*$x+1}]] }
for {set y 0} {$y < $N} {incr y} { for {set x 0} {$x < $N} {incr x} {
    lappend profiles [list dual_r[expr {2*$y}]_c[expr {2*$x+1}] 1 1 [expr {2*$y}] [expr {2*$x+1}]] } }
set fh [open "$out/profiles.txt" w]
foreach p $profiles {
    lassign $p name rs cs rv cv
    create_project -in_memory -part xczu7ev-ffvc1156-2-e
    read_verilog [list "$rtl/lbe_dist.v" "$rtl/matched_tile.v"]
    synth_design -top matched_tile -part xczu7ev-ffvc1156-2-e -mode out_of_context -include_dirs $rtl -flatten_hierarchy rebuilt \
        -generic ROW_SRC=$rs -generic COL_SRC=$cs -generic ROW_VAR=$rv -generic COL_VAR=$cv -generic EXT=$EXT \
        -generic TW=$tw -generic TH=$tw -generic T=64 -generic LEAN=6 -generic PERT=8
    create_clock -period 14.2857 -name clk [get_ports clk]
    report_utilization -file "$out/util_synth_$name.txt"
    opt_design
    report_utilization -file "$out/util_opt_$name.txt"
    puts $fh "$name ROW_SRC=$rs COL_SRC=$cs ROW_VAR=$rv COL_VAR=$cv"
    close_project
}
# control: the registered all_armed / go reduction, NT inputs each
create_project -in_memory -part xczu7ev-ffvc1156-2-e
read_verilog [list "$rtl/matched_tile.v" "$rtl/lbe_dist.v"]
synth_design -top matched_control -part xczu7ev-ffvc1156-2-e -mode out_of_context -include_dirs $rtl -flatten_hierarchy rebuilt
create_clock -period 14.2857 -name clk [get_ports clk]
report_utilization -file "$out/util_synth_control.txt"
opt_design
report_utilization -file "$out/util_opt_control.txt"
puts $fh "control"
close $fh
close_project
puts "DONE profiles N=$N EXT=$EXT"
