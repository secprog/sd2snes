# Source-pinned DSPX-only post-MAP two-register physical relocation.
# All controls, conversion checks and fresh-MAP reproduction must run on GitHub.
# No PAR/TRCE options/status/deletion, timing constraint or RTL change.
proc require {ok message} { if {!$ok} { error $message } }
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
proc runTool {directory label words} {
    set out [open [file join $directory "$label.stdout.log"] {WRONLY CREAT EXCL}]
    set err [open [file join $directory "$label.stderr.log"] {WRONLY CREAT EXCL}]
    fconfigure $out -translation binary -encoding binary
    fconfigure $err -translation binary -encoding binary
    writeExclusive [file join $directory "$label.command.txt"] "$words\n"
    set command [concat [list exec] $words [list >@ $out 2>@ $err]]
    set status [catch {eval $command} message]
    set code 0
    set errorCodeValue {}
    if {$status != 0} {
        set errorCodeValue $::errorCode
        set code -1
        if {[lindex $errorCodeValue 0] == "CHILDSTATUS"} {
            set code [lindex $errorCodeValue 2]
        }
    }
    close $out
    close $err
    writeExclusive [file join $directory "$label.exit.txt"] "catch=$status native=$code errorCode=$errorCodeValue\n"
    require [expr {$status == 0 && $code == 0}] "Direct tool failed: $label catch=$status native=$code $message"
    return [readBinary [file join $directory "$label.stdout.log"]]
}
proc hashFile {directory label path} {
    set output [runTool $directory $label [list sha256sum -- $path]]
    require [regexp {^([0-9a-f]{64})[ \t]} $output ignore digest] "Unexpected full sha256sum output"
    return $digest
}
proc canonicalBody {value} {
    set padded "\n$value"
    set start [string first "\ndesign " $padded]
    require [expr {$start >= 0}] "Missing design record"
    set prefix [string range $padded 0 $start]
    foreach line [split $prefix "\n"] {
        set line [string trim $line]
        require [expr {[string length $line] == 0 || [string index $line 0] == "#"}] "Unrecognized pre-design content"
    }
    return [string trim [string range $padded [expr {$start + 1}] end]]
}
proc hashBody {directory label path} {
    set canonical [file join $directory "$label.canonical"]
    writeExclusive $canonical [canonicalBody [readBinary $path]]
    return [hashFile $directory "$label-body-sha256" $canonical]
}
proc loadPins {path} {
    set allowed {ORIGINAL_BODY_SHA256 RELOCATED_BODY_SHA256 ORIGINAL_PCF_SHA256 PATCH_SCRIPT_SHA256}
    array set pins {}
    foreach line [split [readBinary $path] "\n"] {
        if {[string length [string trim $line]] == 0} { continue }
        require [regexp {^([A-Z0-9_]+) ([0-9a-f]{64})$} $line ignore key value] "Malformed physical manifest"
        require [expr {[lsearch -exact $allowed $key] >= 0}] "Unexpected physical manifest key"
        require [expr {![info exists pins($key)]}] "Duplicate physical manifest key"
        set pins($key) $value
    }
    require [expr {[array size pins] == 4}] "Incomplete physical manifest"
    return [array get pins]
}
proc main {arguments} {
    require [expr {[llength $arguments] == 4}] "Usage: XILINX_BIN ORIGINAL_NCD ORIGINAL_PCF PIN_MANIFEST"
    set toolbin [file normalize [lindex $arguments 0]]
    set ncd [file normalize [lindex $arguments 1]]
    set pcf [file normalize [lindex $arguments 2]]
    set manifest [file normalize [lindex $arguments 3]]
    set project [file dirname $ncd]
    require [expr {[file tail $ncd] == "main_map.ncd" && [file tail $pcf] == "main.pcf"}] "Unexpected mapped filenames"
    require [expr {[file dirname $pcf] == $project && [file normalize [pwd]] == $project}] "Unexpected project/input directory"
    require [expr {[file type $ncd] == "file" && [file type $pcf] == "file"}] "Mapped inputs must be regular files"
    require [expr {[file size $ncd] > 0 && [file size $ncd] <= 8000000}] "Mapped input size outside bound"
    require [expr {[info patchlevel] == "8.4.14"}] "Unreviewed runtime Tcl version"
    array set pins [loadPins $manifest]
    set patcher [file join $project dma4_ff_relocation.tcl]
    require [expr {[file type $patcher] == "file"}] "Missing regular pinned patch script"

    set parent [file join $project .dma4-ff-relocation]
    if {[file exists $parent]} {
        require [expr {[file type $parent] == "directory"}] "Physical evidence parent must be an ordinary directory"
    } else { file mkdir $parent }
    set generation [file join $parent "generation-[pid]-[clock clicks]"]
    require [expr {![file exists $generation]}] "Physical evidence generation already exists"
    file mkdir $generation
    writeExclusive [file join $generation ownership.txt] "DSPX physical conversion only; Tcl=[info patchlevel]\n"
    puts "DSPX_FF_RELOCATION_GENERATION=$generation"

    set originalNcdSha [hashFile $generation original-ncd $ncd]
    set originalPcfSha [hashFile $generation original-pcf $pcf]
    require [expr {$originalPcfSha == $pins(ORIGINAL_PCF_SHA256)}] "Complete original PCF fingerprint mismatch"
    require [expr {[hashFile $generation patch-script $patcher] == $pins(PATCH_SCRIPT_SHA256)}] "Complete patch script fingerprint mismatch"
    file copy $ncd [file join $generation original.ncd]
    file copy $pcf [file join $generation original.pcf]
    require [expr {[hashFile $generation saved-original-ncd [file join $generation original.ncd]] == $originalNcdSha}] "Original NCD backup mismatch"
    require [expr {[hashFile $generation saved-original-pcf [file join $generation original.pcf]] == $originalPcfSha}] "Original PCF backup mismatch"
    set originalXdl [file join $generation original.xdl]
    runTool $generation original-export [list [file join $toolbin xdl] -ncd2xdl $ncd $originalXdl]
    require [expr {[hashBody $generation original $originalXdl] == $pins(ORIGINAL_BODY_SHA256)}] "Fresh MAP complete design-body fingerprint mismatch"
    set originalPin [file join $generation original-body.sha256]
    writeExclusive $originalPin "$pins(ORIGINAL_BODY_SHA256)\n"
    set movedXdl [file join $generation moved.xdl]
    runTool $generation patch [list [file join $toolbin xtclsh] $patcher $originalXdl $movedXdl $originalPin]
    set convertedNcd [file join $generation converted.ncd]
    runTool $generation import [list [file join $toolbin xdl] -xdl2ncd $movedXdl $convertedNcd]
    set convertedXdl [file join $generation converted.xdl]
    runTool $generation converted-export [list [file join $toolbin xdl] -ncd2xdl $convertedNcd $convertedXdl]
    require [expr {[hashBody $generation converted $convertedXdl] == $pins(RELOCATED_BODY_SHA256)}] "Converted complete relocated design-body fingerprint mismatch"
    set convertedSha [hashFile $generation converted-ncd $convertedNcd]
    require [expr {[hashFile $generation precommit-original-ncd $ncd] == $originalNcdSha}] "Original mapped NCD changed before install"
    require [expr {[hashFile $generation precommit-original-pcf $pcf] == $originalPcfSha}] "Original PCF changed before install"
    # Keep exact originals and all full tool streams. The only installed change
    # is the independently graph-verified converted mapped NCD.
    set installStatus [catch {
        file rename -force $convertedNcd $ncd
        require [expr {[hashFile $generation installed-ncd $ncd] == $convertedSha}] "Installed mapped NCD differs from checked conversion"
        require [expr {[hashFile $generation final-pcf $pcf] == $originalPcfSha}] "PCF changed during install"
    } installFailure]
    if {$installStatus != 0} {
        set restoreStatus [catch {
            file copy -force [file join $generation original.ncd] $ncd
            require [expr {[hashFile $generation restored-ncd $ncd] == $originalNcdSha}] "Restored original NCD fingerprint mismatch"
        } restoreFailure]
        error "Mapped NCD install failed; original restore status=$restoreStatus: $installFailure; $restoreFailure"
    }
    writeExclusive [file join $generation result.txt] "originalNcdSha256=$originalNcdSha\nrelocatedNcdSha256=$convertedSha\noriginalPcfSha256=$originalPcfSha\noriginalBodySha256=$pins(ORIGINAL_BODY_SHA256)\nrelocatedBodySha256=$pins(RELOCATED_BODY_SHA256)\nnoTimingResult=true\n"
    puts "DSPX_FF_RELOCATION_INSTALLED=2FF_2COMP_7NET_TIMING_UNVERIFIED"
}
if {[catch {main $argv} failure]} {
    puts stderr $failure
    puts stderr $::errorInfo
    exit 1
}
exit 0
