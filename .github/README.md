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

The MkII and MkIII jobs run in parallel and build the FPGA cores listed in
`MK2CORES` and `MK3CORES` in the root Makefile, including each board's mini
configuration image. The firmware job downloads both jobs' artifacts from the
same run and runs `make all FPGA_PREBUILT=1`. This builds the ARM firmware for
MkII, MkIII LPC, and MkIII STM32, the SNES menus, fonts, and card modules, then
assembles the release ZIP. `FPGA_PREBUILT=1` fails if any required FPGA image is
missing; ordinary local `make all` still builds the FPGA images.

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

Keys include the runner OS/architecture and a hash of the Dockerfile and ISE
trimming or software toolchain preparation script. Source changes reuse the cached tools; changing toolchain
configuration creates a new cache. The first build downloads the vendor images
and prepares the environments. Hosted runners free unused SDKs to make room for
that installation, and the image's size is printed in the job log.
One preparation job builds and saves the software image before its dependent
jobs start. On a cache hit, those jobs only load the completed image; they do not
rebuild GCC, newlib or binutils, or install their prerequisites.

GitHub can evict caches that are unused or exceed the repository's storage
limit; see [GitHub's cache limits](https://docs.github.com/en/actions/reference/workflows-and-actions/dependency-caching#usage-limits-and-eviction-policy).
An evicted cache is rebuilt automatically. Full release runs compile FPGA images
from the checked-out sources. Software checks reuse the specified MkIII artifact
after verifying its sources against the current checkout.
