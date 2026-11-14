# Write options to files: project open also prints status text on stdout.
if {[llength $argv] != 2} {
    error "Usage: gbc-remap-options.tcl <repository root> <output directory>"
}
set root_dir [file normalize [lindex $argv 0]]
set output_dir [file normalize [lindex $argv 1]]
source [file join $root_dir verilog xilinx_scripts xgetmapopts.tcl]
source [file join $root_dir verilog xilinx_scripts xgetparopts.tcl]
project open [file join $root_dir verilog sd2snes_gbc sd2snes_gbc.xise]
foreach {kind options} [list map [getmapopts] par [getparopts]] {
    set stream [open [file join $output_dir "$kind.options"] w]
    puts $stream [join $options]
    close $stream
}
project close
