# Existing routed-checkpoint audit only. Reports are written to a NEW directory.
# No implementation commands, constraints or checkpoint writes are performed.
set checkpoint [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
file mkdir $out
open_checkpoint $checkpoint
check_timing -verbose -file "$out/check_timing.txt"
report_timing_summary -report_unconstrained -check_timing_verbose -max_paths 20 -file "$out/timing_summary_unconstrained.txt"
report_clocks -file "$out/clocks.txt"
report_clock_interaction -file "$out/clock_interaction.txt"
report_exceptions -file "$out/exceptions.txt"

proc sequential_named {pattern} {
    set result {}
    foreach cell [get_cells -quiet -hier -regexp $pattern] {
        set ref [get_property REF_NAME $cell]
        if {[string match FD* $ref] || [string match LD* $ref]} { lappend result $cell }
    }
    return $result
}
set states [sequential_named {.*g_dist\.u_ks/(xr|xc)_reg.*}]
set receivers [sequential_named {.*g_dist\.u_ks/(row_q|col_q)_reg.*}]
set readiness [sequential_named {.*g_dist\.u_ks/(cnt|pushed|running)_reg.*}]
set armed [sequential_named {.*g_dist\.u_ks/armed_reg.*}]
set go [sequential_named {.*orb_go_r_reg.*}]
set initialize [sequential_named {.*orb_all_armed_r_reg.*}]
set groups [list recurrence $states receivers $receivers readiness_state $readiness initialization_state $armed advance_register $go initialization_register $initialize]
set inventory [open "$out/register_coverage.tsv" w]
puts $inventory "class\tcell\tclock_names\tsetup_path_present\tsetup_slack\tstartpoint\tendpoint"
foreach {class cells} $groups {
    foreach cell $cells {
        set c [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == C || REF_PIN_NAME == G}]
        set clocks [get_clocks -quiet -of_objects $c]
        set d [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == D}]
        set paths {}
        if {[llength $d]} { set paths [get_timing_paths -quiet -to $d -max_paths 1 -nworst 1 -setup] }
        set slack "NA"; set start "NA"; set endpoint "NA"
        if {[llength $paths]} {
            set p [lindex $paths 0]
            set slack [get_property SLACK $p]
            set start [get_property STARTPOINT_PIN $p]
            set endpoint [get_property ENDPOINT_PIN $p]
        }
        puts $inventory "$class\t$cell\t[join $clocks ,]\t[expr {[llength $paths] > 0}]\t$slack\t$start\t$endpoint"
    }
}
close $inventory
proc paths_between {from to filename} {
    if {![llength $from] || ![llength $to]} {
        set fp [open $filename w]; puts $fp "MISSING_REGISTER_CLASS: inspect optimized names and netlist connectivity"; close $fp
    } else {
        report_timing -from $from -to $to -max_paths 20 -nworst 1 -file $filename
    }
}
paths_between $states $states "$out/recurrence_paths.txt"
paths_between $states $receivers "$out/distribution_paths.txt"
paths_between $readiness $go "$out/readiness_reduction_paths.txt"
paths_between $armed $initialize "$out/initialization_reduction_paths.txt"
paths_between $go $states "$out/advance_to_source_paths.txt"
set ports [open "$out/external_ports.tsv" w]
puts $ports "port\tdirection"
foreach port [get_ports] { puts $ports "$port\t[get_property DIRECTION $port]" }
close $ports
set fp [open "$out/scope.txt" w]
puts $fp "Existing checkpoint; constraints unchanged. External I/O is deliberately unconstrained in the original common flow."
puts $fp "Register-class absence or an unclocked/no-setup-path endpoint requires explicit review, not an automatic timing pass."
puts $fp "Counts: states=[llength $states] receivers=[llength $receivers] readiness=[llength $readiness] armed=[llength $armed] go=[llength $go] init=[llength $initialize]"
close $fp
close_design
exit
