# Inspect exactly the split-model starts sampled by the unchanged main reports.
# All commands are read-only; no new case analysis or exceptions are set.
set checkpoint [file normalize [lindex $argv 0]]
set starts_file [file normalize [lindex $argv 1]]
set out [file normalize [lindex $argv 2]]
file mkdir $out
open_checkpoint $checkpoint
proc exact_pin {name} { return [get_pins -quiet -hier -filter [format {NAME == "%s"} $name]] }
proc exact_cell {name} { return [get_cells -quiet -hier -filter [format {NAME == "%s"} $name]] }
set sf [open $starts_file r]
set starts [split [string trim [read $sf]] "\n"]
close $sf
set fp [open "$out/sampled_dsp.tsv" w]
puts $fp "start_pin\tBREG\tB_INPUT\tAREG\tB_input_logic\tINMODE_4_to_0\tCEB2_logic\tMREG\tPREG"
set ap [open "$out/active_bit_paths.tsv" w]
puts $ap "through_pin\tinput_logic\tslack\tstartpoint\tendpoint"
set states [get_cells -quiet -hier -regexp {.*g_dist\.u_ks/(xr|xc)_reg.*}]
set i 0
foreach start $starts {
    regexp {^(.*)/DSP_A_B_DATA_INST/B2_DATA\[([0-9]+)\]$} $start ignored parent bit
    set cell [exact_cell "$parent/DSP_A_B_DATA_INST"]
    set bpin [exact_pin [format {%s/B[%d]} $parent $bit]]
    set mode ""
    foreach b {4 3 2 1 0} { append mode "[get_property LOGIC_VALUE [exact_pin [format {%s/INMODE[%d]} $parent $b]]]," }
    puts $fp "$start\t[get_property BREG $cell]\t[get_property B_INPUT $cell]\t[get_property AREG $cell]\t[get_property LOGIC_VALUE $bpin]\t[string trimright $mode ,]\t[get_property LOGIC_VALUE [exact_pin "$parent/CEB2"]]\t[get_property MREG [exact_cell "$parent/DSP_M_DATA_INST"]]\t[get_property PREG [exact_cell "$parent/DSP_OUTPUT_INST"]]"
    # Adjacent nonconstant data bit: obtain a real registered feedback path.
    set found 0
    foreach b {0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16} {
        set bp [exact_pin [format {%s/B[%d]} $parent $b]]
        set logic [get_property LOGIC_VALUE $bp]
        if {$logic != "unknown"} { continue }
        set through [exact_pin [format {%s/DSP_A_B_DATA_INST/B2_DATA[%d]} $parent $b]]
        set paths [get_timing_paths -quiet -setup -from $states -through $through -to $states -max_paths 1 -nworst 1]
        if {[llength $paths]} {
            foreach path $paths { puts $ap "$through\t$logic\t[get_property SLACK $path]\t[get_property STARTPOINT_PIN $path]\t[get_property ENDPOINT_PIN $path]" }
            report_timing -from $states -through $through -to $states -max_paths 1 -nworst 1 -file "$out/active_bit_${i}.txt"
            set found 1
            break
        }
    }
    if {!$found} { puts $ap "$parent\tNO_ORBIT_REGISTER_PATH_FOUND\tNA\tNA\tNA" }
    incr i
}
close $fp
close $ap
close_design
exit
