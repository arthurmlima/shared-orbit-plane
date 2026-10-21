# Read-only mapped-source audit. Usage: <routed.dcp> <new-output-directory> [N=6]
# No synthesis, implementation, constraints, preservation, or checkpoint writes.
set checkpoint [file normalize [lindex $argv 0]]
set out [file normalize [lindex $argv 1]]
set N [expr {[llength $argv] > 2 ? [lindex $argv 2] : 6}]
file mkdir $out
open_checkpoint $checkpoint

proc names {objects} {
    set result {}
    foreach object $objects { lappend result $object }
    return [lsort -unique $result]
}
proc property_or_na {object property} {
    if {![llength $object]} { return NA }
    if {[catch {get_property -quiet $property $object} value] || $value == ""} { return NA }
    return $value
}
proc exact_pin {name} {
    return [get_pins -quiet -hier -filter [format {NAME == "%s"} $name]]
}
proc exact_cell {name} {
    return [get_cells -quiet -hier -filter [format {NAME == "%s"} $name]]
}
proc sequential_named {pattern} {
    set result {}
    foreach cell [get_cells -quiet -hier -regexp $pattern] {
        set ref [get_property REF_NAME $cell]
        if {[string match FD* $ref] || [string match LD* $ref]} { lappend result $cell }
    }
    return $result
}
proc parsed_register {name} {
    if {[regexp {^u_mesh/g_row\[([0-9]+)\]\.g_col\[([0-9]+)\]\.u_tile/g_dist\.u_ks/(xr|xc|row_q|col_q)_reg\[([0-9]+)\](.*)$} $name unused y x bank bit suffix]} {
        return [list $y $x $bank $bit $suffix]
    }
    return {}
}
set clock_cache [dict create]
proc cell_clocks {cell} {
    global clock_cache
    set name [get_property NAME $cell]
    if {![dict exists $clock_cache $name]} {
        set pins [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == C || REF_PIN_NAME == G}]
        set clocks {}
        if {[llength $pins]} { set clocks [names [get_clocks -quiet -of_objects $pins]] }
        dict set clock_cache $name [join $clocks ,]
    }
    return [dict get $clock_cache $name]
}
proc direct_drivers {pin} {
    set nets [get_nets -quiet -segments -of_objects $pin]
    if {![llength $nets]} { return {} }
    return [names [get_pins -quiet -leaf -of_objects $nets -filter {DIRECTION == OUT}]]
}
set mapped_register_metadata [dict create]
proc driver_metadata {driver} {
    global mapped_register_metadata
    set name [file dirname $driver]
    if {[dict exists $mapped_register_metadata $name]} { return [dict get $mapped_register_metadata $name] }
    # Only unusual non-register drivers need an exact native-object lookup.
    set resolved [exact_cell $name]
    if {[llength $resolved] != 1} { return [list UNRESOLVED_DRIVER_CELL "" {}] }
    set ref [get_property REF_NAME $resolved]
    set clocks [cell_clocks $resolved]
    set metadata [list $ref $clocks [parsed_register $name]]
    dict set mapped_register_metadata $name $metadata
    return $metadata
}
proc driver_class {driver y x wanted wanted_bit} {
    lassign [driver_metadata $driver] ref clocks parsed
    if {$ref == "UNRESOLVED_DRIVER_CELL"} { return $ref }
    if {$ref == "GND" || $ref == "VCC"} { return CONSTANT }
    if {![string match FD* $ref] && ![string match LD* $ref]} { return OTHER_DRIVER }
    if {![llength $parsed]} { return OTHER_DRIVER }
    lassign $parsed sy sx bank bit suffix
    if {$bank != "xr" && $bank != "xc"} { return NON_SOURCE_REGISTER }
    if {$sy != $y || $sx != $x} { return CROSS_TILE_SOURCE }
    if {$bank != $wanted} { return WRONG_LOCAL_SOURCE_ROLE }
    if {$bit != $wanted_bit} { return WRONG_LOCAL_SOURCE_BIT }
    return SAME_TILE_SOURCE
}

set registers [sequential_named {.*g_dist\.u_ks/(xr|xc|row_q|col_q)_reg.*}]
set bank_cells [dict create]
set bank_bits [dict create]
set receiver_bit_drivers [dict create]
set receiver_bit_classes [dict create]
set source_seen_as_driver [dict create]
set inventory [open "$out/register_inventory.tsv" w]
puts $inventory "y\tx\tbank\tcanonical_bit\tname_suffix\tcell\tref_name\tclock_names\tQ_logic_value\tORIG_CELL_NAME\tORIG_REF_NAME\tLOC\tBEL"
set unparsed [open "$out/unparsed_registers.tsv" w]
puts $unparsed "cell\tref_name\tORIG_CELL_NAME\tORIG_REF_NAME"
foreach cell $registers {
    set name [get_property NAME $cell]
    set parsed [parsed_register $name]
    dict set mapped_register_metadata $name [list [get_property REF_NAME $cell] [cell_clocks $cell] $parsed]
    if {![llength $parsed]} {
        puts $unparsed "$name\t[get_property REF_NAME $cell]\t[property_or_na $cell ORIG_CELL_NAME]\t[property_or_na $cell ORIG_REF_NAME]"
        continue
    }
    lassign $parsed y x bank bit suffix
    set key "$y,$x,$bank"
    dict lappend bank_cells $key $name
    dict lappend bank_bits $key $bit
    set q [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == Q}]
    puts $inventory "$y\t$x\t$bank\t$bit\t$suffix\t$name\t[get_property REF_NAME $cell]\t[cell_clocks $cell]\t[property_or_na $q LOGIC_VALUE]\t[property_or_na $cell ORIG_CELL_NAME]\t[property_or_na $cell ORIG_REF_NAME]\t[property_or_na $cell LOC]\t[property_or_na $cell BEL]"
}
close $inventory
close $unparsed

set receiver_table [open "$out/receiver_drivers.tsv" w]
puts $receiver_table "y\tx\treceiver_bank\tcanonical_bit\treceiver_cell\tD_pin\tD_logic_value\tdirect_driver_pins\tdriver_classes\tdriver_clock_names\tfanin_startpoints\tfanin_status"
foreach cell $registers {
    set name [get_property NAME $cell]
    set parsed [parsed_register $name]
    if {![llength $parsed]} { continue }
    lassign $parsed y x bank bit suffix
    if {$bank != "row_q" && $bank != "col_q"} { continue }
    set wanted [expr {$bank == "row_q" ? "xr" : "xc"}]
    set dp [get_pins -quiet -of_objects $cell -filter {REF_PIN_NAME == D}]
    set drivers [direct_drivers $dp]
    set classes {}
    set clocks {}
    foreach driver $drivers {
        lappend classes [driver_class $driver $y $x $wanted $bit]
        set driver_cell_name [file dirname $driver]
        lassign [driver_metadata $driver] driver_ref driver_clock source_parsed
        lappend clocks "$driver_cell_name:$driver_clock"
        if {[llength $source_parsed] && [lindex $source_parsed 2] in {xr xc}} {
            dict set source_seen_as_driver $driver_cell_name 1
        }
    }
    set starts {}
    set fanin_status OK
    if {[catch {set starts [names [all_fanin -flat -startpoints_only -to $dp]]} reason]} {
        set fanin_status "ERROR:[string map [list \t { } \n { }] $reason]"
    }
    set direct_signature [join $drivers ,]
    dict lappend receiver_bit_drivers "$y,$x,$bank,$bit" $direct_signature
    dict lappend receiver_bit_classes "$y,$x,$bank,$bit" [join $classes ,]
    puts $receiver_table "$y\t$x\t$bank\t$bit\t$name\t[join [names $dp] ,]\t[property_or_na $dp LOGIC_VALUE]\t$direct_signature\t[join $classes ,]\t[join $clocks ,]\t[join $starts ,]\t$fanin_status"
}
close $receiver_table

set summary [open "$out/bank_summary.tsv" w]
puts $summary "y\tx\tbank\texpected_variant\tmapped_FD_LD_cells\tcanonical_bit_count\tmissing_bits\textra_mapped_cells\tsource_cells_seen_as_receiver_drivers\tstatus"
for {set y 0} {$y < $N} {incr y} {
    for {set x 0} {$x < $N} {incr x} {
        foreach bank {xr xc row_q col_q} {
            set key "$y,$x,$bank"
            set cells {}; set bits {}; set used 0
            if {[dict exists $bank_cells $key]} { set cells [dict get $bank_cells $key] }
            if {[dict exists $bank_bits $key]} { set bits [lsort -integer -unique [dict get $bank_bits $key]] }
            set missing {}
            for {set bit 0} {$bit < 32} {incr bit} {
                if {[lsearch -exact $bits $bit] < 0} { lappend missing $bit }
            }
            foreach cell $cells { if {[dict exists $source_seen_as_driver $cell]} { incr used } }
            set variant [expr {$bank in {xr row_q} ? 2 * $y : 2 * $x + 1}]
            set status [expr {[llength $missing] ? "REVIEW_MISSING_OR_RENAMED_BITS" : "NAMED_BANK_PRESENT"}]
            if {$bank in {xr xc} && $used != [llength $cells]} { append status ",REVIEW_UNUSED_OR_REPLICATED_STATE" }
            puts $summary "$y\t$x\t$bank\t$variant\t[llength $cells]\t[llength $bits]\t[join $missing ,]\t[expr {[llength $cells] - [llength $bits]}]\t$used\t$status"
        }
    }
}
close $summary

set signatures [dict create]
set signature_table [open "$out/receiver_bus_signatures.tsv" w]
puts $signature_table "y\tx\treceiver_bank\tcomplete_named_bits\tall_bits_have_one_same_tile_source\tdriver_signature"
for {set y 0} {$y < $N} {incr y} {
    for {set x 0} {$x < $N} {incr x} {
        foreach bank {row_q col_q} {
            set signature {}; set complete 1; set all_local 1; set resolved 1; set has_source 0
            for {set bit 0} {$bit < 32} {incr bit} {
                set key "$y,$x,$bank,$bit"
                if {![dict exists $receiver_bit_drivers $key]} {
                    lappend signature "$bit=MISSING"; set complete 0; set all_local 0; set resolved 0
                    continue
                }
                set drivers [lsort -unique [dict get $receiver_bit_drivers $key]]
                set classes [lsort -unique [dict get $receiver_bit_classes $key]]
                if {[llength $drivers] != 1 || [lindex $drivers 0] == ""} { set resolved 0 }
                foreach class $classes {
                    if {$class in {SAME_TILE_SOURCE CROSS_TILE_SOURCE WRONG_LOCAL_SOURCE_ROLE WRONG_LOCAL_SOURCE_BIT}} { set has_source 1 }
                }
                if {[llength $drivers] != 1 || [lindex $classes 0] != "SAME_TILE_SOURCE" || [llength $classes] != 1} { set all_local 0 }
                lappend signature "$bit=[join $drivers &]"
            }
            set signature [join $signature {;}]
            puts $signature_table "$y\t$x\t$bank\t$complete\t$all_local\t$signature"
            if {$complete && $resolved && $has_source} { dict lappend signatures $signature "$y,$x,$bank" }
        }
    }
}
close $signature_table
set aliases [open "$out/identical_driver_signatures.tsv" w]
puts $aliases "receiver_buses\tstatus\tdriver_signature"
dict for {signature buses} $signatures {
    if {[llength $buses] > 1} {
        puts $aliases "[join $buses { | }]\tSHARED_PHYSICAL_DRIVER_SIGNATURE_REQUIRES_REVIEW\t$signature"
    }
}
close $aliases
set scope [open "$out/scope.txt" w]
puts $scope "Checkpoint: $checkpoint"
puts $scope "N=$N; expected logical source roles=[expr {2*$N*$N}] (not an expected DSP count)."
puts $scope "All commands are read-only queries. No preservation, constraints, exceptions, implementation, or checkpoint writes were applied."
puts $scope "FD/LD name matches are inventoried; combinational *_i_* matches are excluded. Named counts are discovery evidence, not sole proof of physical source multiplicity."
puts $scope "Each named row_q/col_q D is checked for direct mapped drivers and all fanin startpoints. Same-tile source classification requires xr/xc role and tile-coordinate agreement."
puts $scope "A missing named bank may reflect renaming, constants, or merging and requires netlist review. Optional original-name properties are hints only."
puts $scope "Identical complete receiver driver signatures show physical sharing of their drivers; missing/unresolved signatures and buses with no source-register driver are excluded. Constants and other drivers are recorded explicitly."
puts $scope "A source state not seen as a direct named receiver driver requires review for an unused state, physical replica, or renamed/optimized receiver; it is not an automatic failure."
puts $scope "Expected variant is derived from RTL coordinates (row 2*y, column 2*x+1); this query does not prove mapped arithmetic equivalence."
close $scope
close_design
exit
