"""Compile and exercise the actual GBC policy function on hosted runners."""
from pathlib import Path
import re
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/gbc.c").read_text()
start = source.index("#ifndef CONFIG_MK2\nstatic uint8_t gbc_ext_is_gbc")
end = source.index("uint8_t gbc_bios_state", start)
policy = source[start:end]
loader = (root / "src/memory.c").read_text()
start = loader.index("  romprops.has_msu1 = 0;", loader.index('printf("check MSU..."'))
end = loader.index("  /* Xeno Crisis:", start)
msu_policy = loader[start:end]
feature = re.search(r"^#define FEAT_MSU1\s+[^\n]+", (root / "src/fpga_spi.h").read_text(), re.M)[0]
harness = r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <strings.h>
#include <assert.h>
typedef struct { uint8_t has_sgb,core_is_gbc; struct { uint8_t name[16]; } header;
                 uint16_t fpga_sgbfeat; } sgb_romprops_t;
#include "gbc.h"
static struct { unsigned gbc_mode,gbc_sync,sgb_volume_boost; } CFG;
static uint8_t SGBFW[64], SGBSR[64];
static void strlcpy_nul(uint8_t *out,const char *in,unsigned n) {
  assert(strlen(in)<n); strcpy((char *)out,in);
}
#define printf(...) ((void)0)
''' + policy + "\n" + feature + r'''
static sgb_romprops_t sgb_romprops;
static struct { unsigned has_spc7110,has_fx3,has_msu1,fpga_features; } romprops;
static struct { unsigned has_nes; } nes_romprops;
static unsigned msu_calls,msu_present;
static int msu1_check(uint8_t *filename) {
  assert(filename); msu_calls++;
  if(msu_present) romprops.fpga_features |= FEAT_MSU1;
  return msu_present;
}
static void load_msu_policy(uint8_t *filename) {
  struct { uint8_t *filename; } c={filename};
''' + msu_policy + r'''
}
#undef printf
int main(void) {
  uint8_t *names[]={(uint8_t *)"test.gb",(uint8_t *)"test.GBC",NULL};
  unsigned checked=0;
  for(unsigned has=0;has<2;has++) for(unsigned cgb=0;cgb<256;cgb++)
  for(unsigned mode=0;mode<4;mode++) for(unsigned v=0;v<8;v++)
  for(unsigned sync=0;sync<2;sync++) for(unsigned n=0;n<3;n++) {
    sgb_romprops_t p={0}; p.has_sgb=has; p.header.name[15]=cgb; p.fpga_sgbfeat=0x7777;
    strcpy((char *)SGBFW,"legacy-boot"); strcpy((char *)SGBSR,"legacy-player");
    CFG.gbc_mode=mode; CFG.gbc_sync=sync; CFG.sgb_volume_boost=v;
    gbc_id(&p,names[n]);
#ifdef CONFIG_MK2
    unsigned want=has;
#else
    unsigned want=has && (mode==1 ? cgb==0xc0 : mode==2 ? 1 : (n==1 || (cgb&0x80)));
#endif
    assert(p.core_is_gbc==want);
    assert(p.has_sgb==has && p.header.name[15]==cgb);
    assert(!strcmp((char *)SGBFW,want ? GBC_BOOT_FILE_STR : "legacy-boot"));
    assert(!strcmp((char *)SGBSR,want ? GBC_PLAYER_FILE_STR : "legacy-player"));
    assert(p.fpga_sgbfeat==(want ? v|((cgb&0x80)?GBC_FEAT_CGB_HDR:0)
                            |(sync?GBC_FEAT_SYNC_EXACT:0) : 0x7777));
    checked++;
  }
  printf("PASS: %u actual loader-policy cases; boot, player and feature word agree\n",checked);
  checked=0;
  for(unsigned spc=0;spc<2;spc++) for(unsigned fx3=0;fx3<2;fx3++)
  for(unsigned nes=0;nes<2;nes++) for(unsigned gb=0;gb<2;gb++)
  for(unsigned gbc=0;gbc<2;gbc++) for(unsigned present=0;present<2;present++) {
    romprops.has_spc7110=spc; romprops.has_fx3=fx3;
    romprops.has_msu1=1; romprops.fpga_features=0;
    nes_romprops.has_nes=nes; sgb_romprops.has_sgb=gb; sgb_romprops.core_is_gbc=gbc;
    msu_calls=0; msu_present=present;
    load_msu_policy(names[0]);
#ifdef CONFIG_MK2
    unsigned want_call=!nes && !spc && !fx3 && !(gb && gbc);
#else
    unsigned want_call=!nes;
#endif
    assert(msu_calls==want_call);
    assert(romprops.has_msu1==(want_call && present));
    assert(romprops.fpga_features==((want_call && present) ? FEAT_MSU1 : 0));
    checked++;
  }
  printf("PASS: %u actual MSU activation cases; unsupported cores skip file-open side effects\n",checked);
}
'''
with tempfile.TemporaryDirectory(prefix="gbc-routing-") as temp:
    work = Path(temp)
    test = work / "routing.c"
    test.write_text(harness)
    for board in ("MK2", "MK3"):
        binary = work / board
        subprocess.run(["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-DCONFIG_" + board, "-I", str(root / "src"),
                        str(test), "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)
