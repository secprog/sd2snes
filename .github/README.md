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

`Compare CX4 GPR bank timing` tests three 16-byte banks in place of the original
48-byte GPR array. XST reports 384 flip-flops for the original array; this is a
targeted RAM-inference experiment, not an assumed timing fix. The source generator
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
PAR/TRACE gates. All models and reports remain diagnostic artifacts; production
RTL is unchanged. The RAM coding references are AMD UG627, pages 133 and 144–150;
the proof uses Yosys 0.33's strict miter comparison and SAT failure checks.
The byte-to-bank address decoder uses an explicit combinational table because
XST only supports division/remainder by powers of two (UG627 pages 128 and 491).
The complete proof is repeated when this decoder changes. `include_original`
defaults to true; it can be disabled when a recent unchanged control already
exists under the identical image, project and constraints.
`synthesis_goal` selects Area (the default) or Speed in the diagnostic runner's
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
