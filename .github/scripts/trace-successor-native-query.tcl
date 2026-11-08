# Hosted diagnostic only. Source the original option query exactly once.
# Uses Tcl 8.4 documented catch/uplevel/return forms; runtime version is retained.
set ::dsp_diag_version_file [open /diagnostic/runtime-version.txt {WRONLY CREAT EXCL}]
puts $::dsp_diag_version_file [info patchlevel]
puts $::dsp_diag_version_file [info tclversion]
close $::dsp_diag_version_file
if {![regexp {^8\.[456](\.[0-9]+)?$} [info patchlevel]] || ![string equal [join [lrange [split [info patchlevel] .] 0 1] .] [info tclversion]]} {
    error "Unsupported observed Tcl version; no original project query executed"
}
set ::dsp_diag_trace [open /diagnostic/wrapper-controls.trace.tsv {WRONLY CREAT EXCL}]
set ::dsp_diag_marker_channel [open /diagnostic/wrapper-controls.markers.txt {WRONLY CREAT EXCL}]
fconfigure $::dsp_diag_trace -encoding ascii -translation lf
set ::dsp_diag_seq 0
set ::dsp_diag_phase control
proc dsp_diag_log {kind args} {
    set fields [list $kind]
    foreach value $args {
        binary scan [encoding convertto utf-8 $value] H* encoded
        lappend fields $encoded
    }
    set line [join $fields "\t"]
    if {[expr {[tell $::dsp_diag_trace] + [string length $line] + 1}] > 3000000} {
        error "Diagnostic trace exceeds declared complete-file bound"
    }
    puts $::dsp_diag_trace $line
    flush $::dsp_diag_trace
}
proc dsp_diag_marker {kind number phase} {
    puts $::dsp_diag_marker_channel "SD2SNES_QUERY_V1|$kind|$number|$phase"
    flush $::dsp_diag_marker_channel
}
rename ::project ::dsp_diag_vendor_project
proc ::project {args} {
    incr ::dsp_diag_seq
    set number $::dsp_diag_seq
    set phase $::dsp_diag_phase
    if {$number > 128} {error "Diagnostic project command count exceeded"}
    dsp_diag_log CALL $number $phase [llength $args]
    set index 0
    foreach value $args {
        dsp_diag_log ARG $number $index $value
        incr index
    }
    dsp_diag_marker BEGIN $number $phase
    # Same caller frame and exact argument list. No command/result rewriting.
    set code [catch {uplevel 1 [linsert $args 0 ::dsp_diag_original_project]} result]
    set savedInfo ""
    set savedCode ""
    if {$code == 1} {
        set savedInfo $::errorInfo
        set savedCode $::errorCode
    }
    dsp_diag_log RETURN $number $code $result $savedCode $savedInfo
    if {$code == 0 && [string equal [lindex $args 0] properties]} {
        dsp_diag_log LIST $number [llength $result]
        set index 0
        foreach value $result {
            dsp_diag_log ITEM $number $index $value
            incr index
        }
    }
    dsp_diag_marker END $number $phase
    if {$code == 1} {
        return -code error -errorcode $savedCode -errorinfo $savedInfo $result
    }
    if {$code != 0} {
        return -code error -errorcode [list SD2SNES DIAGNOSTIC UNSUPPORTED_COMPLETION $code] "Unsupported project completion code $code; original result retained in trace"
    }
    return $result
}
# Exercise this exact wrapper without calling any vendor project operation.
proc ::dsp_diag_original_project {args} {
    set action [lindex $args 0]
    switch -exact -- $action {
        value {return "normal result with spaces"}
        properties {return [list "first property" "second\tproperty"]}
        scope {return [uplevel 1 {set caller_local}]}
        error {return -code error -errorcode {DIAG SENTINEL} -errorinfo "exact error-info sentinel" "exact error-result sentinel"}
        code2 {return -code 2 "unsupported result 2"}
        code3 {return -code 3 "unsupported result 3"}
        code4 {return -code 4 "unsupported result 4"}
        code5 {return -code 5 "unsupported result 5"}
        default {error "Unknown synthetic delegate action"}
    }
}
proc dsp_diag_assert {condition label} {
    if {!$condition} {error "Wrapper hosted control failed: $label"}
    dsp_diag_log CONTROL $label pass
}
dsp_diag_assert [string equal [project value] "normal result with spaces"] normal-result
dsp_diag_assert [string equal [project properties] [list "first property" "second\tproperty"]] list-result
proc dsp_diag_scope_control {} {
    set caller_local "exact caller-local value"
    return [project scope]
}
dsp_diag_assert [string equal [dsp_diag_scope_control] "exact caller-local value"] caller-scope
set ::dsp_diag_code [catch {project error} ::dsp_diag_result]
set ::dsp_diag_info $::errorInfo
set ::dsp_diag_error $::errorCode
dsp_diag_assert [expr {$::dsp_diag_code == 1 && [string equal $::dsp_diag_result "exact error-result sentinel"] && [string equal $::dsp_diag_error {DIAG SENTINEL}] && [string first "exact error-info sentinel" $::dsp_diag_info] == 0}] error-preservation
foreach ::dsp_diag_unsupported {2 3 4 5} {
    set ::dsp_diag_code [catch {project code$::dsp_diag_unsupported} ::dsp_diag_result]
    set ::dsp_diag_error $::errorCode
    dsp_diag_assert [expr {$::dsp_diag_code == 1 && [string equal $::dsp_diag_error [list SD2SNES DIAGNOSTIC UNSUPPORTED_COMPLETION $::dsp_diag_unsupported]]}] unsupported-$::dsp_diag_unsupported
}
dsp_diag_log CONTROLS_COMPLETE 8
close $::dsp_diag_trace
close $::dsp_diag_marker_channel
rename ::dsp_diag_original_project {}
rename ::dsp_diag_vendor_project ::dsp_diag_original_project
set ::dsp_diag_trace [open /diagnostic/query.trace.tsv {WRONLY CREAT EXCL}]
fconfigure $::dsp_diag_trace -encoding ascii -translation lf
set ::dsp_diag_marker_channel stderr
set ::dsp_diag_seq 0
set ::dsp_diag_phase original
dsp_diag_log VERSION [info patchlevel] [info tclversion] [pwd]
dsp_diag_log START /work/verilog/xilinx_scripts/xgenparcmd.tcl sd2snes_dspx.xise 68
foreach ::dsp_diag_env {ISE_CTABLE LC_ALL LANG JAVA_OPTS _JAVA_OPTIONS XILINX XILINX_EDK XILINX_DSP XILINX_PLANAHEAD XILINX_PATH XILINXD_LICENSE_FILE LD_LIBRARY_PATH PATH MAKEFILES MAKEFLAGS GNUMAKEFLAGS MFLAGS MAKEOVERRIDES MAKELEVEL MAKE_RESTARTS HOST XILINX_ENV IGNORE_TIMING} {
    set ::dsp_diag_exists [info exists ::env($::dsp_diag_env)]
    set ::dsp_diag_value ""
    if {$::dsp_diag_exists} {set ::dsp_diag_value $::env($::dsp_diag_env)}
    dsp_diag_log ENV $::dsp_diag_env $::dsp_diag_exists $::dsp_diag_value
}
if {[info exists ::env(GH_TOKEN)] || [info exists ::env(GITHUB_TOKEN)]} {
    error "Host credential must not enter diagnostic container"
}
set argv [list sd2snes_dspx.xise 68]
set argc 2
set argv0 /work/verilog/xilinx_scripts/xgenparcmd.tcl
set ::dsp_diag_source_code [catch {source /work/verilog/xilinx_scripts/xgenparcmd.tcl} ::dsp_diag_source_result]
set ::dsp_diag_source_info ""
set ::dsp_diag_source_error ""
if {$::dsp_diag_source_code == 1} {
    set ::dsp_diag_source_info $::errorInfo
    set ::dsp_diag_source_error $::errorCode
}
dsp_diag_log SOURCE $::dsp_diag_source_code $::dsp_diag_source_result $::dsp_diag_source_error $::dsp_diag_source_info
if {$::dsp_diag_source_code != 0} {
    dsp_diag_log END failure $::dsp_diag_seq
    close $::dsp_diag_trace
    exit 71
}
# These additional reads never change a property or reopen the project.
# The original source phase and its stdout remain separately identifiable.
set ::dsp_diag_phase probe
set ::dsp_diag_names [list "Placer Effort Level" "Placer Effort Level (Overrides Overall Level)" "Router Effort Level" "Router Effort Level (Overrides Overall Level)" "Place & Route Effort Level (Overall)"]
foreach ::dsp_diag_name $::dsp_diag_names {
    dsp_diag_log MEMBERSHIP $::dsp_diag_name [existsParProp $::dsp_diag_name]
}
set ::dsp_diag_probes [list \
    [list properties -process "Place & Route"] \
    [list properties] \
    [list get "Placer Effort Level"] \
    [list get "Placer Effort Level (Overrides Overall Level)" -process "Place & Route"] \
    [list get "Router Effort Level"] \
    [list get "Router Effort Level (Overrides Overall Level)" -process "Place & Route"] \
    [list get "Place & Route Effort Level (Overall)" -process "Place & Route"] \
    [list get "Extra Effort (Highest PAR level only)" -process "Place & Route"] \
    [list get "Starting Placer Cost Table (1-100)" -process "Place & Route"] \
    [list get "Ignore User Timing Constraints" -process "Place & Route"] \
    [list get "Other Place & Route Command Line Options"]]
set ::dsp_diag_probe_failures 0
set ::dsp_diag_probe_index 0
foreach ::dsp_diag_command $::dsp_diag_probes {
    set ::dsp_diag_code [catch {eval [linsert $::dsp_diag_command 0 project]} ::dsp_diag_result]
    dsp_diag_log PROBE $::dsp_diag_probe_index $::dsp_diag_code $::dsp_diag_result
    if {$::dsp_diag_code != 0} {incr ::dsp_diag_probe_failures}
    incr ::dsp_diag_probe_index
}
if {$::dsp_diag_probe_failures != 0} {
    dsp_diag_log END failure $::dsp_diag_seq
    close $::dsp_diag_trace
    exit 72
}
dsp_diag_log END complete $::dsp_diag_seq
close $::dsp_diag_trace
exit 0
