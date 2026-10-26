CORE = cx4

VSRC = address.v cheat.v clk_test.v dac.v dcm.v dcm96.v cx4.v main.v mcu_cmd.v msu.v regshadow.v sd_dma.v spi.v
VHSRC =

COMMON_IP = cx4_datram cx4_datrom cx4_mul cx4_pgmrom dac_buf msu_databuf snescmd_buf

HEADER = config.vh

# Guide duplication of high-fanout CX4 controls during synthesis (UG627, pp. 347-349).
# Keep RTL, clock requirements and actual pin-register packing unchanged.
XST_XCF = synthesis.xcf

XIL_IP =
XIL_IPCORE_DIR = ip/mk2

INT_IP = pll

include ../settings.mk
include ../common.mk
