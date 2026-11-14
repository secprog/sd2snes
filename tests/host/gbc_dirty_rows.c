/* Execute each device player's real dirty-row reader with the existing 65816
 * interpreter. Check every cell alone and missing, plus deterministic maps.
 * The two wire layouts must produce identical masked bytes and instruction
 * counts, with exactly three status reads per row. No player code is patched.
 */
#include "m65816.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { CASES = 2 + 720 + 256, ROWS = 18, COLS = 20 };
static uint8_t views[5 * 65536], cells[ROWS * COLS];
static uint32_t baseline[CASES][ROWS];
static uint64_t instructions[CASES][ROWS];
static uint32_t reads[3];
static unsigned nreads;

static void require(int ok, const char *what) {
  if (!ok) { fprintf(stderr, "FAIL: %s\n", what); exit(1); }
}

static uint32_t symbol(const char *path, const char *name) {
  FILE *f = fopen(path, "r");
  char line[1024], label[512];
  unsigned bank, addr;
  int inside = 0, found = 0;
  uint32_t value = 0;
  require(f != NULL, "open assembly symbols");
  while (fgets(line, sizeof line, f)) {
    if (line[0] == '[') inside = !strncmp(line, "[labels]", 8);
    if (inside && sscanf(line, "%x:%x %511s", &bank, &addr, label) == 3 &&
        !strcmp(label, name)) {
      require(!found && bank < 256 && addr < 65536, "unique valid symbol");
      value = bank * 65536 + addr;
      found = 1;
    }
  }
  fclose(f);
  require(found, name);
  return value;
}

static void watch(uint32_t addr) {
  require(nreads < 3, "no extra dirty-status reads");
  reads[nreads++] = addr;
}

static void load_player(const char *path) {
  FILE *f = fopen(path, "rb");
  long size;
  uint8_t *rom;
  require(f != NULL && fseek(f, 0, SEEK_END) == 0, "open device player");
  size = ftell(f);
  require(size > 0 && size < 0x70000, "player ends before framebuffer SRAM");
  rewind(f);
  rom = malloc((size_t)size);
  require(rom != NULL, "allocate ROM");
  require(fread(rom, 1, (size_t)size, f) == (size_t)size, "read complete ROM");
  fclose(f);
  m_reset_memory();
  m_load_rom(rom, (size_t)size);
  free(rom);
  m_gbc_mode(1);
  m_set_view_window(views);
}

static void run_player(int mk2, const char *rom, const char *sym) {
  const uint32_t start = symbol(sym, "GbcFbRowBits");
  const uint32_t some = symbol(sym, "GbcFbRowSome");
  const uint32_t ver = symbol(sym, "GbcCheckVer");
  const uint32_t lo = 0xe20200, hi = 0xe202ff;
  uint32_t random = 0x86c60503;
  unsigned test, row, cell;
  load_player(rom);
  require(m_peek(ver) == 0xaf && m_peek(ver + 4) == 0xc9 &&
          m_peek(ver + 5) == (mk2 ? 5 : 3), "compiled wire-version gate");
  m_set_read_watch(1, &lo, &hi, watch);
  m_instr_budget = 64;
  for (test = 0; test < CASES; ++test) {
    for (cell = 0; cell < ROWS * COLS; ++cell) {
      if (test < 2) cells[cell] = (uint8_t)test;
      else if (test < 362) cells[cell] = cell == test - 2;
      else if (test < 722) cells[cell] = cell != test - 362;
      else {
        random ^= random << 13; random ^= random >> 17; random ^= random << 5;
        cells[cell] = (uint8_t)(random & 1);
      }
    }
    /* Encode bits independently of the RTL byte-select implementation. */
    memset(views, 0, sizeof views);
    for (cell = 0; cell < ROWS * COLS; ++cell) if (cells[cell]) {
      const unsigned r = cell / COLS, c = cell % COLS;
      const unsigned bit = mk2 ? 32 * r + 4 * (r & 1) + c : cell;
      views[0x20200 + (mk2 ? 0xa0 : 0x60) + bit / 8] |= 1u << (bit % 8);
    }
    for (row = 0; row < ROWS; ++row) {
      uint32_t expected = 0, actual, first;
      unsigned byte;
      for (cell = 0; cell < COLS; ++cell)
        expected |= (uint32_t)cells[row * COLS + cell] << cell;
      expected <<= 4 * (row & 1);
      m_cpu = (m_cpu_t){ .s = 0x1fff, .p = M_M };
      m_poke16(0x42, (uint16_t)row);
      m_poke16(0x62, 0); /* The caller's 16-bit index scratch. */
      m_poke(0x5f, 0xa5); m_poke(0x60, 0xa5); m_poke(0x61, 0xa5);
      nreads = 0;
      if (expected) m_run_to(start, some);
      else {
        m_call(start, 0);
        require((m_cpu.p & M_C) != 0, "clean row returns carry set");
      }
      actual = m_peek(0x5f) | (uint32_t)m_peek(0x60) << 8 |
               (uint32_t)m_peek(0x61) << 16;
      require(actual == expected, "all twenty dirty cells and nibble masks");
      first = lo + (mk2 ? 0xa0 + 4 * row : 0x60 + 20 * row / 8);
      require(nreads == 3, "exactly three status reads per row");
      for (byte = 0; byte < 3; ++byte)
        require(reads[byte] == first + byte, "compiled dirty-row addresses");
      if (!mk2) {
        baseline[test][row] = actual;
        instructions[test][row] = m_cpu.instrs;
      } else {
        require(actual == baseline[test][row], "both players see identical dirt");
        require(m_cpu.instrs == instructions[test][row], "same instruction count");
      }
    }
  }
}

int main(int argc, char **argv) {
  require(argc == 5, "usage: gbc_dirty_rows mk3.bin mk3.sym mk2.bin mk2.sym");
  require(m_selftest() == 0, "existing 65816 interpreter self-tests");
  run_player(0, argv[1], argv[2]);
  run_player(1, argv[3], argv[4]);
  printf("PASS: both compiled players preserve every dirty cell in %u row reads\n",
         2 * CASES * ROWS);
  return 0;
}
