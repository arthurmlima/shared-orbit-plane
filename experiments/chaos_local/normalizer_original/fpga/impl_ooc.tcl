# Out-of-context Vivado implementation flow.
# usage: vivado -mode batch -nojournal -nolog -source impl_ooc.tcl -tclargs <tag> <FREQ_MHZ> "<generics>" [top] [outroot]
#   top     : mpriscv_axi (default, complete mesh), plane_mesh (Level B subsystem), ext_bench (Level A), matched_tile
#   outroot : directory that receives ooc_<tag>/ (default: this script's directory)
# RTL is always ../rtl of this script. Clock: s_axi_aclk if the top has it, else clk. I/O unconstrained.
set tag  [lindex $argv 0]
set FREQ [lindex $argv 1]
set gens [lindex $argv 2]
set top  [expr {[llength $argv] > 3 ? [lindex $argv 3] : "mpriscv_axi"}]
set here [file normalize [file dirname [info script]]]
set outroot [expr {[llength $argv] > 4 ? [file normalize [lindex $argv 4]] : $here}]
set rtl  [file normalize "$here/../rtl"]
set out  "$outroot/ooc_$tag"
file mkdir $out
set_param general.maxThreads 6
puts "INFO: v2 flow tag=$tag top=$top freq=$FREQ generics=$gens rtl=$rtl"
create_project -in_memory -part xczu7ev-ffvc1156-2-e
read_verilog [glob -nocomplain "$rtl/*.v"]
set garg {}
foreach g $gens { lappend garg -generic $g }
set t0 [clock seconds]
synth_design -top $top -part xczu7ev-ffvc1156-2-e -mode out_of_context -include_dirs $rtl -flatten_hierarchy rebuilt {*}$garg
set period [expr {1000.0 / $FREQ}]
if {[llength [get_ports -quiet s_axi_aclk]] > 0} { set clkport s_axi_aclk } else { set clkport clk }
create_clock -period $period -name clk [get_ports $clkport]
report_utilization -file "$out/util_synth_$tag.txt"
set t1 [clock seconds]
opt_design
report_utilization -file "$out/util_opt_$tag.txt"
place_design
phys_opt_design
route_design
set t2 [clock seconds]
report_utilization -file "$out/util_$tag.txt"
report_utilization -hierarchical -hierarchical_depth 5 -file "$out/util_hier_$tag.txt"
report_timing_summary -max_paths 20 -file "$out/timing_$tag.txt"
report_timing -max_paths 10 -nworst 1 -file "$out/paths_$tag.txt"
set ks_cells [get_cells -hier -quiet -filter {NAME =~ *u_ks*}]
if {[llength $ks_cells] > 0} {
    report_timing -through $ks_cells -max_paths 10 -nworst 1 -file "$out/paths_ks_$tag.txt"
    set ks_slack [get_property SLACK [lindex [get_timing_paths -through $ks_cells -max_paths 1 -nworst 1 -setup] 0]]
} else { set ks_slack "none" }
set orb_nets [get_nets -hier -quiet -filter {NAME =~ *orb_row_src* || NAME =~ *orb_col_src*}]
if {[llength $orb_nets] > 0} {
    report_timing -through $orb_nets -max_paths 10 -nworst 1 -file "$out/paths_plane_$tag.txt"
    set plane_slack [get_property SLACK [lindex [get_timing_paths -through $orb_nets -max_paths 1 -nworst 1 -setup] 0]]
} else { set plane_slack "none" }
report_power -file "$out/power_$tag.txt"
write_checkpoint -force "$out/routed_$tag.dcp"
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]
set fmax [expr {1000.0 / ($period - $wns)}]
set fh [open "$out/fmax_$tag.txt" w]
puts $fh "tag $tag top $top target_MHz $FREQ period_ns $period WNS_ns $wns Fmax_MHz [format %.1f $fmax] ks_unit_slack_ns $ks_slack plane_wire_slack_ns $plane_slack synth_s [expr {$t1-$t0}] impl_s [expr {$t2-$t1}] generics {$gens}"
close $fh
puts "DONE $tag top $top target $FREQ MHz, WNS $wns ns, Fmax [format %.1f $fmax] MHz, ks slack $ks_slack, plane slack $plane_slack; reports in $out"
