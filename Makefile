MCUSRC := src

README := README*

MK2MCUPATH := $(MCUSRC)/obj-mk2
MK3MCUPATH := $(MCUSRC)/obj-mk3
STMMCUPATH := $(MCUSRC)/obj-mk3-stm32
MK2MCU := firmware.img
MK3MCU := firmware.im3
STMMCU := firmware.stm

SAVESTATEPATH := savestate
SAVESTATEFILES := savestate*.yml

MENUPATH := snes
MK2MENU := menu.bin
MK3MENU := m3nu.bin

FPGAPATH := verilog
MK2EXT := bit
MK3EXT := bi3
# MkII needs separate extended-mapper, competition-cart and SGB/MSU variants.
MK2CORES := base basex bootleg col20 cx4 dsp dspx gsu gsu3 obc1 sa1 sdd1 sgb sgb_msu spc7110 st0011 st0018 test xc
# Both MkIII MCU variants load these same Cyclone IV images.
MK3CORES := a26 base bootleg col20 cx4 dsp gbc gsu gsu3 nes nes_k nes_mmc3 nes_mmc5 obc1 sa1 sdd1 sgb sms spc7110 st0011 st0018 test xc

MK2FPGA := $(foreach C,$(MK2CORES),$(FPGAPATH)/sd2snes_$C/fpga_$C.$(MK2EXT))
MK3FPGA := $(foreach C,$(MK3CORES),$(FPGAPATH)/sd2snes_$C/fpga_$C.$(MK3EXT))

MK2MINI := $(FPGAPATH)/sd2snes_mini/fpga_mini.bit
MK3MINI := $(FPGAPATH)/sd2snes_mini/fpga_mini.bi3

MK2CLEAN := $(foreach C,$(MK2CORES) mini,$(FPGAPATH)/sd2snes_$C/.clean.$(MK2EXT))
MK3CLEAN := $(foreach C,$(MK3CORES) mini,$(FPGAPATH)/sd2snes_$C/.clean.$(MK3EXT))

BIN := bin

UTILS := utils

-include src/VERSION
include src/version.mk

RELEASE_BOARD ?= all
ifeq ($(RELEASE_BOARD),mk2)
RELEASE_FPGA := $(MK2FPGA) $(MK2MINI)
RELEASE_MCU := $(MK2MCUPATH)/$(MK2MCU)
RELEASE_MENU := $(MK2MENU)
RELEASE_MODULES := $(MK2MCUPATH)
else ifeq ($(RELEASE_BOARD),mk3)
RELEASE_FPGA := $(MK3FPGA) $(MK3MINI)
RELEASE_MCU := $(MK3MCUPATH)/$(MK3MCU)
RELEASE_MENU := $(MK3MENU)
RELEASE_MODULES := $(MK3MCUPATH)
else ifeq ($(RELEASE_BOARD),mk3-stm32)
RELEASE_FPGA := $(MK3FPGA) $(MK3MINI)
RELEASE_MCU := $(STMMCUPATH)/$(STMMCU)
RELEASE_MENU := $(MK3MENU)
RELEASE_MODULES := $(STMMCUPATH)
else ifeq ($(RELEASE_BOARD),all)
RELEASE_FPGA := $(MK2FPGA) $(MK2MINI) $(MK3FPGA) $(MK3MINI)
RELEASE_MCU := $(MK2MCUPATH)/$(MK2MCU) $(MK3MCUPATH)/$(MK3MCU) $(STMMCUPATH)/$(STMMCU)
RELEASE_MENU := $(MK2MENU) $(MK3MENU)
RELEASE_MODULES := $(MK3MCUPATH)
else
$(error RELEASE_BOARD must be all, mk2, mk3 or mk3-stm32)
endif

RELEASE_SUFFIX := $(if $(filter all,$(RELEASE_BOARD)),,-$(RELEASE_BOARD))
TARGETPARENT := release/v$(CONFIG_VERSION)$(RELEASE_SUFFIX)
TARGET := $(TARGETPARENT)/sd2snes
RELEASE_ZIP := sd2snes_firmware_v$(CONFIG_VERSION)$(RELEASE_SUFFIX).zip

all: version fpga build
	$(MAKE) release

fpga: fpga-mk2 fpga-mk3

fpga-mk2: $(MK2FPGA) $(MK2MINI)
fpga-mk3: $(MK3FPGA) $(MK3MINI)

# CI obtains its per-core matrix and verifies artifacts from these same lists.
list-fpga-mk2:
	@printf '%s\n' $(MK2CORES) mini

list-fpga-mk3:
	@printf '%s\n' $(MK3CORES) mini

# Build these before compressing FPGA images or building firmware.
host-tools:
	$(MAKE) -C $(UTILS)
	$(MAKE) -C $(MCUSRC)/utils

$(MK2FPGA) $(MK3FPGA) $(MK2MINI) $(MK3MINI): | host-tools

# CI passes FPGA artifacts from the same workflow run to the software job.
ifeq ($(FPGA_PREBUILT),1)
$(MK2FPGA) $(MK3FPGA) $(MK2MINI) $(MK3MINI):
	@test -s "$@" || { echo "Missing prebuilt FPGA image: $@" >&2; exit 1; }
else

$(MK2FPGA) $(MK2MINI):
	$(MAKE) -C $(dir $@) mk2

$(MK3FPGA) $(MK3MINI):
	$(MAKE) -C $(dir $@) mk3
endif

$(MK2CLEAN):
	$(MAKE) -C $(dir $@) mk2_clean

$(MK3CLEAN):
	$(MAKE) -C $(dir $@) mk3_clean

build: $(MK2MINI) $(MK3MINI) | host-tools
	$(MAKE) -C snes
	$(MAKE) -C src CONFIG=config-mk2
	$(MAKE) -C src CONFIG=config-mk3
	$(MAKE) -C src CONFIG=config-mk3-stm32

clean: $(MK2CLEAN) $(MK3CLEAN)
	$(MAKE) -C snes clean
	$(MAKE) -C src clean CONFIG=config-mk2
	$(MAKE) -C src clean CONFIG=config-mk3
	$(MAKE) -C src clean CONFIG=config-mk3-stm32

release: version bsxpage
	rm -rf $(TARGETPARENT)
	mkdir -p $(TARGET)
	cp $(BIN)/*.bin $(TARGET)
ifneq ($(README),)
	cp $(README) $(TARGET)
endif
	cp $(RELEASE_FPGA) $(TARGET)
	cp $(RELEASE_MCU) $(TARGET)
	cp $(addprefix $(MENUPATH)/,$(RELEASE_MENU)) $(TARGET)
	cp $(MENUPATH)/igmenu.bin $(MENUPATH)/onboarding.bin $(TARGET)
	cp $(addprefix $(RELEASE_MODULES)/,nsfplay.bin memtest.bin pcmplay.bin rtc7110.bin fileops.bin rmdir.bin xc_soc.bin) $(TARGET)
	mkdir -p $(TARGET)/lang
	cp $(MENUPATH)/fonts/*.txt $(TARGET)/lang
	set -e; for lang in ja zh; do \
		cp $(MENUPATH)/lang_$$lang.bin $(TARGET)/lang/$$lang.bin; \
		cp $(MENUPATH)/lang_$$lang.fnt $(TARGET)/lang/$$lang.fnt; \
	done
ifneq ($(SAVESTATEPATH),)
	cp $(SAVESTATEPATH)/$(SAVESTATEFILES) $(TARGET)
endif
	cd $(TARGETPARENT) && zip -r $(RELEASE_ZIP) sd2snes

bsxpage:
	$(MAKE) -C $(UTILS)
	mkdir -p bin
	cd bin && ../$(UTILS)/genbsxpage

version:
	@echo Version: $(CONFIG_VERSION)

# ---- ludufre PT-BR fork: mk3-only targets (no mk2 = no Xilinx ISE) ----
# `mk3`     : full from-scratch mk3 release (FPGA cores via Quartus [Make-cached]
#             + firmware mk3/stm32 + menu + bsxpage), assembled + zipped. Nothing
#             from the official zip. Needs QUARTUS_ROOTDIR in the env (prepare.sh).
# `mk3-fw`  : just menu + firmware (mk3 + stm32) — fast, for device-update
#             iteration; skips the big FPGA cores (only needs the mini cfgware).
mk3: version $(MK3FPGA) $(MK3MINI) bsxpage mk3-fw
	rm -rf $(TARGETPARENT)
	mkdir -p $(TARGET)
	cp bin/*.bin $(TARGET)
	cp $(README) $(TARGET)
	cp $(MK3FPGA) $(TARGET)
	cp $(MK3MCUPATH)/$(MK3MCU) $(TARGET)
	cp $(STMMCUPATH)/$(STMMCU) $(TARGET)
	cp $(MENUPATH)/$(MK3MENU) $(TARGET)
	cp $(MENUPATH)/$(MK2MENU) $(TARGET)
	cp $(SAVESTATEPATH)/$(SAVESTATEFILES) $(TARGET)
	cd $(TARGETPARENT) && zip -r sd2snes_firmware_v$(CONFIG_VERSION).zip sd2snes

mk3-fw: $(MK3MINI)
	$(MAKE) -C snes
	$(MAKE) -C src CONFIG=config-mk3
	$(MAKE) -C src CONFIG=config-mk3-stm32

.PHONY: all fpga fpga-mk2 fpga-mk3 list-fpga-mk2 list-fpga-mk3 host-tools build clean version release bsxpage mk3 mk3-fw $(MK2FPGA) $(MK3FPGA) $(MK2MINI) $(MK3MINI) $(MK2CLEAN) $(MK3CLEAN)
