#!/usr/bin/env python3
"""GitHub-only complete basex address proof and original strict native timing."""
import copy,hashlib,json,os,re,shutil,stat,subprocess,sys,time,zipfile
from pathlib import Path,PurePosixPath
if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("GitHub-hosted execution only")
BASE="a8614d3cd944e9819cc749d475e058a35e6435c8"
SOURCE="verilog/sd2snes_base/address.v"
SELF=".github/scripts/validate-basex-normal-unshared.py"
WORKFLOW=".github/workflows/validate-dspx-stack-timing.yml"
IMAGE="sha256:5e3bbb00649997abca8843b1d82d8529eda99a0f2868d37ad9777e0ad5fd50e8"
MAC="08:00:27:68:c9:35"
MAP=("map -p xc3s400-4pq208 -timing -logic_opt on -ol high -xe n -t 46 "
     "-register_duplication on -cm area -detail -ir off -ignore_keep_hierarchy "
     "-pr b -bp -power off -o main_map.ncd main.ngd main.pcf")
PAR="par -w -ol high -xe c -t 46 main_map.ncd main.ncd main.pcf"
REPORTS={".syr",".par",".mrp",".psr",".bld",".bgn",".twr",".unroutes",
         ".pcf",".xst",".prj",".ut",".tsi",".ucf"}
FRAGMENTS=json.loads(r'''{
  "source": "verilog/sd2snes_base/address.v",
  "base": "a8614d3cd944e9819cc749d475e058a35e6435c8",
  "old": "assign SRAM_SNES_ADDR = IS_PATCH\n                        ? SNES_ADDR\n                        : ((MAPPER_DEC[3'b000])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[12:0]}\n                                            & SAVERAM_MASK)\n                            : BS_PACK_HIT_HI                        /* HiROM pack: $En:0000 -> bank*$10000 */\n                            ? (24'h900000 + {4'h0, SNES_ADDR[19:0]})\n                            : ({1'b0, SNES_ADDR[22:0]} & ROM_MASK))\n\n                          :(MAPPER_DEC[3'b001])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & SAVERAM_MASK)\n                            : BS_PACK_HIT                          /* LoROM pack: $Cn:8000 -> bank*$8000 */\n                            ? (24'h900000 + {4'h0, LOROM_OFF})\n                            : BSLOROM_HI\n                            ? (BSLOROM_ADDR & ROM_MASK)\n                            : ({1'b0, ~SNES_ADDR[23], SNES_ADDR[22:16], SNES_ADDR[14:0]}\n                               & ROM_MASK))\n\n                            /* Gamars Puzzle.\n                            *\n                            * ROM mapping is otherwise ordinary LoROM.\n                            *\n                            * $31:6000-$61ff\n                            * $41:6000-$61ff\n                            *\n                            * both map to the same SaveRAM offsets $000-$1ff.\n                            */\n                          :(MAP_GAMARS)\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR\n                               + ({15'b0, SNES_ADDR[8:0]} & SAVERAM_MASK)\n                            : ({1'b0,\n                                ~SNES_ADDR[23],\n                                SNES_ADDR[22:16],\n                                SNES_ADDR[14:0]}\n                               & ROM_MASK))\n\n                          :(MAPPER_DEC[3'b010])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[12:0]}\n                                            & SAVERAM_MASK)\n                            : ({1'b0, !SNES_ADDR[23], SNES_ADDR[21:0]}\n                               & ROM_MASK))\n                          :(MAPPER_DEC[3'b011])\n                          ?(  IS_SAVERAM\n                              ? SAVERAM_ADDR + {SNES_ADDR[18:16], SNES_ADDR[11:0]}\n                              : BSX_IS_CARTROM\n                              ? (24'h800000 + ({SNES_ADDR[22:16], SNES_ADDR[14:0]} & 24'h0fffff))\n                              : BSX_IS_PSRAM\n                              ? (24'h400000 + (BSX_ADDR & 24'h07FFFF))\n                              : bs_page_enable\n                              ? (24'h900000 + {bs_page,bs_page_offset})\n                              : (BSX_ADDR & 24'h0fffff)\n                           )\n                           :(MAP_SUFAMI)  /* Sufami Turbo */\n                           ?(IS_SAVERAM\n                             ? (SNES_ADDR[20]\n                                ? (ST_SAVERAM_B + ({SNES_ADDR[19:16], SNES_ADDR[15:0]}\n                                                 & SAVERAM_MASK_B))\n                                : (SAVERAM_ADDR + ({SNES_ADDR[19:16], SNES_ADDR[15:0]}\n                                                 & SAVERAM_MASK)))\n                             : (SNES_ADDR[22:21] == 2'b00)   /* ST BIOS, 256 KB */\n                             ? ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]} & 24'h03ffff)\n                             : (SNES_ADDR[22:21] == 2'b01)   /* Slot A ROM */\n                             ? (24'h100000 | ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & ROM_MASK))\n                             : (24'h700000 | ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & ROM_MASK_B))  /* Slot B ROM; mask 0 = empty slot */\n                            )\n                           :(MAPPER_DEC[3'b110])\n                           ?(IS_SAVERAM\n                             ? SAVERAM_ADDR + ((SNES_ADDR[14:0] - 15'h6000)\n                                             & SAVERAM_MASK)\n                             :(SNES_ADDR[15]\n                               ?({1'b0, SNES_ADDR[23:16], SNES_ADDR[14:0]})\n                               :({2'b10,\n                                  SNES_ADDR[23],\n                                  SNES_ADDR[21:16],\n                                  SNES_ADDR[14:0]}\n                                )\n                              )\n                            )\n                           :(MAPPER_DEC[3'b111])\n                           ?(IS_SAVERAM\n                             ? SNES_ADDR\n                             : (({1'b0, SNES_ADDR[22:0]} & ROM_MASK)\n                                + 24'hC00000)\n                            )\n                           : 24'b0);",
  "new": "`ifdef MK2\n`ifdef BASE_EXT\n// Keep every arithmetic branch and its original width, with no shared adder\n// feeding the complete normal mapper. The original patch override remains last.\nwire [23:0] basex_normal_addr;\nbasex_normal_mapper_unshared normal_addr_unshared(\n  .MAPPER_DEC(MAPPER_DEC),\n  .IS_SAVERAM(IS_SAVERAM),\n  .SAVERAM_ADDR(SAVERAM_ADDR),\n  .SNES_ADDR(SNES_ADDR),\n  .SAVERAM_MASK(SAVERAM_MASK),\n  .BS_PACK_HIT_HI(BS_PACK_HIT_HI),\n  .BS_PACK_HIT(BS_PACK_HIT),\n  .LOROM_OFF(LOROM_OFF),\n  .BSLOROM_HI(BSLOROM_HI),\n  .BSLOROM_ADDR(BSLOROM_ADDR),\n  .ROM_MASK(ROM_MASK),\n  .MAP_GAMARS(MAP_GAMARS),\n  .BSX_IS_CARTROM(BSX_IS_CARTROM),\n  .BSX_IS_PSRAM(BSX_IS_PSRAM),\n  .BSX_ADDR(BSX_ADDR),\n  .bs_page_enable(bs_page_enable),\n  .bs_page(bs_page),\n  .bs_page_offset(bs_page_offset),\n  .MAP_SUFAMI(MAP_SUFAMI),\n  .ST_SAVERAM_B(ST_SAVERAM_B),\n  .SAVERAM_MASK_B(SAVERAM_MASK_B),\n  .ROM_MASK_B(ROM_MASK_B),\n  .NORMAL_ADDR(basex_normal_addr)\n);\nassign SRAM_SNES_ADDR = IS_PATCH ? SNES_ADDR : basex_normal_addr;\n`else\nassign SRAM_SNES_ADDR = IS_PATCH\n                        ? SNES_ADDR\n                        : ((MAPPER_DEC[3'b000])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[12:0]}\n                                            & SAVERAM_MASK)\n                            : BS_PACK_HIT_HI                        /* HiROM pack: $En:0000 -> bank*$10000 */\n                            ? (24'h900000 + {4'h0, SNES_ADDR[19:0]})\n                            : ({1'b0, SNES_ADDR[22:0]} & ROM_MASK))\n\n                          :(MAPPER_DEC[3'b001])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & SAVERAM_MASK)\n                            : BS_PACK_HIT                          /* LoROM pack: $Cn:8000 -> bank*$8000 */\n                            ? (24'h900000 + {4'h0, LOROM_OFF})\n                            : BSLOROM_HI\n                            ? (BSLOROM_ADDR & ROM_MASK)\n                            : ({1'b0, ~SNES_ADDR[23], SNES_ADDR[22:16], SNES_ADDR[14:0]}\n                               & ROM_MASK))\n\n                            /* Gamars Puzzle.\n                            *\n                            * ROM mapping is otherwise ordinary LoROM.\n                            *\n                            * $31:6000-$61ff\n                            * $41:6000-$61ff\n                            *\n                            * both map to the same SaveRAM offsets $000-$1ff.\n                            */\n                          :(MAP_GAMARS)\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR\n                               + ({15'b0, SNES_ADDR[8:0]} & SAVERAM_MASK)\n                            : ({1'b0,\n                                ~SNES_ADDR[23],\n                                SNES_ADDR[22:16],\n                                SNES_ADDR[14:0]}\n                               & ROM_MASK))\n\n                          :(MAPPER_DEC[3'b010])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[12:0]}\n                                            & SAVERAM_MASK)\n                            : ({1'b0, !SNES_ADDR[23], SNES_ADDR[21:0]}\n                               & ROM_MASK))\n                          :(MAPPER_DEC[3'b011])\n                          ?(  IS_SAVERAM\n                              ? SAVERAM_ADDR + {SNES_ADDR[18:16], SNES_ADDR[11:0]}\n                              : BSX_IS_CARTROM\n                              ? (24'h800000 + ({SNES_ADDR[22:16], SNES_ADDR[14:0]} & 24'h0fffff))\n                              : BSX_IS_PSRAM\n                              ? (24'h400000 + (BSX_ADDR & 24'h07FFFF))\n                              : bs_page_enable\n                              ? (24'h900000 + {bs_page,bs_page_offset})\n                              : (BSX_ADDR & 24'h0fffff)\n                           )\n                           :(MAP_SUFAMI)  /* Sufami Turbo */\n                           ?(IS_SAVERAM\n                             ? (SNES_ADDR[20]\n                                ? (ST_SAVERAM_B + ({SNES_ADDR[19:16], SNES_ADDR[15:0]}\n                                                 & SAVERAM_MASK_B))\n                                : (SAVERAM_ADDR + ({SNES_ADDR[19:16], SNES_ADDR[15:0]}\n                                                 & SAVERAM_MASK)))\n                             : (SNES_ADDR[22:21] == 2'b00)   /* ST BIOS, 256 KB */\n                             ? ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]} & 24'h03ffff)\n                             : (SNES_ADDR[22:21] == 2'b01)   /* Slot A ROM */\n                             ? (24'h100000 | ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & ROM_MASK))\n                             : (24'h700000 | ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & ROM_MASK_B))  /* Slot B ROM; mask 0 = empty slot */\n                            )\n                           :(MAPPER_DEC[3'b110])\n                           ?(IS_SAVERAM\n                             ? SAVERAM_ADDR + ((SNES_ADDR[14:0] - 15'h6000)\n                                             & SAVERAM_MASK)\n                             :(SNES_ADDR[15]\n                               ?({1'b0, SNES_ADDR[23:16], SNES_ADDR[14:0]})\n                               :({2'b10,\n                                  SNES_ADDR[23],\n                                  SNES_ADDR[21:16],\n                                  SNES_ADDR[14:0]}\n                                )\n                              )\n                            )\n                           :(MAPPER_DEC[3'b111])\n                           ?(IS_SAVERAM\n                             ? SNES_ADDR\n                             : (({1'b0, SNES_ADDR[22:0]} & ROM_MASK)\n                                + 24'hC00000)\n                            )\n                           : 24'b0);\n`endif\n`else\nassign SRAM_SNES_ADDR = IS_PATCH\n                        ? SNES_ADDR\n                        : ((MAPPER_DEC[3'b000])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[12:0]}\n                                            & SAVERAM_MASK)\n                            : BS_PACK_HIT_HI                        /* HiROM pack: $En:0000 -> bank*$10000 */\n                            ? (24'h900000 + {4'h0, SNES_ADDR[19:0]})\n                            : ({1'b0, SNES_ADDR[22:0]} & ROM_MASK))\n\n                          :(MAPPER_DEC[3'b001])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & SAVERAM_MASK)\n                            : BS_PACK_HIT                          /* LoROM pack: $Cn:8000 -> bank*$8000 */\n                            ? (24'h900000 + {4'h0, LOROM_OFF})\n                            : BSLOROM_HI\n                            ? (BSLOROM_ADDR & ROM_MASK)\n                            : ({1'b0, ~SNES_ADDR[23], SNES_ADDR[22:16], SNES_ADDR[14:0]}\n                               & ROM_MASK))\n\n                            /* Gamars Puzzle.\n                            *\n                            * ROM mapping is otherwise ordinary LoROM.\n                            *\n                            * $31:6000-$61ff\n                            * $41:6000-$61ff\n                            *\n                            * both map to the same SaveRAM offsets $000-$1ff.\n                            */\n                          :(MAP_GAMARS)\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR\n                               + ({15'b0, SNES_ADDR[8:0]} & SAVERAM_MASK)\n                            : ({1'b0,\n                                ~SNES_ADDR[23],\n                                SNES_ADDR[22:16],\n                                SNES_ADDR[14:0]}\n                               & ROM_MASK))\n\n                          :(MAPPER_DEC[3'b010])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[12:0]}\n                                            & SAVERAM_MASK)\n                            : ({1'b0, !SNES_ADDR[23], SNES_ADDR[21:0]}\n                               & ROM_MASK))\n                          :(MAPPER_DEC[3'b011])\n                          ?(  IS_SAVERAM\n                              ? SAVERAM_ADDR + {SNES_ADDR[18:16], SNES_ADDR[11:0]}\n                              : BSX_IS_CARTROM\n                              ? (24'h800000 + ({SNES_ADDR[22:16], SNES_ADDR[14:0]} & 24'h0fffff))\n                              : BSX_IS_PSRAM\n                              ? (24'h400000 + (BSX_ADDR & 24'h07FFFF))\n                              : bs_page_enable\n                              ? (24'h900000 + {bs_page,bs_page_offset})\n                              : (BSX_ADDR & 24'h0fffff)\n                           )\n                           :(MAP_SUFAMI)  /* Sufami Turbo */\n                           ?(IS_SAVERAM\n                             ? (SNES_ADDR[20]\n                                ? (ST_SAVERAM_B + ({SNES_ADDR[19:16], SNES_ADDR[15:0]}\n                                                 & SAVERAM_MASK_B))\n                                : (SAVERAM_ADDR + ({SNES_ADDR[19:16], SNES_ADDR[15:0]}\n                                                 & SAVERAM_MASK)))\n                             : (SNES_ADDR[22:21] == 2'b00)   /* ST BIOS, 256 KB */\n                             ? ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]} & 24'h03ffff)\n                             : (SNES_ADDR[22:21] == 2'b01)   /* Slot A ROM */\n                             ? (24'h100000 | ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & ROM_MASK))\n                             : (24'h700000 | ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & ROM_MASK_B))  /* Slot B ROM; mask 0 = empty slot */\n                            )\n                           :(MAPPER_DEC[3'b110])\n                           ?(IS_SAVERAM\n                             ? SAVERAM_ADDR + ((SNES_ADDR[14:0] - 15'h6000)\n                                             & SAVERAM_MASK)\n                             :(SNES_ADDR[15]\n                               ?({1'b0, SNES_ADDR[23:16], SNES_ADDR[14:0]})\n                               :({2'b10,\n                                  SNES_ADDR[23],\n                                  SNES_ADDR[21:16],\n                                  SNES_ADDR[14:0]}\n                                )\n                              )\n                            )\n                           :(MAPPER_DEC[3'b111])\n                           ?(IS_SAVERAM\n                             ? SNES_ADDR\n                             : (({1'b0, SNES_ADDR[22:0]} & ROM_MASK)\n                                + 24'hC00000)\n                            )\n                           : 24'b0);\n`endif",
  "suffix": "\n`ifdef MK2\n`ifdef BASE_EXT\n// This synthesis boundary changes resource allocation, not mapping semantics.\n// Keep the complete original expression, including all masks, pages and mappers.\n(* keep_hierarchy=\"yes\", resource_sharing=\"no\" *)\nmodule basex_normal_mapper_unshared(\n  input [7:0] MAPPER_DEC,\n  input IS_SAVERAM,\n  input [23:0] SAVERAM_ADDR,\n  input [23:0] SNES_ADDR,\n  input [23:0] SAVERAM_MASK,\n  input BS_PACK_HIT_HI,\n  input BS_PACK_HIT,\n  input [19:0] LOROM_OFF,\n  input BSLOROM_HI,\n  input [23:0] BSLOROM_ADDR,\n  input [23:0] ROM_MASK,\n  input MAP_GAMARS,\n  input BSX_IS_CARTROM,\n  input BSX_IS_PSRAM,\n  input [23:0] BSX_ADDR,\n  input bs_page_enable,\n  input [9:0] bs_page,\n  input [8:0] bs_page_offset,\n  input MAP_SUFAMI,\n  input [23:0] ST_SAVERAM_B,\n  input [23:0] SAVERAM_MASK_B,\n  input [23:0] ROM_MASK_B,\n  output [23:0] NORMAL_ADDR\n);\nassign NORMAL_ADDR = ((MAPPER_DEC[3'b000])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[12:0]}\n                                            & SAVERAM_MASK)\n                            : BS_PACK_HIT_HI                        /* HiROM pack: $En:0000 -> bank*$10000 */\n                            ? (24'h900000 + {4'h0, SNES_ADDR[19:0]})\n                            : ({1'b0, SNES_ADDR[22:0]} & ROM_MASK))\n\n                          :(MAPPER_DEC[3'b001])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & SAVERAM_MASK)\n                            : BS_PACK_HIT                          /* LoROM pack: $Cn:8000 -> bank*$8000 */\n                            ? (24'h900000 + {4'h0, LOROM_OFF})\n                            : BSLOROM_HI\n                            ? (BSLOROM_ADDR & ROM_MASK)\n                            : ({1'b0, ~SNES_ADDR[23], SNES_ADDR[22:16], SNES_ADDR[14:0]}\n                               & ROM_MASK))\n\n                            /* Gamars Puzzle.\n                            *\n                            * ROM mapping is otherwise ordinary LoROM.\n                            *\n                            * $31:6000-$61ff\n                            * $41:6000-$61ff\n                            *\n                            * both map to the same SaveRAM offsets $000-$1ff.\n                            */\n                          :(MAP_GAMARS)\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR\n                               + ({15'b0, SNES_ADDR[8:0]} & SAVERAM_MASK)\n                            : ({1'b0,\n                                ~SNES_ADDR[23],\n                                SNES_ADDR[22:16],\n                                SNES_ADDR[14:0]}\n                               & ROM_MASK))\n\n                          :(MAPPER_DEC[3'b010])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[12:0]}\n                                            & SAVERAM_MASK)\n                            : ({1'b0, !SNES_ADDR[23], SNES_ADDR[21:0]}\n                               & ROM_MASK))\n                          :(MAPPER_DEC[3'b011])\n                          ?(  IS_SAVERAM\n                              ? SAVERAM_ADDR + {SNES_ADDR[18:16], SNES_ADDR[11:0]}\n                              : BSX_IS_CARTROM\n                              ? (24'h800000 + ({SNES_ADDR[22:16], SNES_ADDR[14:0]} & 24'h0fffff))\n                              : BSX_IS_PSRAM\n                              ? (24'h400000 + (BSX_ADDR & 24'h07FFFF))\n                              : bs_page_enable\n                              ? (24'h900000 + {bs_page,bs_page_offset})\n                              : (BSX_ADDR & 24'h0fffff)\n                           )\n                           :(MAP_SUFAMI)  /* Sufami Turbo */\n                           ?(IS_SAVERAM\n                             ? (SNES_ADDR[20]\n                                ? (ST_SAVERAM_B + ({SNES_ADDR[19:16], SNES_ADDR[15:0]}\n                                                 & SAVERAM_MASK_B))\n                                : (SAVERAM_ADDR + ({SNES_ADDR[19:16], SNES_ADDR[15:0]}\n                                                 & SAVERAM_MASK)))\n                             : (SNES_ADDR[22:21] == 2'b00)   /* ST BIOS, 256 KB */\n                             ? ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]} & 24'h03ffff)\n                             : (SNES_ADDR[22:21] == 2'b01)   /* Slot A ROM */\n                             ? (24'h100000 | ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & ROM_MASK))\n                             : (24'h700000 | ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & ROM_MASK_B))  /* Slot B ROM; mask 0 = empty slot */\n                            )\n                           :(MAPPER_DEC[3'b110])\n                           ?(IS_SAVERAM\n                             ? SAVERAM_ADDR + ((SNES_ADDR[14:0] - 15'h6000)\n                                             & SAVERAM_MASK)\n                             :(SNES_ADDR[15]\n                               ?({1'b0, SNES_ADDR[23:16], SNES_ADDR[14:0]})\n                               :({2'b10,\n                                  SNES_ADDR[23],\n                                  SNES_ADDR[21:16],\n                                  SNES_ADDR[14:0]}\n                                )\n                              )\n                            )\n                           :(MAPPER_DEC[3'b111])\n                           ?(IS_SAVERAM\n                             ? SNES_ADDR\n                             : (({1'b0, SNES_ADDR[22:0]} & ROM_MASK)\n                                + 24'hC00000)\n                            )\n                           : 24'b0);\nendmodule\n`endif\n`endif\n",
  "ports": [
    [
      "MAPPER_DEC",
      8
    ],
    [
      "IS_SAVERAM",
      1
    ],
    [
      "SAVERAM_ADDR",
      24
    ],
    [
      "SNES_ADDR",
      24
    ],
    [
      "SAVERAM_MASK",
      24
    ],
    [
      "BS_PACK_HIT_HI",
      1
    ],
    [
      "BS_PACK_HIT",
      1
    ],
    [
      "LOROM_OFF",
      20
    ],
    [
      "BSLOROM_HI",
      1
    ],
    [
      "BSLOROM_ADDR",
      24
    ],
    [
      "ROM_MASK",
      24
    ],
    [
      "MAP_GAMARS",
      1
    ],
    [
      "BSX_IS_CARTROM",
      1
    ],
    [
      "BSX_IS_PSRAM",
      1
    ],
    [
      "BSX_ADDR",
      24
    ],
    [
      "bs_page_enable",
      1
    ],
    [
      "bs_page",
      10
    ],
    [
      "bs_page_offset",
      9
    ],
    [
      "MAP_SUFAMI",
      1
    ],
    [
      "ST_SAVERAM_B",
      24
    ],
    [
      "SAVERAM_MASK_B",
      24
    ],
    [
      "ROM_MASK_B",
      24
    ]
  ],
  "fullOriginalNormalExpression": "((MAPPER_DEC[3'b000])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[12:0]}\n                                            & SAVERAM_MASK)\n                            : BS_PACK_HIT_HI                        /* HiROM pack: $En:0000 -> bank*$10000 */\n                            ? (24'h900000 + {4'h0, SNES_ADDR[19:0]})\n                            : ({1'b0, SNES_ADDR[22:0]} & ROM_MASK))\n\n                          :(MAPPER_DEC[3'b001])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & SAVERAM_MASK)\n                            : BS_PACK_HIT                          /* LoROM pack: $Cn:8000 -> bank*$8000 */\n                            ? (24'h900000 + {4'h0, LOROM_OFF})\n                            : BSLOROM_HI\n                            ? (BSLOROM_ADDR & ROM_MASK)\n                            : ({1'b0, ~SNES_ADDR[23], SNES_ADDR[22:16], SNES_ADDR[14:0]}\n                               & ROM_MASK))\n\n                            /* Gamars Puzzle.\n                            *\n                            * ROM mapping is otherwise ordinary LoROM.\n                            *\n                            * $31:6000-$61ff\n                            * $41:6000-$61ff\n                            *\n                            * both map to the same SaveRAM offsets $000-$1ff.\n                            */\n                          :(MAP_GAMARS)\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR\n                               + ({15'b0, SNES_ADDR[8:0]} & SAVERAM_MASK)\n                            : ({1'b0,\n                                ~SNES_ADDR[23],\n                                SNES_ADDR[22:16],\n                                SNES_ADDR[14:0]}\n                               & ROM_MASK))\n\n                          :(MAPPER_DEC[3'b010])\n                          ?(IS_SAVERAM\n                            ? SAVERAM_ADDR + ({SNES_ADDR[20:16], SNES_ADDR[12:0]}\n                                            & SAVERAM_MASK)\n                            : ({1'b0, !SNES_ADDR[23], SNES_ADDR[21:0]}\n                               & ROM_MASK))\n                          :(MAPPER_DEC[3'b011])\n                          ?(  IS_SAVERAM\n                              ? SAVERAM_ADDR + {SNES_ADDR[18:16], SNES_ADDR[11:0]}\n                              : BSX_IS_CARTROM\n                              ? (24'h800000 + ({SNES_ADDR[22:16], SNES_ADDR[14:0]} & 24'h0fffff))\n                              : BSX_IS_PSRAM\n                              ? (24'h400000 + (BSX_ADDR & 24'h07FFFF))\n                              : bs_page_enable\n                              ? (24'h900000 + {bs_page,bs_page_offset})\n                              : (BSX_ADDR & 24'h0fffff)\n                           )\n                           :(MAP_SUFAMI)  /* Sufami Turbo */\n                           ?(IS_SAVERAM\n                             ? (SNES_ADDR[20]\n                                ? (ST_SAVERAM_B + ({SNES_ADDR[19:16], SNES_ADDR[15:0]}\n                                                 & SAVERAM_MASK_B))\n                                : (SAVERAM_ADDR + ({SNES_ADDR[19:16], SNES_ADDR[15:0]}\n                                                 & SAVERAM_MASK)))\n                             : (SNES_ADDR[22:21] == 2'b00)   /* ST BIOS, 256 KB */\n                             ? ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]} & 24'h03ffff)\n                             : (SNES_ADDR[22:21] == 2'b01)   /* Slot A ROM */\n                             ? (24'h100000 | ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & ROM_MASK))\n                             : (24'h700000 | ({4'b0, SNES_ADDR[20:16], SNES_ADDR[14:0]}\n                                            & ROM_MASK_B))  /* Slot B ROM; mask 0 = empty slot */\n                            )\n                           :(MAPPER_DEC[3'b110])\n                           ?(IS_SAVERAM\n                             ? SAVERAM_ADDR + ((SNES_ADDR[14:0] - 15'h6000)\n                                             & SAVERAM_MASK)\n                             :(SNES_ADDR[15]\n                               ?({1'b0, SNES_ADDR[23:16], SNES_ADDR[14:0]})\n                               :({2'b10,\n                                  SNES_ADDR[23],\n                                  SNES_ADDR[21:16],\n                                  SNES_ADDR[14:0]}\n                                )\n                              )\n                            )\n                           :(MAPPER_DEC[3'b111])\n                           ?(IS_SAVERAM\n                             ? SNES_ADDR\n                             : (({1'b0, SNES_ADDR[22:0]} & ROM_MASK)\n                                + 24'hC00000)\n                            )\n                           : 24'b0)",
  "originalSha256": "dd1c00473255e9d9432a12e77d3819ab17203ece11a1bb8a6dbba36d638142fe",
  "candidateSha256": "a991db68d4163bc4f422e1a002902fe0b39ddd3c6bd93fcc9dee4b58bcaf16f5"
}''')


def require(ok, why):
    if not ok:
        raise ValueError(why)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def read(path):
    raw = Path(path).read_bytes()
    require(b"\0" not in raw, "NUL in text")
    raw.decode("utf-8")
    return raw

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    require(not path.exists(), "Refuse evidence overwrite: " + str(path))
    raw = value if isinstance(value, bytes) else (value.encode() if isinstance(value, str)
          else (json.dumps(value, indent=2, sort_keys=True) + "\n").encode())
    raw.decode("utf-8")
    require(b"\0" not in raw, "NUL in output")
    path.write_bytes(raw)

def git(*args):
    return subprocess.check_output(["git", *args])

def command(argv, prefix, timeout=1800, allowed=(0,)):
    """Keep complete stdout, stderr, argv and the actual direct process status."""
    prefix = Path(prefix)
    prefix.parent.mkdir(parents=True, exist_ok=True)
    write(str(prefix)+".argv.json", argv)
    start = time.monotonic()
    with open(str(prefix)+".stdout.log", "xb") as out, open(str(prefix)+".stderr.log", "xb") as err:
        process = subprocess.run(argv, stdout=out, stderr=err, timeout=timeout)
    streams = {}
    for kind in ("stdout", "stderr"):
        raw = read(str(prefix)+"."+kind+".log")
        streams[kind] = dict(bytes=len(raw), sha256=sha(raw))
        if raw:
            sys.stdout.write(raw.decode())
            sys.stdout.flush()
    write(str(prefix)+".status.json", dict(argv=argv, exit=process.returncode,
          elapsedSeconds=time.monotonic()-start, streams=streams))
    require(process.returncode in allowed, "Unexpected direct process exit: " + repr(argv))
    return process.returncode

def tokens(text):
    text=re.sub(r"^\s*\x60line[^\n]*","",text,flags=re.M)
    items=re.findall(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/|\s+|.',text,re.S)
    return [x for x in items if not x.isspace() and not x.startswith(("//","/*"))]

def cut_state(source, output, model_name):
    design = json.loads(read(source))
    require(set(design["modules"]) == {"address"}, "Complete flattened address component, no blackboxes")
    module = design["modules"]["address"]
    aliases, init = {}, {}
    for name, net in module["netnames"].items():
        for index, bit in enumerate(net["bits"]):
            if not name.startswith("$") and not name.startswith("normal_addr_unshared."):
                aliases.setdefault(bit, []).append((name, index))
        values = net.get("attributes", {}).get("init")
        if values is not None:
            require(isinstance(values, str) and len(values) == len(net["bits"]), "Lossless init width")
            for bit, value in zip(net["bits"], reversed(values)):
                init.setdefault(bit, set()).add(value)
    states = []
    used = set()
    remove = []
    for name, cell in module["cells"].items():
        kind = cell["type"]
        if kind != "$dff":
            require(kind.startswith("$") and not any(s in kind.lower() for s in ("dff", "latch", "mem"))
                    and kind != "$ff" and not kind.startswith("$any") and kind != "$initstate"
                    and "CLK" not in cell["connections"], "Unexpected hidden state: "+kind)
            continue
        require(cell["connections"]["CLK"] == module["ports"]["CLK"]["bits"] and
                int(cell["parameters"]["CLK_POLARITY"], 2) == 1, "Original positive clock")
        q, d = cell["connections"]["Q"], cell["connections"]["D"]
        require(len(q) == len(d), "State Q/D width")
        for qb, db in zip(q, d):
            labels = sorted(aliases.get(qb, []))
            require(isinstance(qb, int) and qb not in used and labels and len(init.get(qb, set())) <= 1,
                    "State identity/init bijection")
            used.add(qb)
            states.append(dict(identity=labels, init=next(iter(init.get(qb, set())), "x"), q=qb, d=db))
        remove.append(name)
    require(len(states) == 34, "All original34address state bits required")
    states.sort(key=lambda x: json.dumps(x["identity"]))
    identities = [json.dumps(x["identity"]) for x in states]
    require(len(set(identities)) == len(states), "Unique named state identities")
    for name in remove:
        del module["cells"][name]
    module["ports"]["__state"] = dict(direction="input", bits=[x["q"] for x in states])
    module["ports"]["__next"] = dict(direction="output", bits=[x["d"] for x in states])
    # Initial attributes are recorded above, not turned into assumptions on the cut state.
    for net in module["netnames"].values():
        net.get("attributes", {}).pop("init", None)
    design["modules"] = {model_name: module}
    write(output, design)
    return [dict(identity=x["identity"], init=x["init"]) for x in states], module["ports"]

def require_sat_result(rc,transcript,witness,positive):
    require(rc==(0 if positive else 1),"Exact real SAT/verify exit")
    if positive:
        require(b"SAT proof finished - no model found: SUCCESS!" in transcript,
                "Actual positive SAT result, not a preparation/timeout error")
        return
    witness=Path(witness)
    require(witness.is_file() and witness.stat().st_size>0,"Real changed-source counterexample")
    data=json.loads(read(witness))
    output=[x for x in data["signal"] if x.get("name","").lstrip("\\")=="ok"]
    require(len(output)==1 and output[0].get("wave","").startswith("0"),
            "Counterexample records actual failed output ok=0")
    require(b"Solving problem with" in transcript and
            (b"SAT proof finished - model found: FAIL!" in transcript or
             b"ERROR: Called with -verify and proof did fail!" in transcript),
            "Actual solver counterexample/verify failure, never a generic tool error or timeout")

def native_spec(phase):
    require(phase=="native","Only one original native phase")
    return [".github/scripts/build.sh","mk2","basex"]

def inspect_container(info, name, phase, running=None):
    require(len(info) == 1, "One owned container")
    c = info[0]; expected = native_spec(phase)
    require(c["Name"] == "/"+name and c["Image"] == IMAGE and
            c["Config"]["Entrypoint"] == ["/bin/bash"] and c["Config"]["Cmd"] == expected and
            c["Config"]["User"] == "0:0" and c["Config"]["WorkingDir"] == "/work", "Exact owned native command")
    require(c["HostConfig"]["NetworkMode"] == "bridge", "Native license bridge")
    if c["State"]["Running"]:
        require(c["NetworkSettings"]["Networks"]["bridge"]["MacAddress"] == MAC, "Actual live licensed MAC")
    mounts = c["Mounts"]
    require(len(mounts) == 1 and mounts[0]["Destination"] == "/work" and mounts[0]["RW"] is True and
            mounts[0]["Source"] == os.environ["GITHUB_WORKSPACE"], "Only exact checkout mount")
    env = dict(x.split("=",1) for x in c["Config"]["Env"])
    require(env["IGNORE_TIMING"] == "0" and env["ISE_CTABLE"] == "" and
            not any(x.startswith("MAKE") or x == "XILINX_PART" for x in env), "No inherited build controls")
    require(env.get("XIL_TIMING_HOLDCHECKING") == ("YES" if phase=="hold" else None), "Explicit separate hold analysis")
    if running is not None:
        require(c["State"]["Running"] is running, "Actual process lifecycle")
    return c

def container(out, phase):
    out = Path(out); name = "basex-"+phase+"-"+os.environ["GITHUB_RUN_ID"]+"-"+os.environ["GITHUB_RUN_ATTEMPT"]
    require(re.fullmatch("[a-z0-9-]+", name), "Owned name")
    require(not subprocess.check_output(["docker","ps","-aq","--filter","name=^/"+name+"$"]).strip(),
            "No duplicate owned container")
    command(["docker","image","inspect",IMAGE],out/(phase+"-image"))
    argv = ["docker","create","--name",name,"--user","0:0","--network","bridge","--mac-address",MAC,
            "--volume",os.environ["GITHUB_WORKSPACE"]+":/work","--workdir","/work",
            "--env","IGNORE_TIMING=0","--env","ISE_CTABLE=","--entrypoint","/bin/bash"]
    if phase=="hold": argv += ["--env","XIL_TIMING_HOLDCHECKING=YES"]
    argv += [IMAGE,*native_spec(phase)]
    command(argv,out/(phase+"-create"))
    command(["docker","start",name],out/(phase+"-start"))
    # Observe the actual licensed interface while this owned process is live.
    live = json.loads(subprocess.check_output(["docker","inspect",name]))
    write(out/(phase+"-started.json"),live)
    inspect_container(live,name,phase,True)
    command(["docker","logs","--follow",name],out/(phase+"-build"),timeout=21600)
    command(["docker","wait",name],out/(phase+"-wait"))
    done = json.loads(subprocess.check_output(["docker","inspect",name]))
    write(out/(phase+"-finished.json"),done)
    c = inspect_container(done,name,phase,False)
    require(not c["State"]["OOMKilled"] and not c["State"]["Error"], "No native OOM/runtime error")
    rc = c["State"]["ExitCode"]
    require(read(out/(phase+"-wait.stdout.log")).strip() == str(rc).encode(), "Docker wait/native status binding")
    write(out/(phase+"-exit.json"),dict(exit=rc,phase=phase,name=name,originalFailurePreserved=True))
    # Keep the complete inspect evidence and remove only this completed exact container.
    command(["docker","rm",name],out/(phase+"-remove"))
    require(rc == 0, "Actual "+phase+" process failed with exit "+str(rc))

def collect(out):
    out = Path(out); root = Path("verilog/sd2snes_basex")
    target = out/"native-reports";target.mkdir()
    rows = []
    for f in sorted(root.iterdir()):
        if f.is_file() and f.suffix in REPORTS:
            require(not f.is_symlink(), "Regular native report")
            b = read(f); require(len(b) <= 3_000_000,"Native text cap")
            write(target/f.name,b)
            rows.append(dict(path=f.name,bytes=len(b),sha256=sha(b)))
    write(target/"report-index.json",rows)

def freeze_ip(out,label):
    root=Path("verilog/sd2snes_base/ip/mk2/build")
    require(root.is_dir(),"Original isolated base IP products")
    rows=[]
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(),"Regular IP product")
        if path.is_file():
            raw=path.read_bytes()
            rows.append(dict(path=path.as_posix(),bytes=len(raw),sha256=sha(raw),mtimeNs=path.stat().st_mtime_ns))
    ips=("dac_buf","msu_databuf","snescmd_buf")
    require(all((root/(name+suffix)).is_file()for name in ips for suffix in (".ngc",".v")),"All three original base IPs")
    prj=read("verilog/sd2snes_basex/main.prj").decode()
    for name in ips:
        require(prj.count('verilog work "../sd2snes_base/ip/mk2/build/'+name+'.v"')==1,
                "Actual basex canonical isolated wrapper binding")
    write(Path(out)/("ip-"+label+".json"),rows)
    if label!="before":
        require(rows==json.loads(read(Path(out)/"ip-before.json")),"All base IP bytes/mtimes immutable")

def baseline(out):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    artifact = 13629706369
    for kind, endpoint in (("run","actions/runs/42507318034"),
                           ("jobs","actions/runs/42507318034/jobs?per_page=100"),
                           ("artifact","actions/artifacts/"+str(artifact))):
        raw = subprocess.check_output(["gh","api","repos/secprog/sd2snes/"+endpoint])
        write(out/(kind+"-api.json"), raw)
    a = json.loads(read(out/"artifact-api.json"))
    require(a["id"] == artifact and a["size_in_bytes"] == 206808 and
            a["digest"] == "sha256:5b7c04346bc5282b9aa573dcc6d01f22ee821ff9adf8952b93367f0ecf36b90f" and
            not a["expired"] and a["workflow_run"]["id"] == 42507318034, "Exact original report artifact")
    run = json.loads(read(out/"run-api.json"))
    require(run["head_sha"] == "31cecdc00d200691afe8a85a5ec6f8cc2924e92e" and run["run_attempt"] == 1
            and run["status"] == "completed", "Original build identity")
    jobs = json.loads(read(out/"jobs-api.json"))
    job = next(x for x in jobs["jobs"] if x["id"] == 128814120555)
    require(job["status"] == "completed" and job["conclusion"] == "success", "Original basex job remains success")
    raw = subprocess.check_output(["gh","api","repos/secprog/sd2snes/actions/artifacts/"+str(artifact)+"/zip"])
    require(len(raw) == a["size_in_bytes"] and "sha256:"+sha(raw) == a["digest"], "Complete original ZIP hash")
    import io
    total, seen, rows = 0, set(), []
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [x for x in archive.infolist() if not x.is_dir()]
        expected_names={"_temp/fpga-build.log"}|{
            "sd2snes/sd2snes/verilog/sd2snes_basex/"+n for n in
            ("main.bld","main.bgn","main.par","main.syr","main.unroutes","main.twr","main_map.mrp","main_map.psr")}
        require(len(members)==9 and {x.filename for x in members}==expected_names,
                "Exact complete nine-file original report and build-log union")
        for entry in members:
            name = PurePosixPath(entry.filename)
            mode = entry.external_attr >> 16
            require(not name.is_absolute() and "\\" not in entry.filename and ":" not in entry.filename and
                    all(x not in ("",".","..") for x in name.parts) and
                    (mode & 0o170000) in (0, stat.S_IFREG), "Safe original regular path")
            require((name.suffix in REPORTS or entry.filename=="_temp/fpga-build.log") and
                    name.name.casefold() not in seen, "Expected unique original report/build log")
            seen.add(name.name.casefold())
            require(entry.file_size <= 3_000_000, "Original file cap")
            b = archive.read(entry)
            require(len(b) == entry.file_size and b"\0" not in b, "Original CRC/size/text")
            b.decode("utf-8")
            total += len(b); require(total <= 8_000_000, "Original aggregate cap")
            write(out/name.name, b)
            rows.append(dict(path=name.name,originalPath=entry.filename,bytes=len(b),sha256=sha(b)))
    pins = {"main.par":"18e44aed3bf134ec4e4f94932dadc9d36416e9b74f53f04073b181cf01cd2cb6",
            "main.twr":"fe84fb2699cae633c7ae0b3c7d8ab68fcae7f16518f189eb88530b3c81dc1db6",
            "main_map.mrp":"62570644ee0288e823573528463f83ba62412386cc4e8a1da29fd99e0e51d479"}
    pins["fpga-build.log"]="e5b46fc84355fada65583fbf3fef6270cce3093acdc016905bb61a993debd0f0"
    for name, pin in pins.items():
        require(sha(read(out/name)) == pin, "Byte-exact original report: "+name)
    write(out/"baseline-index.json",rows)
    controls(out)

def parse_timing(par, twr):
    scores = re.findall(r"Timing Score:\s*(\d+)\s*\(Setup:\s*(\d+), Hold:\s*(\d+), Component Switching Limit:\s*(\d+)\)",par)
    totals = re.findall(r"Timing errors:\s*(\d+)\s+Score:\s*(\d+)\s+\(Setup/Max:\s*(\d+), Hold:\s*(\d+)\)",twr)
    require(len(scores)==len(totals)==1,"Exactly one complete timing summary")
    slack = {"setup":[],"hold":[],"other":[]}
    for line in twr.splitlines():
        if line.lstrip().startswith("Slack"):
            m = re.match(r"\s*Slack(?:\s+\((setup|hold) paths?\))?:\s*([+-]?\d+(?:\.\d+)?)ns\b",line)
            require(m is not None,"Every displayed slack parsed")
            slack[m[1] or "other"].append(float(m[2]))
    require(slack["setup"] and slack["hold"],"Actual setup and hold records")
    return dict(parScore=int(scores[0][0]),setupScore=int(scores[0][1]),holdScore=int(scores[0][2]),
                componentScore=int(scores[0][3]),traceErrors=int(totals[0][0]),traceScore=int(totals[0][1]),
                traceSetupScore=int(totals[0][2]),traceHoldScore=int(totals[0][3]),
                fullyRouted="All signals are completely routed." in par,
                slack={k:dict(records=len(v),negative=sum(x<0 for x in v),minimumNs=min(v) if v else None)
                       for k,v in slack.items()})

def timing_clean(parsed):
    return (parsed["fullyRouted"] and all(parsed[k]==0 for k in
            ("parScore","setupScore","holdScore","componentScore","traceErrors","traceScore",
             "traceSetupScore","traceHoldScore")) and
            all(v["negative"]==0 for v in parsed["slack"].values()))

def controls(out):
    out=Path(out)
    actual=parse_timing(read(out/"main.par").decode(),read(out/"main.twr").decode())
    require(actual['traceErrors']==124 and actual['slack']['setup']['minimumNs']==-0.827 and
            actual['slack']['hold']['negative']==0 and not timing_clean(actual),
            "Actual original basex setup failure must reject")
    par="All signals are completely routed.\nTiming Score: 0 (Setup: 0, Hold: 0, Component Switching Limit: 0)\n"
    twr="Slack (setup path): 0.028ns\nSlack (hold path): 0.433ns\nSlack: 0.000ns\nTiming errors: 0 Score: 0 (Setup/Max: 0, Hold: 0)\n"
    cases=[("synthetic-clean",par,twr,True),("actual-original-setup-failure",read(out/"main.par").decode(),read(out/"main.twr").decode(),False)]
    for name,key,old,new in [
      ("negative-setup","twr","0.028ns","-0.001ns"),
      ("negative-hold-with-zero-summary","twr","0.433ns","-3.216ns"),
      ("negative-plain","twr","0.000ns","-0.001ns"),
      ("par-setup","par","Setup: 0,","Setup: 1,"),
      ("par-hold","par","Hold: 0,","Hold: 1,"),
      ("par-component","par","Limit: 0","Limit: 1"),
      ("trace-errors","twr","Timing errors: 0","Timing errors: 1"),
      ("trace-score","twr","Score: 0 (","Score: 1 ("),
      ("trace-hold","twr","Hold: 0)","Hold: 1)"),
      ("unrouted","par","All signals are completely routed.","Not completely routed."),
      ("unknown-slack","twr","Slack: 0.000ns","Slack changed: 0.000ns"),
      ("missing-hold","twr","Slack (hold path): 0.433ns\n",""),
      ("missing-setup","twr","Slack (setup path): 0.028ns\n","")]:
        original=par if key=="par" else twr
        require(original.count(old)==1,"Unique report mutation")
        replacement=original.replace(old,new,1)
        cases.append((name,replacement if key=="par" else par,replacement if key=="twr" else twr,False))
    plural=twr.replace("(setup path)","(setup paths)").replace("(hold path)","(hold paths)")
    cases.extend([("plural-clean",par,plural,True),
                  ("plural-negative-setup",par,plural.replace("0.028ns","-0.001ns"),False),
                  ("plural-negative-hold",par,plural.replace("0.433ns","-0.001ns"),False),
                  ("malformed-plural",par,plural.replace("setup paths","setup pathsx"),False)])
    cases.extend([("duplicate-par",par+par,twr,False),("duplicate-trace",par,twr+twr,False)])
    rows=[]
    for name,p,t,expected in cases:
        error=None
        try: accepted=timing_clean(parse_timing(p,t))
        except ValueError as failure: accepted=False;error=str(failure)
        rows.append(dict(name=name,expected=expected,accepted=accepted,error=error,passed=accepted==expected))
    write(out/"strict-report-controls.json",dict(controls=rows,passed=all(x["passed"] for x in rows),
          actualOriginalReportIncluded=True,syntheticReportsAreNotTimingEvidence=True))
    require(all(x["passed"] for x in rows),"Adversarial strict report controls")

def analyze(out,baseline_dir):
    out=Path(out);root=out/"native-reports"
    par,twr,mrp,pcf=(read(root/name).decode()for name in ("main.par","main.twr","main_map.mrp","main.pcf"))
    require([" ".join(x.split())for x in re.findall(r"^par .+$",par,re.M)]==[PAR],"Original single PAR/seed46")
    match=re.search(r"Command Line\s*:\s*(.*?)\s*Target Device",mrp,re.S)
    require(match and " ".join(match[1].split())==MAP,"Exact original MAP options/seed46")
    require(len(re.findall(r"/trce -v 10 -n 10 -u 10\s+-fastpaths main\.ncd main\.pcf -o main\.twr",twr))==1,
            "Original single TRACE invocation")
    expected={"TS_CLKIN":("CLKIN","24.01"),"TS_SPI_SCK":("SPI_SCK","48.1"),
              "TS_SNES_SYSCLK":("SNES_SYSCLK","21.5"),"TS_CLK21":("CLK21","96.04")}
    normalized_pcf=" ".join(pcf.split())
    periods=re.findall(r'(TS_\w+) = PERIOD TIMEGRP "([^"]+)" ([0-9.]+) MHz HIGH 50%;',normalized_pcf)
    require(len(periods)==4 and {n:(g,v)for n,g,v in periods}==expected,"All four original period requirements")
    require(set(re.findall(r"^(TS_\w+)\s*=",pcf,re.M))==set(expected),"No new/removed timing specification")
    require("SYSTEM_JITTER"not in pcf,"Preserve original basex PCF jitter specification")
    before=parse_timing(read(Path(baseline_dir)/"main.par").decode(),read(Path(baseline_dir)/"main.twr").decode())
    after=parse_timing(par,twr);native=json.loads(read(out/"native-exit.json"))
    native_log=read(out/"native-build.stdout.log")+read(out/"native-build.stderr.log")
    timing_only=(native["exit"]==2 and re.search(rb"\bError 55\b",native_log)is not None and after["fullyRouted"])
    no_worse=(after["fullyRouted"] and after["traceErrors"]<=before["traceErrors"] and
       after["slack"]["setup"]["minimumNs"]>=before["slack"]["setup"]["minimumNs"] and
       after["parScore"]<=before["parScore"] and after["holdScore"]==after["componentScore"]==0 and
       after["traceHoldScore"]==0 and after["slack"]["hold"]["negative"]==0 and
       after["slack"]["other"]["negative"]==0)
    better=(after["traceErrors"]<before["traceErrors"] or
       after["slack"]["setup"]["minimumNs"]>before["slack"]["setup"]["minimumNs"] or
       after["parScore"]<before["parScore"])
    improvement=no_worse and better and(native["exit"]==0 or timing_only)
    strict=native["exit"]==0 and timing_clean(after)
    write(out/"timing-result.json",dict(head=os.environ["GITHUB_SHA"],baseline=before,current=after,
      nativeExit=native["exit"],onlyOriginalTimingGateFailed=timing_only,measuredImprovement=improvement,
      strictTimingPassed=strict,allOriginalOptionsAndTimingRequirementsVerified=True,
      externalIoQualified=False,hardwareQualified=False,secondIndependentReviewer=False,
      limits="Reported internal timing comparison only; no all-I/O nonregression or hardware qualification claim."))
    print(json.dumps(json.loads(read(out/"timing-result.json")),indent=2))
    require(strict,"Strict basex timing remains failed; actual improvement separately retained")

def union(out):
    root=Path(out);seen=set();rows=[];total=0
    # Preserve large generated proof JSON losslessly as bounded text parts.
    # Original byte count and SHA bind the complete ordered reconstruction.
    for path in sorted(x for x in root.rglob("*") if x.is_file() and x.suffix in (".json", ".log")):
        if path.stat().st_size > 3_000_000:
            raw=read(path);require(len(raw)<=32_000_000,"Generated proof JSON cap")
            parts=[]
            for offset in range(0,len(raw),1_000_000):
                part=path.with_name(path.name+".part-%03d.txt"%(offset//1_000_000))
                data=raw[offset:offset+1_000_000]
                write(part,data);parts.append(dict(path=part.name,bytes=len(data),sha256=sha(data)))
            write(path.with_name(path.name+".parts-index.json"),
                  dict(original=path.name,bytes=len(raw),sha256=sha(raw),orderedParts=parts))
            require(b"".join(read(path.with_name(x["path"])) for x in parts)==raw,"Lossless JSON parts")
            path.unlink()
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(),"No evidence symlinks")
        if path.is_file():
            rel=path.relative_to(root).as_posix();require(rel.casefold() not in seen,"Unique safe paths")
            seen.add(rel.casefold());raw=read(path)
            require(path.suffix not in (".vvp",".ncd",".ngc",".ngd",".bit",".bin",".rom",".xdl",".zip"),
                    "No native executable/design in text artifact")
            require(len(raw)<=3_000_000,"Per-text-file cap")
            total+=len(raw);require(total<=112_000_000 and len(rows)<1024,"Aggregate/count evidence cap")
            rows.append(dict(path=rel,bytes=len(raw),sha256=sha(raw)))
    write(root/"text-union.json",dict(files=rows,bytes=total,fileCount=len(rows)))

def proof_design(out, destination):
    root=Path(out);dest=Path(destination);dest.mkdir(parents=True,exist_ok=True)
    names={"post-proc.json","constant-init.json","state.json","transition.json",
           "miter-binary.json","miter-xstate.json","miter-before-binary.json","miter-before-xstate.json"}
    rows=[];total=0
    for path in sorted(root.rglob("*.json")):
        if path.name not in names:continue
        require(not path.is_symlink(),"Regular formal graph")
        raw=read(path);require(len(raw)<=64_000_000,"Per-formal-graph bound")
        total+=len(raw);require(total<=1_000_000_000 and len(rows)<64,"Formal graph union bound")
        rel=path.relative_to(root);target=dest/rel
        target.parent.mkdir(parents=True,exist_ok=True);require(not target.exists(),"Unique formal graph")
        shutil.move(str(path),str(target))
        require(sha(read(target))==sha(raw),"Byte-exact retained formal graph")
        rows.append(dict(path=rel.as_posix(),bytes=len(raw),sha256=sha(raw),retainedOnGitHubOnly=True))
    write(root/"formal-graph-index.json",dict(files=rows,bytes=total,completeGraphsRetainedOnGitHub=True))
    write(dest/"formal-graph-index.json",dict(files=rows,bytes=total))


def candidate(original):
    require(sha(original.encode())==FRAGMENTS["originalSha256"],"Current complete original address source")
    require(original.count(FRAGMENTS["old"])==1,"Unique complete mapper assignment")
    text=original.replace(FRAGMENTS["old"],FRAGMENTS["new"],1)+FRAGMENTS["suffix"]
    require(sha(text.encode())==FRAGMENTS["candidateSha256"],"Complete reviewed candidate")
    require(text.endswith(FRAGMENTS["suffix"]),"Exact complete helper")
    recovered=text[:-len(FRAGMENTS["suffix"])]
    require(recovered.count(FRAGMENTS["new"])==1,"Unique full-source inverse")
    require(recovered.replace(FRAGMENTS["new"],FRAGMENTS["old"],1)==original,"Lossless complete inverse")
    return text

def contract(out):
    out=Path(out)
    require(git("rev-parse","HEAD").decode().strip()==os.environ["GITHUB_SHA"],"Exact checkout head")
    require(git("rev-parse","HEAD^").decode().strip() in (BASE,"37ccc3d0dc0523e3b1d6e220a399800c61106af3"),"Exact reviewed parent")
    paths={SOURCE,SELF,WORKFLOW}
    require(set(git("diff","--name-only",BASE,"HEAD").decode().splitlines())==paths,"Exact source/helper/workflow scope")
    original=git("show",BASE+":"+SOURCE)
    require(read(SOURCE)==candidate(original.decode()).encode(),"Complete mapper boundary only")
    for name in ("verilog/common.mk",".github/scripts/build.sh","verilog/sd2snes_basex/Makefile",
                 "verilog/sd2snes_base/main.ucf","verilog/sd2snes_basex/sd2snes_basex.xise",
                 "verilog/sd2snes_base/config.vh","verilog/sd2snes_base/main.v","verilog/sd2snes_base/cheat.v",
                 "verilog/sd2snes_st0018/st018_cpu.v","verilog/sd2snes_st0018/Makefile"):
        require(read(name)==git("show",BASE+":"+name),"Unchanged source or native input: "+name)
    require(not Path("verilog/settings.local").exists() and not Path("verilog/sd2snes_basex/ucf.extra").exists(),
            "No settings or timing override")
    write(out/"source-contract.json",dict(head=os.environ["GITHUB_SHA"],base=BASE,
       files=[dict(path=n,bytes=len(read(n)),sha256=sha(read(n)))for n in sorted(paths)],
       completeOriginalMapperExpressionPreserved=True,all34StateBitsUntouchedAtSource=True,
       scope="MK2 && BASE_EXT only",featuresRemoved=False,constraintsRelaxed=False,
       adoptedSt0018AndGbcUntouched=True,secondIndependentReviewer=False))

def component_miter(ports, state_bits):
    inputs=[(n,len(p["bits"]))for n,p in ports.items()if p["direction"]=="input"and n!="__state"]
    outputs=[(n,len(p["bits"]))for n,p in ports.items()if p["direction"]=="output"]
    require(all(p["direction"]in("input","output")for p in ports.values()),"Complete ordinary component interface")
    declarations=["input ["+str(sum(b for n,b in inputs)-1)+":0] common_inputs",
                  "input ["+str(state_bits-1)+":0] common_state","output ok"]
    text="module miter("+", ".join(declarations)+");\n";connections=[];offset=0
    for n,b in inputs:
        connections.append("."+n+"(common_inputs["+str(offset+b-1)+":"+str(offset)+"])");offset+=b
    comparisons=[]
    for n,b in outputs:
        require(re.fullmatch("[A-Za-z_][A-Za-z0-9_]*",n),"Safe output identifier")
        for side in ("gold","gate"):text+="wire ["+str(b-1)+":0] "+side+"_"+n+";\n"
        comparisons.append("(gold_"+n+" === gate_"+n+")")
    for side in ("gold","gate"):
        text+=side+" u_"+side+"("+", ".join(connections+[".__state(common_state)"]+
               ["."+n+"("+side+"_"+n+")"for n,b in outputs])+");\n"
    text+="assign ok = "+" & ".join(comparisons)+";\nendmodule\n"
    return text

def proof(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    original=git("show",BASE+":"+SOURCE).decode();gate=read(SOURCE).decode()
    require(gate==candidate(original),"Actual current candidate source")
    write(out/"original.v",original);write(out/"candidate.v",gate)
    profiles={"mk2-basex":["MK2","BASE_EXT"],"mk2-base":["MK2"],"mk2-bootleg":["MK2","BOOTLEG"],
              "mk2-atari":["MK2","ATARI"],"mk3-base":["MK3"],"mk3-basex":["MK3","BASE_EXT"],
              "mk3-bootleg":["MK3","BOOTLEG"]}
    scope=[]
    for profile,defines in profiles.items():
        versions={}
        for side,source in (("gold","original.v"),("gate","candidate.v")):
            target=out/(side+"-"+profile+".v")
            command(["iverilog","-g2012","-E",*["-D"+x for x in defines],"-o",str(target),str(out/source)],
                    out/(side+"-"+profile+"-preprocess"))
            versions[side]=tokens(read(target).decode())
        equal=versions["gold"]==versions["gate"]
        require(equal==(profile!="mk2-basex"),"Actual target/non-target preprocessor scope")
        scope.append(dict(profile=profile,equalOriginalTokens=equal))
    write(out/"preprocessor-scope.json",scope)
    old_suffix=FRAGMENTS["suffix"]
    bad_bsx_suffix=old_suffix.replace("24'h900000 + {bs_page,bs_page_offset}",
                                     "24'h900001 + {bs_page,bs_page_offset}",1)
    require(bad_bsx_suffix!=old_suffix,"Actual BSX page bit0 mutant")
    bad_sufami_suffix=old_suffix.replace("& SAVERAM_MASK_B))","& SAVERAM_MASK))",1)
    require(bad_sufami_suffix!=old_suffix,"Actual Sufami B mask mutant")
    patch="assign SRAM_SNES_ADDR = IS_PATCH ? SNES_ADDR : basex_normal_addr;"
    bad_x_patch="""reg [23:0] bad_patch_value;
always @* begin
  bad_patch_value = basex_normal_addr;
  if (IS_PATCH) bad_patch_value = SNES_ADDR;
end
assign SRAM_SNES_ADDR = bad_patch_value;"""
    require(gate.count(patch)==1,"Actual final patch override boundary")
    variants={"gold":original,"gate":gate,
      "bad-bsx-bit0":gate.replace(old_suffix,bad_bsx_suffix,1),
      "bad-sufami-mask":gate.replace(old_suffix,bad_sufami_suffix,1),
      "bad-state":gate.replace("SNES_ADDR <= SNES_ADDR_early;","SNES_ADDR <= SNES_ADDR_early ^ 24'h000001;",1),
      "bad-x":gate.replace(patch,bad_x_patch,1)}
    reference,ports=None,None
    for variant,source in variants.items():
        require(variant in("gold","gate")or source!=gate,"Real actual-source mutation")
        folder=out/variant;folder.mkdir();write(folder/"source.v",source)
        command(["iverilog","-g2012","-E","-DMK2","-DBASE_EXT","-o",str(folder/"preprocessed.v"),
                 str(folder/"source.v")],folder/"preprocess")
        script=("read_verilog -sv -formal "+str(folder/"preprocessed.v")+
          "; hierarchy -check -top address; setattr -mod -unset keep_hierarchy; setattr -unset keep_hierarchy; flatten; proc -ifx -noopt; check -assert; write_json "+
          str(folder/"post-proc.json")+"; opt_expr -keepdc; write_json "+str(folder/"constant-init.json")+
          "; memory_memx; memory_collect; memory_map; dffunmap; setundef -undriven -undef; opt_clean; "+
          "check -assert; write_json "+str(folder/"state.json"))
        command(["yosys","-p",script],folder/"prepare")
        inventory,current=cut_state(folder/"state.json",folder/"transition.json","gold"if variant=="gold"else"gate")
        write(folder/"state-inventory.json",inventory)
        if variant=="gold":reference,ports=inventory,current
        else:
            require(inventory==reference,"All named state/init/clock bindings unchanged")
            require({k:(v["direction"],len(v["bits"]))for k,v in current.items()}==
                    {k:(v["direction"],len(v["bits"]))for k,v in ports.items()},
                    "All component inputs and outputs unchanged")
    write(out/"miter.v",component_miter(ports,len(reference)))
    results=[]
    for variant,modes in (("gate",("binary","xstate")),("bad-bsx-bit0",("binary",)),
                          ("bad-sufami-mask",("binary",)),("bad-state",("binary",)),("bad-x",("binary","xstate"))):
        for mode in modes:
            folder=out/variant;witness=folder/("counterexample-"+mode+".json")
            script=("read_json "+str(out/"gold/transition.json")+"; read_json "+str(folder/"transition.json")+
              "; read_verilog -sv -formal "+str(out/"miter.v")+"; hierarchy -check -top miter; flatten; "+
              "opt_clean; check -assert; write_json "+str(folder/("miter-before-"+mode+".json"))+"; "+
              ("opt_merge -share_all -keepdc; opt_clean; "*16)+
              "check -assert; write_json "+str(folder/("miter-"+mode+".json"))+
              "; sat -verify -enable_undef "+("-set-def-inputs "if mode=="binary"else"")+
              "-prove ok 1 -show-inputs -show-outputs -dump_json "+str(witness)+" -timeout 600")
            prefix=folder/("proof-"+mode)
            rc=command(["yosys","-p",script],prefix,timeout=1200,allowed=(0,1))
            expected=variant=="gate"or(variant=="bad-x"and mode=="binary")
            require_sat_result(rc,read(str(prefix)+".stdout.log")+read(str(prefix)+".stderr.log"),witness,expected)
            results.append(dict(variant=variant,mode=mode,exit=rc,expectedPass=expected,actualSatResult=True))
    write(out/"proof-result.json",dict(head=os.environ["GITHUB_SHA"],completeAddressModuleAndAllOutputs=True,
       originalStateBits=len(reference),allNamedInitAndPosedgeClocksPreserved=True,
       strictBinaryAndXEquality=True,arbitrarySharedState=True,noResetEnableOrMapperAssumptions=True,
       preprocessorProfiles=len(profiles),allSixNonTargetProfilesUnchanged=True,sat=results,
       completeCurrentNormalExpressionPreserved=True,outerPatchBit0Preserved=True,
       allFeaturesAndMasksPreserved=True,mappedEquivalenceNotClaimed=True,
       hardwareQualified=False,secondIndependentReviewer=False))


if __name__=="__main__":
    mode,*args=sys.argv[1:]
    {"contract":contract,"proof":proof,"baseline":baseline,"freeze-ip":freeze_ip,
     "container":container,"collect":collect,"analyze":analyze,"union":union,
     "proof-design":proof_design}[mode](*args)
