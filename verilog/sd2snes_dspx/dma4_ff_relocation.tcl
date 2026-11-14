# A source-pinned physical move, not a logic rewrite.
# Tested only by the GitHub diagnostic before any production hook is enabled.
# Tcl 8.4 compatible: no dict, lassign, argument expansion or try.
# INPUT_XDL and ORIGINAL_BODY_SHA256 are read-only. OUTPUT_XDL must not exist.
proc need {value message} {
    if {!$value} { error $message }
}
proc readBinary {path} {
    set channel [open $path r]
    fconfigure $channel -translation binary -encoding binary
    set value [read $channel]
    close $channel
    return $value
}
proc writeExclusive {path value} {
    set channel [open $path {WRONLY CREAT EXCL}]
    fconfigure $channel -translation binary -encoding binary
    puts -nonewline $channel $value
    close $channel
}
proc replaceOnce {value before after label} {
    set where [string first $before $value]
    need [expr {$where >= 0}] "Missing exact token: $label"
    set again [string first $before $value [expr {$where + [string length $before]}]]
    need [expr {$again < 0}] "Ambiguous exact token: $label"
    return [string replace $value $where [expr {$where + [string length $before] - 1}] $after]
}
proc record {value kind name} {
    set prefix "$kind \"$name\" "
    set start [string first $prefix $value]
    need [expr {$start >= 0}] "Missing exact record: $kind $name"
    set duplicate [string first $prefix $value [expr {$start + [string length $prefix]}]]
    need [expr {$duplicate < 0}] "Duplicate exact record: $kind $name"
    set end [string first ";" $value $start]
    need [expr {$end > $start}] "Incomplete exact record: $kind $name"
    return [string range $value $start $end]
}
proc canonicalBody {value} {
    set padded "\n$value"
    set start [string first "\ndesign " $padded]
    need [expr {$start >= 0}] "Missing line-start design record"
    set prefix [string range $padded 0 $start]
    foreach line [split $prefix "\n"] {
        set line [string trim $line]
        need [expr {[string length $line] == 0 || [string index $line 0] == "#"}] "Unknown pre-design content"
    }
    # Preserve every body byte, including configuration, net data and order.
    # Only external leading comments and trailing whitespace are outside the pin.
    return [string trim [string range $padded [expr {$start + 1}] end]]
}
proc main {arguments} {
    need [expr {[llength $arguments] == 3}] "Usage: INPUT_XDL NEW_OUTPUT_XDL ORIGINAL_BODY_SHA256_FILE"
    set input [lindex $arguments 0]
    set output [lindex $arguments 1]
    set manifest [lindex $arguments 2]
    need [expr {[file normalize $input] != [file normalize $output]}] "Output must differ from original input"
    need [expr {![file exists $output]}] "Output already exists"
    need [expr {[file size $input] > 0 && [file size $input] <= 8000000}] "Input size outside reviewed bound"
    set expected [string trim [readBinary $manifest]]
    need [regexp {^[0-9a-f]{64}$} $expected] "Invalid original body fingerprint"
    set original [readBinary $input]
    set body [canonicalBody $original]
    set temporary "$output.canonical-[pid]"
    writeExclusive $temporary $body
    set status [catch {exec sha256sum -- $temporary} measured]
    file delete $temporary
    need [expr {$status == 0}] "Direct sha256sum failed: $measured"
    need [regexp {^([0-9a-f]{64})[ \t]} $measured ignore actual] "Unrecognized sha256sum output"
    need [expr {$actual == $expected}] "Complete original design-body fingerprint mismatch"

    set source "snes_dma/dma_r_4_1"
    set destination "snes_mcu_cmd/N185"
    set oldSource [record $original inst $source]
    set oldDestination [record $original inst $destination]
    need [expr {[string first {,placed R11C15 SLICE_X29Y42} $oldSource] >= 0}] "Original source placement mismatch"
    need [expr {[string first {,placed R13C16 SLICE_X31Y39} $oldDestination] >= 0}] "Original destination placement mismatch"
    # Every transferred field is explicit. Preserve both ordinary co-packed LUTs,
    # their output muxes and every carry/wide-mux/configuration property.
    set fields {
        {BXINV::BX BXINV::#OFF}
        {BYINV::BY BYINV::#OFF}
        {CEINV::CE CEINV::#OFF}
        {CLKINV::CLK CLKINV::#OFF}
        {DXMUX::0 DXMUX::#OFF}
        {DYMUX::0 DYMUX::#OFF}
        {FFX:snes_dma/dma_r_4_1:#FF FFX::#OFF}
        {FFX_INIT_ATTR::INIT0 FFX_INIT_ATTR::#OFF}
        {FFX_SR_ATTR::SRLOW FFX_SR_ATTR::#OFF}
        {FFY:snes_dma/dma_r_4_6:#FF FFY::#OFF}
        {FFY_INIT_ATTR::INIT0 FFY_INIT_ATTR::#OFF}
        {FFY_SR_ATTR::SRLOW FFY_SR_ATTR::#OFF}
        {SRINV::SR SRINV::#OFF}
        {SYNC_ATTR::SYNC SYNC_ATTR::#OFF}
    }
    set newSource $oldSource
    set newDestination $oldDestination
    foreach pair $fields {
        set active [lindex $pair 0]
        set unused [lindex $pair 1]
        set newSource [replaceOnce $newSource $active $unused "source $active"]
        set newDestination [replaceOnce $newDestination $unused $active "destination $unused"]
    }
    set edited [replaceOnce $original $oldSource $newSource "source component"]
    set edited [replaceOnce $edited $oldDestination $newDestination "destination component"]
    set pins {
        {BUS_DATA<1> inpin BX}
        {BUS_DATA<6> inpin BY}
        {CLK2 inpin CLK}
        {SNES_reset_strobe inpin SR}
        {snes_dma/dma_r_4_not0001 inpin CE}
        {snes_dma/dma_r_4_1 outpin XQ}
        {snes_dma/dma_r_4_6 outpin YQ}
    }
    foreach row $pins {
        set name [lindex $row 0]
        set direction [lindex $row 1]
        set pin [lindex $row 2]
        set before [record $edited net $name]
        need [expr {[string first "pip " $before] < 0}] "Affected net has pre-existing routing: $name"
        set after [replaceOnce $before "$direction \"$source\" $pin " "$direction \"$destination\" $pin " "net $name"]
        set edited [replaceOnce $edited $before $after "whole net $name"]
    }
    # Source bytes are never overwritten. Full graph conservation and conversion
    # legality are checked independently by the hosted validator.
    writeExclusive $output $edited
    puts "TCL_VERSION=[info patchlevel]"
    puts "SOURCE_BODY_SHA256=$actual"
    puts "DECLARED_COMPONENTS=2 DECLARED_NETS=7 MOVED_FF_BITS=2"
}
if {[catch {main $argv} failure]} {
    puts stderr $failure
    puts stderr $::errorInfo
    exit 1
}
exit 0
