set scriptdir [file dirname [file normalize [info script]]]

source $scriptdir/xgetmapopts.tcl

if { [llength $argv] < 1 } {
    puts stderr "Usage: $argv0 <xise project>"
    exit
}
set projfile [lindex $argv 0]
set costtable [lindex $argv 1]
if {$costtable ne "" && (![string is integer -strict $costtable] || $costtable < 1 || $costtable > 100)} {
    error "Placer cost table must be between 1 and 100"
}

project open $projfile

puts [join [getmapopts $costtable]]
