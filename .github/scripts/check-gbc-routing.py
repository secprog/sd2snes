"""Compile and exercise the actual GBC policy function on hosted runners."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root / "src/gbc.c").read_text()
start = source.index("#ifndef CONFIG_MK2\nstatic uint8_t gbc_ext_is_gbc")
end = source.index("uint8_t gbc_bios_state", start)
policy = source[start:end]
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
''' + policy + r'''
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
