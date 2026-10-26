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
(`equiv_simple -undef -seq 1`, `equiv_status -assert`). The same checker must reject
a deliberately incorrect write-data mutation. The original and candidate then
use the same ISE project, constraints and seed 46. Only proof inputs and reports
are uploaded; no diagnostic bitstreams enter a release. All verification and
compilation in this workflow runs on GitHub-hosted runners.

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
