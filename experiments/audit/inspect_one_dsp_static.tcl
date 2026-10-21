# Read-only characterization of the sampled cell with no dynamic B-side path.
set checkpoint [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
file mkdir $out
open_checkpoint $checkpoint
set parent {u_mesh/g_row[5].g_col[5].u_tile/g_dist.u_ks/t0__1}
set fp [open "$out/static_operand.tsv" w]
puts $fp "object\tproperty\tvalue"
foreach port {B A INMODE} width {18 30 5} {
    for {set b 0} {$b < $width} {incr b} {
        set name [format {%s/%s[%d]} $parent $port $b]
        set pin [get_pins -quiet -hier -filter [format {NAME == "%s"} $name]]
        puts $fp "$name\tLOGIC_VALUE\t[get_property LOGIC_VALUE $pin]"
    }
}
foreach suffix {DSP_A_B_DATA_INST DSP_MULTIPLIER_INST DSP_PREADD_DATA_INST DSP_PREADD_INST} {
    set name "$parent/$suffix"
    set cell [get_cells -quiet -hier -filter [format {NAME == "%s"} $name]]
    foreach property {REF_NAME AREG BREG A_INPUT B_INPUT AMULTSEL BMULTSEL PREADDINSEL ADREG DREG INMODEREG} {
        puts $fp "$name\t$property\t[get_property -quiet $property $cell]"
    }
}
close $fp
close_design
exit
