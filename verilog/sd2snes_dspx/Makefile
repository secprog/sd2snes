CORE = dspx

# mk2-only variant of the dsp core: the same source with DSP_COMP defined (this project's
# Verilog Macros), i.e. with the Campus Challenge '92 / PowerFest '94 event board map,
# select latch and round timer. See address.v.
VSRC_DIR = ../sd2snes_dsp

VSRC = address.v cheat.v clk_test.v ctx.v dac.v dcm.v dma.v upd77c25.v main.v mcu_cmd.v msu.v sd_dma.v spi.v
VHSRC =

COMMON_IP = dac_buf msu_databuf snescmd_buf upd77c25_datram upd77c25_datrom upd77c25_pgmrom

HEADER = config.vh

XIL_IP =
XIL_IPCORE_DIR = ../sd2snes_dsp/ip/mk2

INT_IP = pll

include ../settings.mk
include ../common.mk

# Retain the original MAP command while performing a source-pinned two-FF
# physical relocation after MAP. The shared PAR/TRCE recipe stays unchanged.
# Explicit main.ngd avoids passing the hook/manifest prerequisites to MAP.
main_map.ncd: main.ngd dma4_ff_relocation.tcl dma4_ff_physical.tcl dma4_ff_relocation.sha256
	$(call T,[mk2] fpga_$(CORE) - Map)
	$(eval XILINX_MAP_OPTS := $(shell $(XILINX_ENV) $(XILINX_BIN)/xtclsh $(XILINX_SCRIPTS)/xgenmapcmd.tcl sd2snes_$(CORE).xise $(ISE_CTABLE)))
	$(XILINX_ENV) $(XILINX_BIN)/map -p $(XILINX_PART) $(XILINX_MAP_OPTS) -o $@ main.ngd main.pcf || { status=$$?; rm -f "$@"; exit $$status; }
	$(XILINX_ENV) $(XILINX_BIN)/xtclsh dma4_ff_physical.tcl "$(XILINX_BIN)" main_map.ncd main.pcf dma4_ff_relocation.sha256 || { status=$$?; rm -f "$@"; exit $$status; }
