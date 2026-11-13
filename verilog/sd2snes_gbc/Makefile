CORE = gbc

VSRC = c6_fb.v c6_sram.v mk2_memory.v dcm.v address.v cheat.v clk_test.v dac.v gbc_bridge.v gbc_clk.v main.v mcu_cmd.v sd_dma.v spi.v sgb.v sgb_cpu.v
VHSRC =

HEADER = config.vh

COMMON_IP = dec_table vram snescmd_buf oam

XIL_IP =
XIL_IPCORE_DIR = ../sd2snes_sgb/ip/mk2

INT_IP = pll hram

include ../settings.mk
include ../common.mk

# Pin assignments and the 24 MHz -> 84 MHz DCM are the proven Mk.II SGB
# interface. Keep constraints in one place; a parent edit rebuilds this core.
main.ucf: ../sd2snes_sgb/main.ucf
	cp $< $@
