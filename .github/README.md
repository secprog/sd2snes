# Firmware builds

`build-firmware.yml` runs on GitHub-hosted Ubuntu runners for pushes, pull
requests, and manual runs from the Actions tab. It uses public container images;
no installer URLs or repository secrets need to be configured.

The independent **Build SNES menus and onboarding** job builds and checks both
board menus, the in-game menu, onboarding, and language assets. Its `menus`
artifact is available without waiting for either FPGA build.
Select `build: menus` for a manual menu-only run.
European Portuguese is a separate language choice, `Português (Portugal)`;
existing language selections retain their saved IDs. Identical strings and
complete string suffixes share ROM storage so the additional locale fits the
existing menu banks.
The build packs repeated 1 KB onboarding picture blocks once and verifies all
linked pictures and palette/OAM records against the original bytes. This leaves
room for the additional tour language without changing the pictures or ROM size.

For software checks, manually select `build: software` and supply the
run ID containing a successful `fpga-mk3` artifact. This mode checks that the
artifact's Verilog sources match the current checkout. It builds only the small
MkII bootstrap FPGA image, then checks all three MCU configurations and menus
on GitHub-hosted runners. Supply `mk2_run_id` to reuse an existing
`fpga-mk2-mini` artifact after the same source verification, skipping that build.
MkIII LPC and STM32 stay non-LTO; MkII retains its existing LTO setting.
Compiler versions, full command lines, maps and binaries are uploaded.
The normal software check uses the same cached container as release packaging.

Full runs produce three independent firmware jobs and ZIPs: `mk2`, `mk3`
(LPC), and `mk3-stm32`. Each ZIP contains only its board's MCU firmware, menu,
FPGA images and matching card modules. MkIII LPC and STM32 use the same `.bi3`
images, compiled once and included in both packages. STM32 remains non-LTO.
Manual full runs can select one board with `release_target`; `mk3-both` builds
the two separate MkIII packages with one shared FPGA matrix. The default `all`
builds all three packages. Board selections have independent concurrency groups.

Every FPGA core has its own hosted-runner job, with up to 12 running at once.
The matrix comes from `MK2CORES` and `MK3CORES` in the root Makefile, plus mini.
A coverage check compares those lists with the core directories and explicit
board exclusions, so adding a core cannot silently leave it out of CI.

| FPGA target | Runtime cores (mini is built and packaged in addition) |
| --- | --- |
| MkII (19) | base, basex, bootleg, col20, cx4, dsp, dspx, gsu, gsu3, obc1, sa1, sdd1, sgb, sgb_msu, spc7110, st0011, st0018, test, xc |
| MkIII LPC / STM32 (23) | a26, base, bootleg, col20, cx4, dsp, gbc, gsu, gsu3, nes, nes_k, nes_mmc3, nes_mmc5, obc1, sa1, sdd1, sgb, sms, spc7110, st0011, st0018, test, xc |

MkII uses separate `basex` and `dspx` images for extended mappers and competition
carts, and separate SGB feature variants. MkIII includes those mapper features
in its base/DSP images and uses one SGB image. NES, SMS, Atari and GBC loaders
are MkIII-only; legacy NES/SMS ISE project files do not enable their MkII MCU
loaders. Other board-specific feature and timing settings are retained.

Complete board sets are verified before publishing `fpga-mk2` / `fpga-mk3`
artifacts. Packaging checks the ZIP's exact FPGA list, MCU file and menu,
rejecting missing cores or files from the wrong board. The MkII mini image is
also copied to the SD-card package because its boot diagnostics load it from
the card. Core logs, utilization and timing reports are retained on success
and failure; a failed core cannot cancel the other core jobs.
For a focused retry, select `build: fpga` and set `fpga_cores` to targets such as
`mk2:sgb,mk2:sgb_msu,mk2:gsu`. This builds only those cores without packaging or
cancelling a full release run. Leave that field empty to check all FPGA cores.
`placement_seeds` optionally tests several MkII map/PAR cost tables in parallel
(for example `2,3,4`). Seed trials publish separate images and reports; normal
release builds use the settings committed in each ISE project.
Every MkII implementation generates a detailed TRACE report, including hold paths
and paths not covered by the existing constraints. Missing reports, report errors
and timing violations are build failures; CI explicitly sets `IGNORE_TIMING=0` on
both FPGA targets.
These reports describe the committed timing model, not hardware qualification.
Legacy MkII cores with no explicit DCM jitter budget or I/O delays still require
separate timing-budget review and hardware validation, even with Timing Score 0.
SMS verifies its actual clock-enable RTL over the complete accumulator period.
Only paths between TV80 registers reached through physical enable pins receive
a conservative two-cycle setup exception (enables are at least 26 clocks apart),
with the corresponding hold correction. Other paths keep their normal timing.

The default `make all` still creates a combined release. `make release
RELEASE_BOARD=mk2`, `mk3` or `mk3-stm32` packages already-built files for a
single board. These commands do not bypass FPGA timing or synthesis guards.

`Compare CX4 RTL timing` is a manual diagnostic workflow. It compares the current
`cx4.v` and `main.v` with both files from sttng's ST0011/ST0018/COL20 reference,
pinned to commit `4c46d18a5b18778e5e3a1f082323e5aacf531447` and verified by their
Git blob hashes. These two variants use the current ISE project and seeds 1 and
46. A fifth job uses both reference RTL files and the reference ISE project, with
its original seed 3. All five use the same cached ISE, unchanged UCF, current
build scripts and strict timing checks. The artifacts contain the source and
tool-image provenance, generated synthesis settings, intermediate-file checksums,
timing and utilization reports. They are separate from release artifacts and do
not publish reference firmware images.

`Compare basex cheat decoder timing` is a separate manual diagnostic. It prepares
an explicit six-slot case decoder from a verified `cheat.v` source blob, leaving
the production RTL unchanged. Before either FPGA job can run, Yosys must prove
every equivalence cell for the complete module with undefined-state modelling
(`equiv_simple`, `equiv_induct`, `equiv_status -assert`). Before induction, every
register bit, clock edge and initial value must match. Uninitialized bits remain
arbitrary; they are never replaced with zeros. The proof job uses Ubuntu 24.04's
Yosys with lossless JSON initializers, and rejects numeric initializer encodings.
Clock enables and synchronous resets are normalized into input muxes before the
audit; register clocks and boundaries must still match. This state audit and the restriction
to a clocked programming block provide the initial relation required by the
induction check; all combinational outputs remain unchanged. The same checker must
reject a deliberately incorrect write-data mutation. The original and candidate then
use the same ISE project, constraints and seed 46. Only proof inputs and reports
are uploaded; no diagnostic bitstreams enter a release. All verification and
compilation in this workflow runs on GitHub-hosted runners.

`Compare CX4 GPR bank timing` verifies three 16-byte banks in place of the original
48-byte GPR array. XST reports 384 flip-flops for the original array. The source generator
checks the complete original `cx4.v` blob and accounts for every GPR access. CPU
write priority, frozen MMIO restores, byte order, out-of-range reads/writes and
the existing registered bus read are included in the extracted component proof.
No other CPU logic or project/clock constraints change.

The proof audits all 392 state bits (384 GPR bits and the 8-bit bus register),
their positive clock edge and absence of initialization. It then cuts every DFF
after memory lowering with explicit bounds/undefined-access modelling and no
read-port widening (`memory -nowiden -memx`). This retains the 48-byte boundary
and the bus output register instead of padding the model to 64 bytes. The cut is
at Q/D, sharing the complete current state as symbolic inputs and comparing all
next-state bits and CPU reads with combinational SAT. This establishes one-step
equivalence for every common binary state and every binary input combination,
including simultaneous CPU/MMIO writes and invalid byte addresses. Uninitialized
storage is arbitrary, never forced to zero. Undefined out-of-range outputs must
match strictly; there is no `ignore_gold_x`, reset assumption or bounded-trace
shortcut. Data corruption and wrong write-priority mutations must both produce
counterexamples. This is a component proof tied to the exact source changes,
not a whole-CX4 equivalence or hardware qualification claim. Only after it passes
do the original and candidate run native ISE with the same seed 1 and strict
PAR/TRACE gates. All models and reports remain diagnostic artifacts.
The RAM coding references are AMD UG627, pages 133 and 144–150;
the proof uses Yosys 0.33's strict miter comparison and SAT failure checks.
The byte-to-bank address decoder uses an explicit combinational table because
XST only supports division/remainder by powers of two (UG627 pages 128 and 491).
The complete proof is repeated when this decoder changes. The original source
is fetched from pinned commit `b52dd4568a5cb9e7ec390c0c5be5aa17ed008dce`,
independently blob-checked, and its generated candidate must match the current
production source byte for byte. `include_original` defaults to false because
the unchanged control has already been measured.
`synthesis_goal` selects Area or Speed (the default) in the diagnostic runner's
ISE project. It changes only that XST property and records the resulting project
and source hashes. The banked Area/seed-1 trial reduced native use from 7010 to
5418 LUTs and 3576 to 3162 slices, but still failed timing with 240 errors and
-2.502 ns worst setup slack. This new capacity margin motivates a bounded Speed
trial; the original unbanked Speed design exceeded capacity. Neither variant is
promoted into production without passing native timing and integration.
Banked XST Speed with Balanced mapping subsequently used 5539 LUTs and 3146
slices, with 153 setup errors and -1.951 ns worst slack. The `map_goal` input
allows a separate bounded Speed cover-mode trial while preserving the same
source, synthesis, seed and constraints. [AMD UG628, page 88](https://docs.amd.com/api/khub/documents/OxIb6JgZldFkcqM0jPOm9A/content)
documents that Speed prioritizes fewer LUT levels after timing, while Balanced
prioritizes fewer LUTs. The measured free capacity permits testing that tradeoff;
neither setting is assumed to close timing.

The banked XST Speed / MAP Speed / seed-1 configuration passed
[run 40525574671](https://github.com/secprog/sd2snes/actions/runs/40525574671)
with PAR score 0 and TRACE reporting zero setup/hold errors. It used 5575 LUTs,
3236 slices and the same 16 block RAMs. Minimum reported setup slack was
+0.007 ns and hold slack +0.433 ns under the unchanged constraints. This exact
proved source and ISE project configuration are now the production defaults;
`map_goal` also defaults to Speed. The diagnostic compares those defaults with
the pinned original source when requested. The very small setup margin and the
legacy constraint coverage still require separate hardware qualification.
The shared source subsequently passed MkIII integration in run 40529045613.

The passing CX4 PAR report also says three timing constraints were not applied.
TRACE reports zero data paths for TS_CLKIN, TS_SNES_SYSCLK and TS_DAC2; the
first two still have component pulse/period checks, and the derived internal
clocks have analyzed paths. This correspondence alone does not establish why
PAR reports three unapplied constraints or whether all intended paths are
covered. The optional `audit_tsi` input runs a separate post-route TRACE
timing-specification interaction report on the exact routed design (UG628
page 184). It preserves and checksums the original NCD, PCF and detailed TWR;
no constraint is changed or waived.

The resulting report in run 40555618424 shows that the existing TS_DAC
constraint takes precedence for 3406 paths otherwise covered by TS_CLK21.
It also reports an overlap between TS_SNES_SYSCLK and TS_CLK21 on the first
DAC sysclk sampler. NGDBUILD identifies both derived DCM clocks from TS_CLKIN,
which is consistent with UG612 page 37 explaining why the original translated
clock constraint reports zero data paths. TS_DAC2 is explicitly reported as
ignored, but its cause is not established by the interaction report.
NGDBUILD additionally warns that 35 specified DAC-group FF names were not
found; whether the affected paths are covered elsewhere must be investigated.
These observations do not establish input, output or hardware timing coverage.

The source model is checked before memory lowering. Yosys `memory_map` leaves
the nonexistent 48..63 read-mux leaves undriven; those become explicit X values
with `setundef -undriven -undef`, and the lowered model is checked again. This
does not initialize storage or turn undefined output values into don't-care
comparison masks.

The **Compare DSPx stack bank timing** diagnostic targets the measured
freeze-to-stack write-enable path. The original DSPx seed 68 has 13 setup
errors, -0.206 ns worst slack and 0.339 ns clock uncertainty. The runner-only
candidate separates each 11-bit stack word into 8-bit and 3-bit lanes with
one write address per lane, using the distributed-RAM coding pattern in
[AMD UG627](https://docs.amd.com/api/khub/documents/TRSkTbERlQzP8~B_44CW7A/content),
pages 133 and 144–150. RAM inference and timing improvement must be measured;
the existing clocks and uncertainty remain unchanged.

The generator pins the complete DSP source blob, accounts for every stack
access and checks the CALL/restore parent conditions. It also compares the
entire non-MkII source after configuration selection. The formal component
contains all 176 stack state bits and both asynchronous read paths. The same
strict state-cut/SAT method used for CX4 checks every common binary state and
input combination, including reset, frozen restores, partial-byte writes,
overflow and the original unsized return-index subtraction. No reset or
initialization is assumed. Data corruption, a missing freeze gate and an
incorrectly wrapped return index must each produce a real counterexample.
Only a passing proof enables original/banked native seed-68 builds with strict
PAR/TRACE checks. This proves the extracted stack component, not the whole DSP
or hardware operation; the candidate is not applied to production RTL.

The first DSP banked Area/seed-68 result inferred four distributed RAMs,
used 6244 LUTs and 3425 slices, and failed timing with 224 setup errors and
-2.689 ns worst slack. Its new worst path traverses eight logic levels from
SNES address decoding to a DSP data-register enable. The diagnostic `map_goal`
input permits a bounded Speed cover-mode comparison on the original and
banked sources at the same seed 68. Only MAP cover mode changes; the full
formal gate, synthesis settings, clock uncertainty and native timing checks
remain. This tests the depth-versus-capacity tradeoff documented in UG628
page 88; the failed Area candidate is not a production change.

Both DSP Speed-cover trials also failed: original seed 68 had 22 setup
errors and -0.792 ns worst slack; banked had 369 and -2.064 ns. The unchanged
original Area profile remains closer at 13 errors and -0.206 ns. Banking is
not promoted.

The **Compare DSPx stack write-gate timing** diagnostic instead retains the
original sixteen 11-bit words and both read semantics. It separates each
word's CALL/restore address selection from the final frozen-state and byte-lane
gate, using the four-input behavioral `LUT_MAP` mechanism in UG627 pages
245–247 and 345–346. The measured original freeze-to-stack path traverses four
LUT levels; this experiment puts the freeze decision in one final LUT. No
register, clock stage, reset, initialization or CALL cycle is added. The native
reports must establish actual mapping, capacity and timing improvement.

The generator pins the same complete source, audits every access and parent
condition, and recovers all text outside the moved writes and explicit return
read bound byte for byte. All
four non-MkII configurations must remain identical. The existing 176-bit
strict state-cut proof checks every transition and both reads, with flattened
behavioral gates and real data/freeze/index-wrap negative counterexamples.
Only a successful proof enables native Area/seed-68 compilation. The unchanged
original control has already reproduced its result; `include_original` defaults
to false to avoid compiling it again. Production RTL remains unchanged.

The first write-gate proof blocked native compilation because Yosys 0.33's
early memory-to-register conversion narrowed the original 32-bit return index
to four bits. With SP=0 this wrapped to word 15 instead of preserving the
original out-of-range X result. The candidate now explicitly returns X for
SP=0 in both native source and proof model. The strict comparison still checks
invalid reads, and the wrapped-index negative control must fail. No reset,
valid-address assumption or ignored-X comparison is introduced.

The corrected factored DSPx gate passed the component proof, but the native
Area/seed-68 trial failed with 165 setup errors, -1.657 ns worst slack, 6458
LUTs and 3469 slices. Its new worst path runs from the mapper decode to a DSP
data-register enable, with 63.8% of its delay in routing; DMA paths also
fail. XST applied the LUT_MAP attribute, but this candidate is not promoted.

The original Area/seed-68 implementation has 3493 occupied slices and its
worst freeze-to-stack path spends 64% of its delay in routing. A bounded
diagnostic tests only the original RTL with XST Area and the existing MAP
Area/seed-68 settings. XST Area prioritizes reducing total logic (UG627 pages
303–304); whether that helps routing or timing must be measured. The
`original_only` input takes precedence over `include_original`. High effort,
register balancing, clocks, uncertainty, PAR and strict checks are unchanged.

Both original-RTL XST Area tests failed: DSPx had 257 setup errors and
-1.923 ns slack, and basex had 251 errors and -1.594 ns. The Speed/Area
profiles remain closer to meeting timing.

The optional runner-only DSPx placement probe keeps the original RTL and
timing constraints. It constrains just the two stack-9 flip-flops on the
original worst path to a small slice range near the measured clock-enable
logic. In the reproduced baseline, that final six-load connection alone
took 3.816 ns. UG625 describes a LOC range as a placement constraint; it
does not promise that routing or global timing improves. The workflow checks
the original source, project and UCF hashes, retains all parent constraints,
and records the actual mapped or routed placement. Missing placement evidence
or any native timing violation fails the diagnostic.

The **Compare basex write-gate timing** diagnostic targets the five-level
SNES write-strobe to cheat-data enable path (-0.827 ns in the original seed 46).
Its runner-only candidate separates the six programming-slot selections from
the late command-priority gate. Each four-input gate uses the documented
`LUT_MAP` module attribute from
[AMD UG627, pages 245–247 and 345–346](https://docs.amd.com/api/khub/documents/TRSkTbERlQzP8~B_44CW7A/content).
No register, clock stage, reset or priority change is intended. Native reports
must confirm actual LUT mapping and timing; the attribute is not itself proof
of an improvement.

The generator pins the full cheat source, validates the entire original
programming block, and accounts for every array access. Apart from moving its
two array assignments into the new gates, all original source is recovered
byte for byte, including declarations and all read expressions. A strict
state-cut SAT proof checks all 192 storage bits for every common binary state
and input, including simultaneous reset, command and programming requests and
indices 6/7. The behavioral LUT helper is flattened, not blackboxed. Corrupted
data, omitted command priority and omitted reset gating must each produce a
real counterexample. This storage-component proof does not replace full FPGA
timing or hardware validation. Only a passing proof allows the original and
factored seed-46 native comparisons; their project and timing constraints stay
unchanged. Production RTL and release artifacts are not modified.

The factored basex Area/seed-46 trial applied the LUT_MAP attribute but failed
with 126 setup errors and -1.818 ns worst slack, compared with 124 and -0.827 ns
for the reproduced original. It used 6237 LUTs and 3432 slices, freeing 29
slices. The new worst path traverses six LUT levels from the SNES address to
the SRTC state enable; BSX and DMA paths also fail. No cheat-storage endpoint
appears among the reported failing paths, which is not a full coverage claim.
The diagnostic now permits a bounded MAP Speed comparison of both sources at
the same seed 46 to test UG628's LUT-depth tradeoff. Synthesis, PAR, the full
formal gate and every timing constraint stay fixed. The Area candidate is not
promoted or repeated unchanged.

Both basex MAP Speed trials also failed. Original seed 46 used 3495 slices
and 6262 LUTs with 526 setup errors and -2.585 ns worst slack. The factored
variant used 3470 slices and 6271 LUTs with 617 errors and -3.532 ns slack.
Its worst cheat-write path has only three logic levels, but routing accounts
for 78.7% of the delay, including a 5.387 ns single-load net. The LUT helper
appears as one LUT in the native path; reduced logic depth did not close timing.

A separate bounded diagnostic selects only the original RTL, XST Area, MAP
Area and seed 46. XST Area prioritizes reducing the logic footprint (UG627,
pages 303–304); this tests a capacity/routing tradeoff against the measured
original High XST Speed/Area MAP profile. High effort, existing register
balancing, PAR and all timing constraints stay fixed. The workflow's
`source_scope` avoids another unchanged control or failed factored profile.
Resource reduction and timing closure must be measured before this setting
can become a production default.

## Toolchains

- MkII: ISE 14.7 from
  [`fbelavenuto/xilinxise`](https://hub.docker.com/r/fbelavenuto/xilinxise), with
  unused device families, EDK, and PlanAhead removed. CoreGen and its IP libraries
  are retained to regenerate the repository's `.xco` files on a clean checkout.
  A current JVM replaces the bundled JVM. The container's host ID follows the
  [upstream ISE VM runtime configuration](https://github.com/vmunoz82/ise14).
- MkIII: Quartus Prime Lite 25.1 plus the matching Cyclone IV E device data from
  [NikLeberg/container_builder](https://github.com/NikLeberg/container_builder/tree/main/quartus).
- Software: Ubuntu 24.04 with pinned ARM GCC 13.5.0, binutils 2.47,
  newlib 4.6.0.20260123, and the
  [SNES assembler/linker 1.8.1.1](https://bisqwit.iki.fi/source/snescom.html).
  The assembler archive is checked against its SHA-256 before compilation.
  The ARM compiler, binutils, newlib and Cortex-M runtime libraries are built
  from pinned upstream releases with verified archive checksums. Newlib is
  compiled with GCC 13.5.0 before GCC's runtime libraries, so headers and
  libraries come from the same toolchain for all three MCU configurations.
  Regular newlib uses its upstream `--enable-target-optspace`/`-Os` configuration
  to fit the firmware flash budgets, retaining the regular library features.
  Runtime library preparation is limited to the Cortex-M0+, Cortex-M3 and
  Cortex-M4 variants used here, plus GCC's default library. Each long toolchain
  build step has a timeout and reports process CPU activity every minute.
  These builds run only on the hosted runner. The linker assertion also
  checks the initialized data stored after the code and constants in flash.

Vendor and Ubuntu base images are pinned by digest in `.github/docker/`.
FPGA timing checks remain enabled. Failed builds upload their compiler and
timing reports as separate Actions artifacts.
During FPGA compilation, the log also reports container CPU/memory usage and
process CPU time every minute, including while ISE is quiet during routing.

## Cache behavior

The local `prepare-build-image` action caches three prepared Docker image
archives: MkII, MkIII, and software. Each archive includes the toolchain and its
system dependencies, so a cache hit loads the image and skips provisioning.
Caches are saved immediately after image preparation, before compiling the
project, so a source or timing failure does not discard the toolchain setup.
The small, checksum-verified SNES assembler source archive has a separate cache,
saved before preparing GCC, so toolchain updates can reuse it even when its
upstream download server is unavailable.
The initial download also accepts an Internet Archive snapshot of the same
upstream release, subject to the identical pinned SHA-256 check.

Keys include the runner OS/architecture and a hash of the Dockerfile and ISE
trimming or software toolchain preparation script. Source changes reuse the cached tools; changing toolchain
configuration creates a new cache. The first build downloads the vendor images
and prepares the environments. Hosted runners free unused SDKs to make room for
that installation, and the image's size is printed in the job log.
Preparation jobs warm each required toolchain cache before dependent jobs
start. On a cache hit, those jobs only load the completed image; they do not
rebuild the toolchains or install their prerequisites.

GitHub can evict caches that are unused or exceed the repository's storage
limit; see [GitHub's cache limits](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#usage-limits-and-eviction-policy).
An evicted cache is rebuilt automatically. Full release runs compile FPGA images
from the checked-out sources. Software checks reuse the specified MkIII artifact
after verifying its sources against the current checkout.
