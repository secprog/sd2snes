#!/usr/bin/env python3
"""GitHub-only address capture, complete stack transition and strict timing evidence."""
import copy
import difflib
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

if os.environ.get('GITHUB_ACTIONS') != 'true':
    raise SystemExit('GitHub-hosted execution only')

BASELINE = '274d52c8aa9c1970df2f04e39da1b5ddca8e6e25'
SOURCE = 'verilog/sd2snes_dsp/upd77c25.v'
ORIGINAL_SHA = 'af6ad41f629e2646763394ee0f2b5a1ef55e745fbb89b65701a3c8de54bcbf81'
CANDIDATE_SHA = 'f6cd94208c9ff5f0f85d43b1caef14d99a96b08dedc31c944f7262af4f2bd920'
FRAGMENTS = {'originalPush': '    if(push_now) stack[regs_sp] <= pc + 1;\n', 'scopedPush': '`ifndef DSP_COMP\n    if(push_now) stack[regs_sp] <= pc + 1;\n`endif\n', 'originalRestore': '        if(ss_wa[0]) stack[ss_wstk_idx][10:8] <= ss_wd[2:0];\n        else         stack[ss_wstk_idx][7:0]  <= ss_wd;\n', 'scopedRestore': '`ifdef MK2\n`ifndef DSP_COMP\n        if(ss_wa[0]) stack[ss_wstk_idx][10:8] <= ss_wd[2:0];\n        else         stack[ss_wstk_idx][7:0]  <= ss_wd;\n`endif\n`else\n        if(ss_wa[0]) stack[ss_wstk_idx][10:8] <= ss_wd[2:0];\n        else         stack[ss_wstk_idx][7:0]  <= ss_wd;\n`endif\n', 'anchor': "wire [3:0] ss_wstk_idx = (ss_wa - 8'h34) >> 1;\n", 'capture': "reg       ss_wr; initial ss_wr = 1'b0;\nreg [7:0] ss_wa;\nreg [7:0] ss_wd;\nalways @(posedge CLK) begin\n  ss_wr <= ss_regwin & reg_we_rising;\n  ss_wa <= DP_ADDR[7:0];\n  ss_wd <= DI;\nend\n", 'body': "// Decode the address at the existing restore capture edge; retain the original strobe and data pipeline.\nwire [15:0] stack_addr_word_q;\nreg [15:0] stack_restore_permit;\ndspx_stack_restore_address_decoder stack_restore_addr(\n  .CLK(CLK), .addr(DP_ADDR[7:0]), .word(stack_addr_word_q)\n);\nalways @* begin\n  stack_restore_permit = 16'h0000;\n  if(ss_wr) begin\n    if(stack_addr_word_q[0]) stack_restore_permit[0] = 1'b1;\n    if(stack_addr_word_q[1]) stack_restore_permit[1] = 1'b1;\n    if(stack_addr_word_q[2]) stack_restore_permit[2] = 1'b1;\n    if(stack_addr_word_q[3]) stack_restore_permit[3] = 1'b1;\n    if(stack_addr_word_q[4]) stack_restore_permit[4] = 1'b1;\n    if(stack_addr_word_q[5]) stack_restore_permit[5] = 1'b1;\n    if(stack_addr_word_q[6]) stack_restore_permit[6] = 1'b1;\n    if(stack_addr_word_q[7]) stack_restore_permit[7] = 1'b1;\n    if(stack_addr_word_q[8]) stack_restore_permit[8] = 1'b1;\n    if(stack_addr_word_q[9]) stack_restore_permit[9] = 1'b1;\n    if(stack_addr_word_q[10]) stack_restore_permit[10] = 1'b1;\n    if(stack_addr_word_q[11]) stack_restore_permit[11] = 1'b1;\n    if(stack_addr_word_q[12]) stack_restore_permit[12] = 1'b1;\n    if(stack_addr_word_q[13]) stack_restore_permit[13] = 1'b1;\n    if(stack_addr_word_q[14]) stack_restore_permit[14] = 1'b1;\n    if(stack_addr_word_q[15]) stack_restore_permit[15] = 1'b1;\n  end\nend\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd0) stack[0] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[0]) begin\n      if(ss_wa[0]) stack[0][10:8] <= ss_wd[2:0];\n      else         stack[0][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd1) stack[1] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[1]) begin\n      if(ss_wa[0]) stack[1][10:8] <= ss_wd[2:0];\n      else         stack[1][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd2) stack[2] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[2]) begin\n      if(ss_wa[0]) stack[2][10:8] <= ss_wd[2:0];\n      else         stack[2][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd3) stack[3] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[3]) begin\n      if(ss_wa[0]) stack[3][10:8] <= ss_wd[2:0];\n      else         stack[3][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd4) stack[4] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[4]) begin\n      if(ss_wa[0]) stack[4][10:8] <= ss_wd[2:0];\n      else         stack[4][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd5) stack[5] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[5]) begin\n      if(ss_wa[0]) stack[5][10:8] <= ss_wd[2:0];\n      else         stack[5][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd6) stack[6] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[6]) begin\n      if(ss_wa[0]) stack[6][10:8] <= ss_wd[2:0];\n      else         stack[6][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd7) stack[7] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[7]) begin\n      if(ss_wa[0]) stack[7][10:8] <= ss_wd[2:0];\n      else         stack[7][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd8) stack[8] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[8]) begin\n      if(ss_wa[0]) stack[8][10:8] <= ss_wd[2:0];\n      else         stack[8][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd9) stack[9] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[9]) begin\n      if(ss_wa[0]) stack[9][10:8] <= ss_wd[2:0];\n      else         stack[9][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd10) stack[10] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[10]) begin\n      if(ss_wa[0]) stack[10][10:8] <= ss_wd[2:0];\n      else         stack[10][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd11) stack[11] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[11]) begin\n      if(ss_wa[0]) stack[11][10:8] <= ss_wd[2:0];\n      else         stack[11][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd12) stack[12] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[12]) begin\n      if(ss_wa[0]) stack[12][10:8] <= ss_wd[2:0];\n      else         stack[12][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd13) stack[13] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[13]) begin\n      if(ss_wa[0]) stack[13][10:8] <= ss_wd[2:0];\n      else         stack[13][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd14) stack[14] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[14]) begin\n      if(ss_wa[0]) stack[14][10:8] <= ss_wd[2:0];\n      else         stack[14][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd15) stack[15] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[15]) begin\n      if(ss_wa[0]) stack[15][10:8] <= ss_wd[2:0];\n      else         stack[15][7:0] <= ss_wd;\n    end\n  end\nend\n", 'prefix': 'wire [15:0] stack_addr_word_q;\nreg [15:0] stack_restore_permit;\ndspx_stack_restore_address_decoder stack_restore_addr(\n  .CLK(CLK), .addr(DP_ADDR[7:0]), .word(stack_addr_word_q)\n);\n', 'permit': "always @* begin\n  stack_restore_permit = 16'h0000;\n  if(ss_wr) begin\n    if(stack_addr_word_q[0]) stack_restore_permit[0] = 1'b1;\n    if(stack_addr_word_q[1]) stack_restore_permit[1] = 1'b1;\n    if(stack_addr_word_q[2]) stack_restore_permit[2] = 1'b1;\n    if(stack_addr_word_q[3]) stack_restore_permit[3] = 1'b1;\n    if(stack_addr_word_q[4]) stack_restore_permit[4] = 1'b1;\n    if(stack_addr_word_q[5]) stack_restore_permit[5] = 1'b1;\n    if(stack_addr_word_q[6]) stack_restore_permit[6] = 1'b1;\n    if(stack_addr_word_q[7]) stack_restore_permit[7] = 1'b1;\n    if(stack_addr_word_q[8]) stack_restore_permit[8] = 1'b1;\n    if(stack_addr_word_q[9]) stack_restore_permit[9] = 1'b1;\n    if(stack_addr_word_q[10]) stack_restore_permit[10] = 1'b1;\n    if(stack_addr_word_q[11]) stack_restore_permit[11] = 1'b1;\n    if(stack_addr_word_q[12]) stack_restore_permit[12] = 1'b1;\n    if(stack_addr_word_q[13]) stack_restore_permit[13] = 1'b1;\n    if(stack_addr_word_q[14]) stack_restore_permit[14] = 1'b1;\n    if(stack_addr_word_q[15]) stack_restore_permit[15] = 1'b1;\n  end\nend\n", 'writes': "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd0) stack[0] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[0]) begin\n      if(ss_wa[0]) stack[0][10:8] <= ss_wd[2:0];\n      else         stack[0][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd1) stack[1] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[1]) begin\n      if(ss_wa[0]) stack[1][10:8] <= ss_wd[2:0];\n      else         stack[1][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd2) stack[2] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[2]) begin\n      if(ss_wa[0]) stack[2][10:8] <= ss_wd[2:0];\n      else         stack[2][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd3) stack[3] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[3]) begin\n      if(ss_wa[0]) stack[3][10:8] <= ss_wd[2:0];\n      else         stack[3][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd4) stack[4] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[4]) begin\n      if(ss_wa[0]) stack[4][10:8] <= ss_wd[2:0];\n      else         stack[4][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd5) stack[5] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[5]) begin\n      if(ss_wa[0]) stack[5][10:8] <= ss_wd[2:0];\n      else         stack[5][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd6) stack[6] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[6]) begin\n      if(ss_wa[0]) stack[6][10:8] <= ss_wd[2:0];\n      else         stack[6][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd7) stack[7] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[7]) begin\n      if(ss_wa[0]) stack[7][10:8] <= ss_wd[2:0];\n      else         stack[7][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd8) stack[8] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[8]) begin\n      if(ss_wa[0]) stack[8][10:8] <= ss_wd[2:0];\n      else         stack[8][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd9) stack[9] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[9]) begin\n      if(ss_wa[0]) stack[9][10:8] <= ss_wd[2:0];\n      else         stack[9][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd10) stack[10] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[10]) begin\n      if(ss_wa[0]) stack[10][10:8] <= ss_wd[2:0];\n      else         stack[10][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd11) stack[11] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[11]) begin\n      if(ss_wa[0]) stack[11][10:8] <= ss_wd[2:0];\n      else         stack[11][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd12) stack[12] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[12]) begin\n      if(ss_wa[0]) stack[12][10:8] <= ss_wd[2:0];\n      else         stack[12][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd13) stack[13] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[13]) begin\n      if(ss_wa[0]) stack[13][10:8] <= ss_wd[2:0];\n      else         stack[13][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd14) stack[14] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[14]) begin\n      if(ss_wa[0]) stack[14][10:8] <= ss_wd[2:0];\n      else         stack[14][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd15) stack[15] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[15]) begin\n      if(ss_wa[0]) stack[15][10:8] <= ss_wd[2:0];\n      else         stack[15][7:0] <= ss_wd;\n    end\n  end\nend\n", 'blocks': ["always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd0) stack[0] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[0]) begin\n      if(ss_wa[0]) stack[0][10:8] <= ss_wd[2:0];\n      else         stack[0][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd1) stack[1] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[1]) begin\n      if(ss_wa[0]) stack[1][10:8] <= ss_wd[2:0];\n      else         stack[1][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd2) stack[2] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[2]) begin\n      if(ss_wa[0]) stack[2][10:8] <= ss_wd[2:0];\n      else         stack[2][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd3) stack[3] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[3]) begin\n      if(ss_wa[0]) stack[3][10:8] <= ss_wd[2:0];\n      else         stack[3][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd4) stack[4] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[4]) begin\n      if(ss_wa[0]) stack[4][10:8] <= ss_wd[2:0];\n      else         stack[4][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd5) stack[5] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[5]) begin\n      if(ss_wa[0]) stack[5][10:8] <= ss_wd[2:0];\n      else         stack[5][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd6) stack[6] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[6]) begin\n      if(ss_wa[0]) stack[6][10:8] <= ss_wd[2:0];\n      else         stack[6][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd7) stack[7] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[7]) begin\n      if(ss_wa[0]) stack[7][10:8] <= ss_wd[2:0];\n      else         stack[7][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd8) stack[8] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[8]) begin\n      if(ss_wa[0]) stack[8][10:8] <= ss_wd[2:0];\n      else         stack[8][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd9) stack[9] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[9]) begin\n      if(ss_wa[0]) stack[9][10:8] <= ss_wd[2:0];\n      else         stack[9][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd10) stack[10] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[10]) begin\n      if(ss_wa[0]) stack[10][10:8] <= ss_wd[2:0];\n      else         stack[10][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd11) stack[11] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[11]) begin\n      if(ss_wa[0]) stack[11][10:8] <= ss_wd[2:0];\n      else         stack[11][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd12) stack[12] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[12]) begin\n      if(ss_wa[0]) stack[12][10:8] <= ss_wd[2:0];\n      else         stack[12][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd13) stack[13] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[13]) begin\n      if(ss_wa[0]) stack[13][10:8] <= ss_wd[2:0];\n      else         stack[13][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd14) stack[14] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[14]) begin\n      if(ss_wa[0]) stack[14][10:8] <= ss_wd[2:0];\n      else         stack[14][7:0] <= ss_wd;\n    end\n  end\nend\n", "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd15) stack[15] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[15]) begin\n      if(ss_wa[0]) stack[15][10:8] <= ss_wd[2:0];\n      else         stack[15][7:0] <= ss_wd;\n    end\n  end\nend\n"], 'scopedBody': "`ifdef MK2\n`ifdef DSP_COMP\n// Decode the address at the existing restore capture edge; retain the original strobe and data pipeline.\nwire [15:0] stack_addr_word_q;\nreg [15:0] stack_restore_permit;\ndspx_stack_restore_address_decoder stack_restore_addr(\n  .CLK(CLK), .addr(DP_ADDR[7:0]), .word(stack_addr_word_q)\n);\nalways @* begin\n  stack_restore_permit = 16'h0000;\n  if(ss_wr) begin\n    if(stack_addr_word_q[0]) stack_restore_permit[0] = 1'b1;\n    if(stack_addr_word_q[1]) stack_restore_permit[1] = 1'b1;\n    if(stack_addr_word_q[2]) stack_restore_permit[2] = 1'b1;\n    if(stack_addr_word_q[3]) stack_restore_permit[3] = 1'b1;\n    if(stack_addr_word_q[4]) stack_restore_permit[4] = 1'b1;\n    if(stack_addr_word_q[5]) stack_restore_permit[5] = 1'b1;\n    if(stack_addr_word_q[6]) stack_restore_permit[6] = 1'b1;\n    if(stack_addr_word_q[7]) stack_restore_permit[7] = 1'b1;\n    if(stack_addr_word_q[8]) stack_restore_permit[8] = 1'b1;\n    if(stack_addr_word_q[9]) stack_restore_permit[9] = 1'b1;\n    if(stack_addr_word_q[10]) stack_restore_permit[10] = 1'b1;\n    if(stack_addr_word_q[11]) stack_restore_permit[11] = 1'b1;\n    if(stack_addr_word_q[12]) stack_restore_permit[12] = 1'b1;\n    if(stack_addr_word_q[13]) stack_restore_permit[13] = 1'b1;\n    if(stack_addr_word_q[14]) stack_restore_permit[14] = 1'b1;\n    if(stack_addr_word_q[15]) stack_restore_permit[15] = 1'b1;\n  end\nend\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd0) stack[0] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[0]) begin\n      if(ss_wa[0]) stack[0][10:8] <= ss_wd[2:0];\n      else         stack[0][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd1) stack[1] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[1]) begin\n      if(ss_wa[0]) stack[1][10:8] <= ss_wd[2:0];\n      else         stack[1][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd2) stack[2] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[2]) begin\n      if(ss_wa[0]) stack[2][10:8] <= ss_wd[2:0];\n      else         stack[2][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd3) stack[3] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[3]) begin\n      if(ss_wa[0]) stack[3][10:8] <= ss_wd[2:0];\n      else         stack[3][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd4) stack[4] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[4]) begin\n      if(ss_wa[0]) stack[4][10:8] <= ss_wd[2:0];\n      else         stack[4][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd5) stack[5] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[5]) begin\n      if(ss_wa[0]) stack[5][10:8] <= ss_wd[2:0];\n      else         stack[5][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd6) stack[6] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[6]) begin\n      if(ss_wa[0]) stack[6][10:8] <= ss_wd[2:0];\n      else         stack[6][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd7) stack[7] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[7]) begin\n      if(ss_wa[0]) stack[7][10:8] <= ss_wd[2:0];\n      else         stack[7][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd8) stack[8] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[8]) begin\n      if(ss_wa[0]) stack[8][10:8] <= ss_wd[2:0];\n      else         stack[8][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd9) stack[9] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[9]) begin\n      if(ss_wa[0]) stack[9][10:8] <= ss_wd[2:0];\n      else         stack[9][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd10) stack[10] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[10]) begin\n      if(ss_wa[0]) stack[10][10:8] <= ss_wd[2:0];\n      else         stack[10][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd11) stack[11] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[11]) begin\n      if(ss_wa[0]) stack[11][10:8] <= ss_wd[2:0];\n      else         stack[11][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd12) stack[12] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[12]) begin\n      if(ss_wa[0]) stack[12][10:8] <= ss_wd[2:0];\n      else         stack[12][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd13) stack[13] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[13]) begin\n      if(ss_wa[0]) stack[13][10:8] <= ss_wd[2:0];\n      else         stack[13][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd14) stack[14] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[14]) begin\n      if(ss_wa[0]) stack[14][10:8] <= ss_wd[2:0];\n      else         stack[14][7:0] <= ss_wd;\n    end\n  end\nend\n\nalways @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n    if(push_now) begin\n      if(regs_sp == 4'd15) stack[15] <= pc + 1;\n    end\n  end else if(RST & ss_frozen) begin\n    if(stack_restore_permit[15]) begin\n      if(ss_wa[0]) stack[15][10:8] <= ss_wd[2:0];\n      else         stack[15][7:0] <= ss_wd;\n    end\n  end\nend\n`endif\n`endif\n", 'helper': '// Module-level control preserves this address-only capture stage.\n(* register_balancing="no" *)\nmodule dspx_stack_restore_address_decoder(\n  input CLK,\n  input [7:0] addr,\n  output reg [15:0] word\n);\nreg [15:0] word_d;\nwire [3:0] word_index = (addr - 8\'h34) >> 1;\ninitial word = 16\'h0000;\nalways @* begin\n  word_d = 16\'h0000;\n  if(addr >= 8\'h34 && addr <= 8\'h53) begin\n    if(word_index == 4\'d0) word_d[0] = 1\'b1;\n    if(word_index == 4\'d1) word_d[1] = 1\'b1;\n    if(word_index == 4\'d2) word_d[2] = 1\'b1;\n    if(word_index == 4\'d3) word_d[3] = 1\'b1;\n    if(word_index == 4\'d4) word_d[4] = 1\'b1;\n    if(word_index == 4\'d5) word_d[5] = 1\'b1;\n    if(word_index == 4\'d6) word_d[6] = 1\'b1;\n    if(word_index == 4\'d7) word_d[7] = 1\'b1;\n    if(word_index == 4\'d8) word_d[8] = 1\'b1;\n    if(word_index == 4\'d9) word_d[9] = 1\'b1;\n    if(word_index == 4\'d10) word_d[10] = 1\'b1;\n    if(word_index == 4\'d11) word_d[11] = 1\'b1;\n    if(word_index == 4\'d12) word_d[12] = 1\'b1;\n    if(word_index == 4\'d13) word_d[13] = 1\'b1;\n    if(word_index == 4\'d14) word_d[14] = 1\'b1;\n    if(word_index == 4\'d15) word_d[15] = 1\'b1;\n  end\nend\nalways @(posedge CLK) begin\n  word <= word_d;\nend\nendmodule\n', 'appendix': '\n`ifdef MK2\n`ifdef DSP_COMP\n// Module-level control preserves this address-only capture stage.\n(* register_balancing="no" *)\nmodule dspx_stack_restore_address_decoder(\n  input CLK,\n  input [7:0] addr,\n  output reg [15:0] word\n);\nreg [15:0] word_d;\nwire [3:0] word_index = (addr - 8\'h34) >> 1;\ninitial word = 16\'h0000;\nalways @* begin\n  word_d = 16\'h0000;\n  if(addr >= 8\'h34 && addr <= 8\'h53) begin\n    if(word_index == 4\'d0) word_d[0] = 1\'b1;\n    if(word_index == 4\'d1) word_d[1] = 1\'b1;\n    if(word_index == 4\'d2) word_d[2] = 1\'b1;\n    if(word_index == 4\'d3) word_d[3] = 1\'b1;\n    if(word_index == 4\'d4) word_d[4] = 1\'b1;\n    if(word_index == 4\'d5) word_d[5] = 1\'b1;\n    if(word_index == 4\'d6) word_d[6] = 1\'b1;\n    if(word_index == 4\'d7) word_d[7] = 1\'b1;\n    if(word_index == 4\'d8) word_d[8] = 1\'b1;\n    if(word_index == 4\'d9) word_d[9] = 1\'b1;\n    if(word_index == 4\'d10) word_d[10] = 1\'b1;\n    if(word_index == 4\'d11) word_d[11] = 1\'b1;\n    if(word_index == 4\'d12) word_d[12] = 1\'b1;\n    if(word_index == 4\'d13) word_d[13] = 1\'b1;\n    if(word_index == 4\'d14) word_d[14] = 1\'b1;\n    if(word_index == 4\'d15) word_d[15] = 1\'b1;\n  end\nend\nalways @(posedge CLK) begin\n  word <= word_d;\nend\nendmodule\n`endif\n`endif\n', 'scanRead': 'wire [10:0] ss_stk  = stack[ss_stk_idx];', 'returnRead': '              pc <= stack[regs_sp-1];', 'scanIndex': "wire [3:0] ss_stk_idx = (DP_ADDR[7:0] - 8'h34) >> 1;", 'writeIndex': "wire [3:0] ss_wstk_idx = (ss_wa - 8'h34) >> 1;"}

def need(value, message):
    if not value:
        raise ValueError(message)

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def save(path, value):
    Path(path).write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')

def once(text, before, after):
    need(text.count(before) == 1, 'Missing or ambiguous source boundary')
    return text.replace(before, after, 1)

def reference_permit():
    lines = ["always @* begin", "  stack_restore_permit = 16'h0000;",
             "  if(ss_wr) begin", "    if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin"]
    lines += [f"      if(ss_wstk_idx == 4'd{i}) stack_restore_permit[{i}] = 1'b1;" for i in range(16)]
    return '\n'.join(lines + ["    end", "  end", "end", ""])


def prepare(output):
    output.mkdir(parents=True, exist_ok=True)
    old_bytes = subprocess.check_output(['git','show',BASELINE + ':' + SOURCE])
    new_bytes = Path(SOURCE).read_bytes()
    need(sha(old_bytes) == ORIGINAL_SHA and sha(new_bytes) == CANDIDATE_SHA, 'Whole source identity changed')
    old, new = old_bytes.decode(), new_bytes.decode()
    need(new.endswith(FRAGMENTS['appendix']), 'Missing decoder scope')
    inverse = new[:-len(FRAGMENTS['appendix'])]
    for before, after in [(FRAGMENTS['anchor'] + FRAGMENTS['scopedBody'], FRAGMENTS['anchor']),
                          (FRAGMENTS['scopedPush'], FRAGMENTS['originalPush']),
                          (FRAGMENTS['scopedRestore'], FRAGMENTS['originalRestore'])]:
        inverse = once(inverse,before,after)
    need(inverse == old, 'Complete inverse changes more than the declared stack boundary')
    need(old.count(FRAGMENTS['capture']) == new.count(FRAGMENTS['capture']) == 1,
         'Original address/data/strobe capture changed')
    need(old.count(FRAGMENTS['scanRead']) == new.count(FRAGMENTS['scanRead']) == 1
         and old.count(FRAGMENTS['returnRead']) == new.count(FRAGMENTS['returnRead']) == 1,
         'Original read expressions changed')
    need(old.count('reg [10:0] stack [15:0];') == new.count('reg [10:0] stack [15:0];') == 1,
         'Original176-bit storage changed')
    push_context = "always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n\x60ifdef MK2\n    push_now <= 1'b0;\n" + FRAGMENTS['originalPush']
    need(old.count(push_context) == 1, 'Original CALL ancestors or clock changed')
    restore_context = re.search(r"  end else if\(RST & ss_frozen\) begin\n"
        r"    // savestate RESTORE.*?\n    if\(ss_wr\) begin\n"
        r"      if\(ss_wa >= 8'h34 && ss_wa <= 8'h53\) begin\n"
        + re.escape(FRAGMENTS['originalRestore']) + r"      end else case\(ss_wa\)", old, re.S)
    need(restore_context is not None, 'Original restore ancestors changed')
    main = Path('verilog/sd2snes_dsp/main.v').read_bytes()
    need(sha(main) == 'b8603c17eed9aaaf1cc290dd278462a9443a300b1e1278af2359cf08a8054869', 'Main/DP isolation/timer changed')
    for name,text in [('original',old),('candidate',new)]:
        (output/(name+'-upd77c25.v')).write_text(text,encoding='utf-8')
    configs = [('none',[]),('debug',['DEBUG']),('mk3',['MK3']),('mk3-debug',['MK3','DEBUG']),
               ('mk2',['MK2']),('mk2-debug',['MK2','DEBUG']),('dsp',['DSP_COMP']),
               ('dsp-debug',['DSP_COMP','DEBUG']),('mk3-dsp',['MK3','DSP_COMP']),
               ('mk3-dsp-debug',['MK3','DSP_COMP','DEBUG']),('mk2-dsp',['MK2','DSP_COMP']),
               ('mk2-dsp-debug',['MK2','DSP_COMP','DEBUG']),('mk2-dsp-lean',['MK2','DSP_COMP','DSP_LEAN']),
               ('mk3-dsp-lean',['MK3','DSP_COMP','DSP_LEAN']),('mk2-lean',['MK2','DSP_LEAN']),
               ('mk3-lean',['MK3','DSP_LEAN'])]
    preprocessing=[]
    for name,flags in configs:
        target='MK2' in flags and 'DSP_COMP' in flags
        header=Path('verilog/sd2snes_dspx' if target else 'verilog/sd2snes_dsp')
        pair={}
        for version in ('original','candidate'):
            path=output/('pp-'+name+'-'+version+'.v')
            subprocess.run(['iverilog','-g2012','-E','-I',str(header.resolve())]
                + ['-D'+flag for flag in flags] + ['-o',str(path),str(output/(version+'-upd77c25.v'))],check=True)
            pair[version]=path.read_text(encoding='utf-8');need(pair[version].strip(),'Empty preprocessing')
        if target:
            pair['original']=once(once(pair['original'],FRAGMENTS['originalPush'],''),FRAGMENTS['originalRestore'],'')
            pair['candidate']=once(once(pair['candidate'],FRAGMENTS['body'],''),FRAGMENTS['helper'],'')
        need(re.sub(r'\s+','',pair['original']) == re.sub(r'\s+','',pair['candidate']), 'Preprocessor scope changed: '+name)
        preprocessing.append(dict(name=name,flags=flags,target=target,header=header.as_posix()))
    visible = """reg [7:0] visible_data;
reg visible_lane, visible_valid;
always @* begin
  visible_data = 8'h00;
  visible_lane = 1'b0;
  visible_valid = 1'b0;
  if(ss_wr) begin
    visible_data = ss_wd;
    visible_lane = ss_wa[0];
    visible_valid = 1'b1;
  end
end
assign word_mask = stack_restore_permit;
assign qualified_data = visible_data;
assign qualified_lane = visible_lane;
assign qualified_valid = visible_valid;
assign pipeline_state = {ss_wd, ss_wa, ss_wr};
endmodule
"""
    producer_ports = """module producer_model(
  input CLK, ss_regwin, reg_we_rising,
  input [10:0] DP_ADDR, input [7:0] DI,
  output [15:0] word_mask,
  output [7:0] qualified_data,
  output qualified_lane, qualified_valid,
  output [16:0] pipeline_state
);
"""
    reference_decode=reference_permit()
    pgold=producer_ports + FRAGMENTS['capture'] + FRAGMENTS['writeIndex'] + "\nreg [15:0] stack_restore_permit;\n" + reference_decode + visible
    pgate=producer_ports + FRAGMENTS['capture'] + FRAGMENTS['prefix'] + FRAGMENTS['permit'] + visible + FRAGMENTS['helper']
    producer={'gold':pgold,'gate':pgate}
    producer_changes={
        'bad-capture-strobe':('ss_wr <= ss_regwin & reg_we_rising;', 'ss_wr <= ss_regwin;'),
        'bad-capture-data':('ss_wd <= DI;', "ss_wd <= DI ^ 8'h01;"),
        'bad-capture-lane':('ss_wa <= DP_ADDR[7:0];', "ss_wa <= DP_ADDR[7:0] ^ 8'h01;"),
        'bad-address-range':("if(addr >= 8'h34 && addr <= 8'h53)", "if(addr >= 8'h36 && addr <= 8'h53)"),
        'bad-address-word':("if(word_index == 4'd0)", "if(word_index == 4'd1)"),
        'bad-init-wr':("initial ss_wr = 1'b0;", "initial ss_wr = 1'b1;"),
        'bad-x-strobe':("  if(ss_wr) begin\n    if(stack_addr_word_q[0])",
                         "  if(ss_wr !== 1'b0) begin\n    if(stack_addr_word_q[0])"),
    }
    for name,(before,after) in producer_changes.items():
        producer[name]=once(pgate,before,after)
    xaddress=once(pgate,"if(addr >= 8'h34 && addr <= 8'h53)","if((addr >= 8'h34 && addr <= 8'h53) !== 1'b0)")
    for i in range(16):
        xaddress=once(xaddress,f"if(word_index == 4'd{i})",f"if((word_index == 4'd{i}) !== 1'b0)")
    producer['bad-x-address']=xaddress
    stack_ports="""module stack_model(
  input CLK, RST, ss_frozen, push_now, ss_wr,
  input [10:0] pc, DP_ADDR,
  input [3:0] regs_sp,
  input [7:0] ss_wa, ss_wd,
  output [10:0] scan_read, return_read,
  output [175:0] state
);
reg [10:0] stack [15:0];
"""
    stack_prefix=stack_ports+FRAGMENTS['scanIndex']+'\n'+FRAGMENTS['writeIndex']+'\n'
    stack_suffix='\nassign scan_read = stack[ss_stk_idx];\nassign return_read = stack[regs_sp-1];\n'
    stack_suffix+=''.join(f'assign state[{i*11} +: 11] = stack[{i}];\n' for i in range(16))+'endmodule\n'
    gold_write="always @(posedge CLK) begin\n  if(RST & ~ss_frozen) begin\n"+FRAGMENTS['originalPush']+"  end else if(RST & ss_frozen) begin\n    if(ss_wr) begin\n      if(ss_wa >= 8'h34 && ss_wa <= 8'h53) begin\n"+FRAGMENTS['originalRestore']+"      end\n    end\n  end\nend\n"
    cgold=stack_prefix+gold_write+stack_suffix
    cgate=stack_prefix+"reg [15:0] stack_restore_permit;\n"+reference_decode+FRAGMENTS['writes']+stack_suffix
    consumer={'gold':cgold,'gate':cgate}
    def block_mutation(model,word,before,after):
        block=FRAGMENTS['blocks'][word];changed=once(block,before,after)
        return once(model,block,changed)
    changes={
        'bad-data':(0,'stack[0] <= pc + 1;','stack[0] <= pc + 2;'),
        'bad-run':(0,'if(RST & ~ss_frozen)','if(RST)'),
        'bad-reset':(0,'if(RST & ~ss_frozen)','if(~ss_frozen)'),
        'bad-push':(0,'if(push_now)',"if(1'b1)"),
        'bad-restore':(0,'else if(RST & ss_frozen)','else if(RST & ~ss_frozen)'),
        'bad-word':(0,'if(stack_restore_permit[0])','if(stack_restore_permit[1])'),
        'bad-lane':(0,'if(ss_wa[0])','if(~ss_wa[0])'),
        'bad-restore-data':(0,'stack[0][7:0] <= ss_wd;',"stack[0][7:0] <= ss_wd ^ 8'h01;"),
        'bad-high-data':(0,'stack[0][10:8] <= ss_wd[2:0];','stack[0][10:8] <= ss_wd[7:5];'),
        'bad-hold':(0,'  end\nend\n',"  end else begin\n    stack[0] <= 11'h000;\n  end\nend\n"),
        'bad-x-push-data':(0,'stack[0] <= pc + 1;','stack[0] <= (pc + 1) ^ {11{ss_wa[0] ^ ss_wa[0]}};'),
        'bad-x-restore-data':(0,'stack[0][7:0] <= ss_wd;','stack[0][7:0] <= ss_wd ^ {8{pc[0] ^ pc[0]}};'),
        'bad-x-run':(0,'if(RST & ~ss_frozen)',"if((RST & ~ss_frozen) !== 1'b0)"),
    }
    for name,(word,before,after) in changes.items():
        consumer[name]=block_mutation(cgate,word,before,after)
    consumer['bad-return']=once(cgate,'assign return_read = stack[regs_sp-1];','assign return_read = stack[regs_sp+1];')
    consumer['bad-scan']=once(cgate,'assign scan_read = stack[ss_stk_idx];',"assign scan_read = stack[ss_stk_idx] ^ 11'h001;")
    need(len(producer)==10 and len(consumer)==17,'Unexpected complete model inventory')
    for family,models in [('producer',producer),('consumer',consumer)]:
        for name,text in models.items():
            (output/(family+'-'+name+'.v')).write_text(text,encoding='utf-8')
    producer_tests=[]
    for mode in ('binary','xstate'):
        for name in ['gate','bad-init-wr']:
            producer_tests.append(dict(model=name,observation='initial',mode=mode,expectedPass=name=='gate'))
        names=['gate','bad-capture-strobe','bad-capture-data','bad-capture-lane','bad-address-range','bad-address-word','bad-x-strobe','bad-x-address'] if mode=='binary' else ['gate','bad-x-strobe','bad-x-address']
        for name in names:
            producer_tests.append(dict(model=name,observation='next',mode=mode,expectedPass=name=='gate' or (mode=='binary' and name.startswith('bad-x-'))))
    consumer_tests=[]
    for mode in ('binary','xstate'):
        names=list(consumer)[1:] if mode=='binary' else ['gate','bad-x-push-data','bad-x-restore-data','bad-x-run']
        for name in names:
            consumer_tests.append(dict(model=name,mode=mode,expectedPass=name=='gate' or (mode=='binary' and name.startswith('bad-x-'))))
    save(output/'proof-plan.json',dict(producerModels=list(producer),consumerModels=list(consumer),
         producerTests=producer_tests,consumerTests=consumer_tests))
    save(output/'preprocessing.json',preprocessing)
    save(output/'source-boundary.json',dict(baseline=BASELINE,originalSha256=ORIGINAL_SHA,candidateSha256=CANDIDATE_SHA,
         exactFullSourceInverse=True,sourceBlocks=FRAGMENTS,originalProducerStateBits=17,newProducerStateBits=33,
         originalStackBits=176,newAddressControlBits=16,referencePermit=reference_decode,goldWrite=gold_write,
         nativeReturnUnchanged=FRAGMENTS['returnRead'],nativeScanUnchanged=FRAGMENTS['scanRead'],
         composition='Producer proves initial and every next qualified word/data/lane/strobe transaction. Consumer compares every176-bit state transition and both unchanged reads using that separately proved transaction boundary. No SAT assumptions or positive constraints.',
         initialContract='Original ss_wr init0 masks original uninitialized address/data. New16 address bits init0; no extra architectural latency.',
         wholeMappedOrElectricalQualification=False))
    (output/'source.diff').write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),'original','candidate')),encoding='utf-8')
    rows=[sha(p.read_bytes())+'  '+p.name for p in sorted(output.iterdir()) if p.is_file()]
    (output/'SHA256SUMS').write_text('\n'.join(rows)+'\n',encoding='utf-8')
    print('Bound complete source,16 configurations, producer lemma and176-bit consumer models; hosted proofs still required')



def module_bits(module):
    values = [b for p in module['ports'].values() for b in p['bits']]
    values += [b for n in module['netnames'].values() for b in n['bits']]
    values += [b for c in module['cells'].values() for v in c['connections'].values() for b in v]
    return values


def audit_state(design, family, variant):
    top = 'producer_model' if family == 'producer' else 'stack_model'
    need(set(design['modules']) == {top}, 'Unexpected module or blackbox')
    module = design['modules'][top]
    if family == 'producer':
        names = [('ss_wr',1),('ss_wa',8),('ss_wd',8)]
        if variant != 'gold':
            names += [('stack_addr_word_q',16)]
    else:
        names = [('stack['+str(i)+']',11) for i in range(16)]
    state=[]
    for name,width in names:
        need(name in module['netnames'] and len(module['netnames'][name]['bits']) == width, 'Missing named state: '+name)
        state += module['netnames'][name]['bits']
    need(len(state) == len(set(state)) and all(type(b) is int for b in state), 'Aliased or nonvariable state')
    observed = module['ports']['pipeline_state' if family == 'producer' else 'state']['bits']
    if family == 'producer':
        need(observed == state[:17], 'Producer state carrier ordering changed')
    else:
        # memory_memx retains guards on even constant-address read ports.
        # The actual carrier is therefore proved equal to named FF Qs below,
        # rather than assuming it must already be a direct wire alias.
        need(len(observed) == 176 and len(set(observed)) == 176
             and all(type(b) is int for b in observed)
             and module['ports']['state']['direction'] == 'output', 'Invalid complete stack observation carrier')
    clock=module['ports']['CLK']['bits']
    need(len(clock)==1 and module['ports']['CLK']['direction']=='input', 'Invalid clock boundary')
    expected_init={}
    if family == 'producer':
        expected_init[state[0]] = '1' if variant == 'bad-init-wr' else '0'
        if variant != 'gold':
            expected_init.update({bit:'0' for bit in state[17:]})
    concrete_init={}
    for net in module['netnames'].values():
        value=net.get('attributes',{}).get('init')
        if value is None:
            continue
        need(family=='producer', 'Original stack must retain no reset/initializer')
        need(len(value)==len(net['bits']), 'Invalid initializer width')
        for bit,digit in zip(net['bits'],reversed(value)):
            need(type(bit) is int and bit in state and digit in '01x', 'Invalid initializer target')
            if digit=='x':
                continue
            need(bit not in concrete_init or concrete_init[bit]==digit, 'Conflicting initial values')
            concrete_init[bit]=digit
    need(concrete_init==expected_init, 'Source initialization contract changed')
    qd={};registers=[]
    for name,cell in module['cells'].items():
        kind=cell['type']
        if kind!='$dff':
            need(kind.startswith('$') and not any(x in kind.lower() for x in ('ff','latch','mem'))
                 and kind not in ('$anyseq','$anyconst') and 'CLK' not in cell['connections'], 'Hidden state or blackbox')
            continue
        need(cell['connections']['CLK']==clock and int(cell['parameters']['CLK_POLARITY'],2)==1, 'State clock or edge changed')
        q,d=cell['connections']['Q'],cell['connections']['D']
        need(len(q)==len(d), 'Invalid D/Q width')
        for qb,db in zip(q,d):
            need(qb not in qd, 'Multiply driven Q');qd[qb]=db
        registers.append(name)
    need(set(qd)==set(state), 'Named state does not cover every actual FF Q/D')
    inputs={b for p in module['ports'].values() if p['direction']=='input' for b in p['bits']}
    need(not inputs.intersection(state), 'State aliases source input')
    for name,cell in module['cells'].items():
        if name not in registers:
            for port,bits in cell['connections'].items():
                if cell['port_directions'][port]=='output':
                    need(not set(bits).intersection(state), 'Non-FF state driver')
    audit=dict(family=family,variant=variant,stateNames=names,qBits=state,dBits=[qd[b] for b in state],
               concreteInit=[dict(qBit=b,value=expected_init[b]) for b in state if b in expected_init],
               uninitializedQ=[b for b in state if b not in expected_init],positiveSingleClock=True,
               stateCarrierBits=observed,noHiddenState=True)
    return module,state,qd,registers,expected_init,audit


def producer_no_feedback(module,state,qd,registers):
    drivers={}
    for name,cell in module['cells'].items():
        if name in registers:
            continue
        inputs=[b for p,bits in cell['connections'].items() if cell['port_directions'][p]=='input' for b in bits]
        for port,bits in cell['connections'].items():
            if cell['port_directions'][port]=='output':
                for bit in bits:
                    if type(bit) is int:
                        need(bit not in drivers, 'Multiple combinational drivers')
                        drivers[bit]=inputs
    state_set=set(state)
    for start in qd.values():
        pending=[start];seen=set()
        while pending:
            bit=pending.pop()
            if type(bit) is not int or bit in seen:
                continue
            need(bit not in state_set, 'Producer next state depends on current Q; forward substitution invalid')
            seen.add(bit);pending.extend(drivers.get(bit,[]))


def strip_registers(module,registers):
    for name in registers:
        del module['cells'][name]
    for net in module['netnames'].values():
        net.get('attributes',{}).pop('init',None)


def substitute_bits(module,mapping):
    def sub(bits):
        return [mapping.get(bit,bit) if type(bit) is int else bit for bit in bits]
    for p in module['ports'].values():
        p['bits']=sub(p['bits'])
    for n in module['netnames'].values():
        n['bits']=sub(n['bits'])
    for c in module['cells'].values():
        c['connections']={p:sub(bits) for p,bits in c['connections'].items()}


def producer_transform(design,variant,observation):
    need(observation in ('initial','next'), 'Invalid producer observation')
    module,state,qd,registers,initial,audit=audit_state(design,'producer',variant)
    producer_no_feedback(module,state,qd,registers)
    first=max(b for b in module_bits(module) if type(b) is int)+1
    symbols=list(range(first,first+32))
    need('initial_state_in' not in module['ports'] and 'initial_state_in' not in module['netnames'], 'Initial boundary already exists')
    if observation=='initial':
        unknown=[b for b in state if b not in initial]
        need(len(unknown)==16, 'Exactly16 original uninitialized address/data bits required')
        selected=symbols[:16] if variant=='gold' else symbols[16:]
        mapping=dict(initial);mapping.update(dict(zip(unknown,selected)))
    else:
        mapping=qd
    strip_registers(module,registers)
    substitute_bits(module,mapping)
    carrier=module['ports'].pop('pipeline_state')
    if observation=='next':
        module['ports']['captured_pipeline']=carrier
        module['netnames']['captured_pipeline']=dict(hide_name=0,bits=carrier['bits'],attributes={})
    module['ports']['initial_state_in']=dict(direction='input',bits=symbols)
    module['netnames']['initial_state_in']=dict(hide_name=0,bits=symbols,attributes={})
    module.get('attributes',{}).pop('top',None)
    design['modules']={'gold' if variant=='gold' else 'gate':module}
    audit.update(observation=observation,replacement=[dict(qBit=b,value=mapping[b]) for b in state],
                 commonInitialInputBits=symbols,initialUnknownInputsIndependent=True,
                 nextConesContainNoQ=True,removedRegisters=registers,
                 retainedTransactionOutputs=['word_mask','qualified_data','qualified_lane','qualified_valid'],
                 capturedPipelineCompared=observation=='next')
    return design,audit


def consumer_transform(design,variant):
    module,state,qd,registers,initial,audit=audit_state(design,'consumer',variant)
    need(len(state)==176 and not initial,'All176 uninitialized stack bits required')
    observed=list(module['ports']['state']['bits'])
    first=max(b for b in module_bits(module) if type(b) is int)+1
    strip_registers(module,registers)
    eqname='$state_view_strict_eq'
    need(eqname not in module['cells'],'State view cell already exists')
    module['cells'][eqname]=dict(hide_name=1,type='$eqx',attributes={},
        parameters=dict(A_SIGNED='0'*32,B_SIGNED='0'*32,A_WIDTH=format(176,'032b'),
                        B_WIDTH=format(176,'032b'),Y_WIDTH=format(1,'032b')),
        port_directions=dict(A='input',B='input',Y='output'),
        connections=dict(A=observed,B=list(state),Y=[first]))
    del module['ports']['state']
    for name,direction,bits in [('state_in','input',state),('next_state','output',[qd[b] for b in state]),
                                ('state_view_ok','output',[first])]:
        need(name not in module['ports'] and name not in module['netnames'],'State boundary already exists')
        module['ports'][name]=dict(direction=direction,bits=list(bits))
        module['netnames'][name]=dict(hide_name=0,bits=list(bits),attributes={})
    module.get('attributes',{}).pop('top',None)
    design['modules']={'gold' if variant=='gold' else 'gate':module}
    audit.update(observation='arbitrary common176-bit current state',removedRegisters=registers,
                 noStateValueConstraints=True,reads=['scan_read','return_read'])
    return design,audit


def audit_controls(original,family,variant):
    controls=[]
    names = ['wrong-clock','duplicate-Q','wrong-init']
    if family == 'producer':
        names.append('wrong-state-view')
    for name in names:
        changed=copy.deepcopy(original)
        top='producer_model' if family=='producer' else 'stack_model'
        module=changed['modules'][top]
        ff=next(c for c in module['cells'].values() if c['type']=='$dff' and len(c['connections']['Q'])>1)
        if name=='wrong-clock':
            ff['parameters']['CLK_POLARITY']='0'*32
        elif name=='duplicate-Q':
            ff['connections']['Q'][1]=ff['connections']['Q'][0]
        elif name=='wrong-init':
            if family=='producer':
                net=next(n for n in module['netnames'].values() if any(v in '01' for v in n.get('attributes',{}).get('init','')))
                init=net['attributes']['init'];at=next(i for i,c in enumerate(init) if c in '01')
                net['attributes']['init']=init[:at]+('1' if init[at]=='0' else '0')+init[at+1:]
            else:
                module['netnames']['stack[0]'].setdefault('attributes',{})['init']='0'*11
        else:
            port=module['ports']['pipeline_state' if family=='producer' else 'state']
            port['bits'][0],port['bits'][1]=port['bits'][1],port['bits'][0]
        try:
            audit_state(changed,family,variant)
        except ValueError as error:
            controls.append(dict(name=name,rejected=True,error=str(error)))
        else:
            raise ValueError('Accepted corrupt state boundary: '+name)
    return controls


def cut_producer(source,output,variant):
    output.mkdir(parents=True,exist_ok=True)
    original=json.loads(source.read_text(encoding='utf-8'))
    controls=audit_controls(original,'producer',variant)
    save(output/'state-controls.json',controls)
    for observation in ('initial','next'):
        transformed,audit=producer_transform(copy.deepcopy(original),variant,observation)
        save(output/(observation+'.json'),transformed)
        save(output/(observation+'-audit.json'),audit)
    print('producer '+variant+': all source FFs/clock/init and Q-free D cones audited; initial/next transaction observations retained')


def cut_consumer(source,output,variant):
    output.mkdir(parents=True,exist_ok=True)
    original=json.loads(source.read_text(encoding='utf-8'))
    controls=audit_controls(original,'consumer',variant)
    save(output/'state-controls.json',controls)
    transformed,audit=consumer_transform(copy.deepcopy(original),variant)
    save(output/'transition.json',transformed);save(output/'state-audit.json',audit)
    if variant=='gold':
        changed=copy.deepcopy(transformed)
        bits=changed['modules']['gold']['cells']['$state_view_strict_eq']['connections']['B']
        bits[0],bits[1]=bits[1],bits[0]
        save(output/'state-view-mutant.json',changed)
    print('consumer '+variant+': all176 positive-edge FF Q/D bits, no reset/init or hidden state; full reads retained')



def yosys_run(directory,label,program,expected_pass=True,witness=None,timeout=600):
    directory.mkdir(parents=True,exist_ok=True)
    script=directory/(label+'.ys')
    script.write_text(program.rstrip()+'\n',encoding='utf-8')
    log=directory/(label+'.log')
    argv=['yosys','-l',log.name,'-s',script.name]
    record=dict(argv=argv,cwd=str(directory.resolve()),scriptSha256=sha(script.read_bytes()),
                expectedPass=expected_pass)
    save(directory/(label+'-attempt.json'),record)
    print(json.dumps(dict(command=argv,directory=str(directory)),sort_keys=True),flush=True)
    try:
        result=subprocess.run(argv,cwd=directory,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                              timeout=timeout)
    except subprocess.TimeoutExpired as error:
        raw=error.stdout or b''
        (directory/(label+'-console.log')).write_bytes(raw)
        record.update(timeout=True,accepted=False,stdoutBytes=len(raw),stdoutSha256=sha(raw))
        save(directory/(label+'-status.json'),record)
        raise ValueError('Hosted proof command timed out: '+label)
    raw=result.stdout
    need(len(raw)<=32000000 and b'\0' not in raw,'Incomplete or oversized proof console')
    text=raw.decode('utf-8')
    (directory/(label+'-console.log')).write_bytes(raw)
    print(text,end='' if text.endswith('\n') else '\n',flush=True)
    logged=log.read_text(encoding='utf-8')
    if expected_pass:
        accepted=result.returncode==0
        if witness is not None:
            accepted=accepted and 'SAT proof finished - no model found: SUCCESS!' in logged
    else:
        accepted=(result.returncode!=0 and 'SAT proof finished - model found: FAIL!' in logged
                  and witness is not None and (directory/witness).is_file())
        if accepted:
            counter=json.loads((directory/witness).read_text(encoding='utf-8'))
            accepted=isinstance(counter.get('signal'),list) and bool(counter['signal'])
    record.update(exit=result.returncode,timeout=False,accepted=accepted,stdoutBytes=len(raw),
                  stdoutSha256=sha(raw),yosysLogSha256=sha(log.read_bytes()))
    save(directory/(label+'-status.json'),record)
    need(accepted,'Unexpected hosted command/proof result: '+label)
    return record


def qpath(path):
    return json.dumps(path.resolve().as_posix())


def validate_miter(path,family,observation=None,design=None):
    original = design is None
    if original:
        design=json.loads(path.read_text(encoding='utf-8'))
    need(set(design['modules'])=={'miter'},'Unexpected actual miter modules')
    module=design['modules']['miter']
    if family=='producer':
        expected_inputs=dict(CLK=1,ss_regwin=1,reg_we_rising=1,DP_ADDR=11,DI=8,initial_state_in=32)
        expected_outputs=dict(word_mask=16,qualified_data=8,qualified_lane=1,qualified_valid=1)
        if observation=='next':
            expected_outputs['captured_pipeline']=17
    else:
        expected_inputs=dict(CLK=1,RST=1,ss_frozen=1,push_now=1,ss_wr=1,pc=11,DP_ADDR=11,
                             regs_sp=4,ss_wa=8,ss_wd=8,state_in=176)
        expected_outputs=dict(next_state=176,scan_read=11,return_read=11,state_view_ok=1)
    actual_inputs={name[3:]:len(port['bits']) for name,port in module['ports'].items() if port['direction']=='input' and name.startswith('in_')}
    need(actual_inputs==expected_inputs,'Common source/state input contract changed')
    need(len([p for p in module['ports'].values() if p['direction']=='input'])==len(expected_inputs),
         'Extra miter input')
    for name,width in expected_inputs.items():
        bits=module['ports']['in_'+name]['bits']
        need(module['netnames']['gold.'+name]['bits']==bits==module['netnames']['gate.'+name]['bits'],
             'Two models do not share the same input: '+name)
    comparisons=[]
    for name,width in expected_outputs.items():
        av=module['ports']['gold_'+name]['bits'];bv=module['ports']['gate_'+name]['bits']
        y=module['ports']['cmp_'+name]['bits']
        need(len(av)==len(bv)==width and len(y)==1,'Missing or truncated output comparison')
        matches=[c for c in module['cells'].values() if c['type']=='$eqx'
                 and c['connections']==dict(A=av,B=bv,Y=y)]
        need(len(matches)==1,'Comparison must be strict Eqx: '+name)
        comparisons+=y
    reductions=[c for c in module['cells'].values() if c['type']=='$reduce_and'
                and len(c['connections']['A'])==len(comparisons) and set(c['connections']['A'])==set(comparisons)]
    need(len(reductions)==1,'Every required comparison must reach the assertion')
    assertions=[c for c in module['cells'].values() if c['type']=='$assert']
    need(len(assertions)==1 and assertions[0]['connections']==dict(A=reductions[0]['connections']['Y'],EN=['1']),
         'Missing, disabled or incomplete assertion')
    need(not any(c['type']=='$assume' or any(v in c['type'].lower() for v in ('dff','latch','mem'))
                 for c in module['cells'].values()),'Miter retains assumptions or hidden sequential state')
    receipt=dict(family=family,observation=observation,inputPorts=expected_inputs,
                 inputBits=sum(expected_inputs.values()),outputWidths=expected_outputs,
                 strictComparisons=len(comparisons),assertionEnabled=True,noAssumptions=True,
                 actualMiterSha256=sha(path.read_bytes()))
    if original:
        save(path.with_name(path.stem+'-audit.json'),receipt)
    return receipt


def miter_controls(path,family,observation):
    source=json.loads(path.read_text(encoding='utf-8'))
    rows=[]
    for name in ('loose-equality','disabled-assertion','incomplete-reduction','different-input','hidden-assumption'):
        design=copy.deepcopy(source); module=design['modules']['miter']
        if name=='loose-equality':
            output='word_mask' if family=='producer' else 'next_state'
            eq=next(c for c in module['cells'].values() if c['type']=='$eqx'
                    and c['connections']['Y']==module['ports']['cmp_'+output]['bits'])
            eq['type']='$eq'
        elif name=='disabled-assertion':
            assertion=next(c for c in module['cells'].values() if c['type']=='$assert')
            assertion['connections']['EN']=['0']
        elif name=='incomplete-reduction':
            assertion=next(c for c in module['cells'].values() if c['type']=='$assert')
            reduction=next(c for c in module['cells'].values() if c['type']=='$reduce_and'
                           and c['connections']['Y']==assertion['connections']['A'])
            reduction['connections']['A']=reduction['connections']['A'][:-1]
        elif name=='different-input':
            module['netnames']['gate.CLK']['bits']=['0']
        else:
            module['cells']['$unexpected_assume']=dict(type='$assume',connections=dict(A=['1'],EN=['1']))
        try:
            validate_miter(path,family,observation,design)
        except ValueError as error:
            rows.append(dict(name=name,rejected=True,error=str(error)))
        else:
            raise ValueError('Accepted corrupt actual miter graph: '+name)
    save(path.with_name(path.stem+'-controls.json'),rows)


def prove(output):
    plan=json.loads((output/'proof-plan.json').read_text(encoding='utf-8'))
    results=[]
    for family,key in [('producer','producerModels'),('consumer','consumerModels')]:
        for variant in plan[key]:
            need(re.fullmatch(r'(gold|gate|bad-[a-z0-9-]+)',variant) is not None,'Untrusted model name')
            directory=output/family/variant
            directory.mkdir(parents=True,exist_ok=True)
            model=output/(family+'-'+variant+'.v')
            (directory/'model.v').write_bytes(model.read_bytes())
            top='producer_model' if family=='producer' else 'stack_model'
            commands='read_verilog -sv -formal model.v\nhierarchy -check -top '+top+'\nflatten\nproc -ifx -noopt\ncheck -assert\n'
            if family=='consumer':
                commands+='memory_memx\nmemory_collect\nmemory_map\n'
            commands+='dffunmap\nsetundef -undriven -undef\nopt_clean\ncheck -assert\nwrite_json state.json\n'
            results.append(dict(family=family,model=variant,stage='preparation',
                                result=yosys_run(directory,'preparation',commands)))
            if family=='producer':
                cut_producer(directory/'state.json',directory,variant)
            else:
                cut_consumer(directory/'state.json',directory,variant)
                prefix='gold' if variant=='gold' else 'gate'
                results.append(dict(family=family,model=variant,stage='state-view',
                    result=yosys_run(directory,'state-view',
                      'read_json transition.json\nhierarchy -check -top '+prefix+'\ncheck -assert\n'
                      'sat -verify -enable_undef -prove state_view_ok 1 -show-inputs -show state_view_ok '
                      '-dump_json state-view-counterexample.json -timeout 180\n',
                      True,'state-view-counterexample.json')))
                if variant=='gold':
                    results.append(dict(family=family,model=variant,stage='state-view-mutant',
                        result=yosys_run(directory,'state-view-mutant',
                          'read_json state-view-mutant.json\nhierarchy -check -top gold\ncheck -assert\n'
                          'sat -verify -enable_undef -set-def-inputs -prove state_view_ok 1 '
                          '-show-inputs -show state_view_ok -dump_json state-view-mutant-counterexample.json -timeout 180\n',
                          False,'state-view-mutant-counterexample.json')))
    for family,key in [('producer','producerTests'),('consumer','consumerTests')]:
        for test in plan[key]:
            variant=test['model'];mode=test['mode'];observation=test.get('observation')
            directory=output/family/variant
            filename=(observation+'.json') if family=='producer' else 'transition.json'
            gold=output/family/'gold'/filename;gate=directory/filename
            label=('miter-'+observation+'-'+mode) if observation else ('miter-'+mode)
            build=('read_json '+qpath(gold)+'\nread_json '+qpath(gate)+'\n'
                   'miter -equiv -make_assert -make_outputs -make_outcmp gold gate miter\n'
                   'hierarchy -check -top miter\nflatten -wb\nhierarchy -check -top miter\n'
                   'opt_clean\ncheck -assert\nwrite_json '+label+'.json\n')
            results.append(dict(family=family,model=variant,stage=label+'-build',
                                result=yosys_run(directory,label+'-build',build)))
            audit=validate_miter(directory/(label+'.json'),family,observation)
            if variant=='gate' and mode=='binary':
                miter_controls(directory/(label+'.json'),family,observation)
            flags='-set-def-inputs ' if mode=='binary' else ''
            witness=label+'-counterexample.json'
            program=('read_json '+label+'.json\nhierarchy -check -top miter\ncheck -assert\n'
                     'sat -verify -enable_undef '+flags+'-prove-asserts -show-inputs -show-outputs '
                     '-dump_json '+witness+' -timeout 300\n')
            result=yosys_run(directory,label+'-proof',program,test['expectedPass'],witness)
            results.append(dict(family=family,model=variant,mode=mode,observation=observation,
                                stage='transition-proof',expectedPass=test['expectedPass'],
                                miterAudit=audit,result=result))
    save(output/'proof-results.json',dict(complete=True,results=results,
         producerInitialAndNextBinaryAndX=True,consumerAll176BitsAndReadsBinaryAndX=True,
         actualNegativeWitnessesRequired=True,noPositiveSatAssumptionsOrForcedInputs=True,
         scope='Closed producer/consumer component proof only; native mapping/timing and external I/O are separate.'))
    message=('Complete source inverse and16 configurations; source-derived producer initial/next transaction lemma '
             'and all176 consumer next-state bits/both unchanged reads passed strict binary/X proofs. '
             'All designated negative controls yielded real counterexamples; all actual FF/clock/init/state boundaries audited. '
             'Component/source proof only; no native or I/O/hardware timing qualification.\n')
    (output/'verified.txt').write_text(message,encoding='utf-8')
    print(message,end='')



def collect(source, output):
    raw_source = source.read_bytes()
    text = raw_source.decode('utf-8')
    starts = re.findall(r'(?m)^\s*(inst|net)\s+"', text)
    statements = re.findall(r'(?ms)^\s*(?:inst|net)\s+".*?;', text)
    need(starts and len(starts) == len(statements), 'Missing or incomplete physical statements')
    instances, nets = {}, {}
    for statement in statements:
        match = re.match(r'\s*(inst|net)\s+"([^"\n]+)"', statement)
        need(match is not None, 'Unrecognized physical statement')
        kind, name = match.groups()
        target = instances if kind == 'inst' else nets
        need(name not in target, 'Duplicate physical statement')
        target[name] = statement.strip()
    need(len(instances) > 1000 and len(nets) > 1000, 'Unexpectedly small mapped design')
    output.mkdir(parents=True, exist_ok=True)
    pin = re.compile(r'\b(outpin|inpin)\s+"([^"\n]+)"\s+([A-Za-z0-9_]+)')
    stack_pattern = r'snes_dspx/stack(?:_(\d+)_(\d+)|<(\d+)><(\d+)>)(.*)'
    decoder_pattern = r'snes_dspx/(?:stack_restore_addr/word|stack_addr_word_q)(?:_(\d+)|<(\d+)>)(.*)'
    stack, decoder, unrecognized = [], [], []
    for component, statement in instances.items():
        for slot, logical in re.findall(r'\b(FFX|FFY):([^:\s]+):#FF(?=\s|$)', statement):
            a, b = re.fullmatch(stack_pattern, logical), re.fullmatch(decoder_pattern, logical)
            binding = dict(component=component, slot=slot, logical=logical)
            if a:
                word = int(a.group(1) or a.group(3)); bit = int(a.group(2) or a.group(4))
                stack.append(dict(binding, word=word, bit=bit, suffix=a.group(5)))
            elif b:
                bit = int(b.group(1) or b.group(2))
                clocks = [name for name, statement_net in nets.items()
                          if ('inpin', component, 'CLK') in pin.findall(statement_net)]
                decoder.append(dict(binding, bit=bit, suffix=b.group(3), clockNets=clocks,
                                    positiveClock=re.search(r'\bCLKINV::CLK(?=\s|$)', statement) is not None,
                                    init0=slot+'_INIT_ATTR::INIT0' in statement))
            elif logical.startswith('snes_dspx/') and any(x in logical for x in ('stack_', 'stack_restore_addr', 'stack_addr_word_q')):
                unrecognized.append(binding)
    parts = []
    for label, words in [('stack-0-3', range(0,4)), ('stack-4-7', range(4,8)),
                         ('stack-8-11', range(8,12)), ('stack-12-15', range(12,16)), ('decoder', [])]:
        if label == 'decoder':
            selected = {name for name, statement in instances.items()
                        if 'snes_dspx/stack_restore_addr/' in statement or 'snes_dspx/stack_addr_word_q' in statement}
        else:
            selected = {name for name, statement in instances.items()
                        if any(re.search(r'snes_dspx/stack(?:_'+str(word)+r'_|<'+str(word)+r'>)', statement) for word in words)}
        seeds = sorted(selected)
        selected_nets = {name for name, statement in nets.items()
                         if any(component in selected for _, component, _ in pin.findall(statement))}
        for name in selected_nets:
            selected.update(component for kind, component, _ in pin.findall(nets[name])
                            if kind == 'outpin' and component in instances)
        rows = [instances[name] for name in sorted(selected)] + [nets[name] for name in sorted(selected_nets)]
        raw = '\n\n'.join(rows) + '\n'
        bounded = len(selected) <= 400 and len(selected_nets) <= 1200 and len(raw.encode()) <= 3000000
        entry = dict(name=label, seedComponents=seeds, components=sorted(selected), nets=sorted(selected_nets),
                     instanceCount=len(selected), netCount=len(selected_nets), bytes=len(raw.encode()),
                     sha256=sha(raw.encode()), withinBounds=bounded)
        parts.append(entry)
        # Never truncate a record or silently increase the declared raw bound.
        if bounded:
            (output/(label+'-raw-statements.txt')).write_text(raw, encoding='utf-8')
    observed = {(b['word'], b['bit']) for b in stack}
    expected = {(word,bit) for word in range(16) for bit in range(11)}
    missing = sorted(expected-observed)
    index = dict(sourceBytes=len(raw_source), sourceSha256=sha(raw_source),
                 totalInstances=len(instances), totalNets=len(nets), parts=parts,
                 stackBindings=stack, decoderBindings=decoder, unrecognizedFFs=unrecognized,
                 missingStackWordBits=missing, extraStackWordBits=sorted(observed-expected),
                 scope='Complete named state excerpts with co-packed records, all incident nets and their immediate source components. Retimed stack aliases retained; not whole mapped equivalence.')
    save(output/'stack-address-physical-index.json', index)
    need(all(p['withinBounds'] for p in parts), 'Physical excerpt exceeds fixed400COMP/1200net/3MB bound; no truncation')
    need(not missing and not observed-expected, 'Incomplete or invalid176 stack word/bit observations; raw retained')
    all_bindings = stack+decoder
    need(len({(b['component'],b['slot']) for b in all_bindings}) == len(all_bindings), 'Duplicate physical FF slot')
    need(len(decoder) == 16 and {b['bit'] for b in decoder} == set(range(16)), 'Expected exactly16 decoder FFs')
    need(all(b['suffix'] == '' for b in decoder), 'Decoder state was retimed or renamed; raw retained')
    need(all(b['clockNets'] == ['CLK2'] and b['positiveClock'] and b['init0'] for b in decoder),
         'Decoder clock or INIT0 contract not observed; raw retained')
    need(not unrecognized, 'Unrecognized stack/decoder FF alias; raw retained')
    print('Retained complete bounded raw records for176 stack word/bits and16 positiveCLK2 INIT0 address decoder FFs')


def collect_controls(output):
    output.mkdir(parents=True, exist_ok=True)
    fixture = '\n'.join('inst "dummy'+str(i)+'" "SLICEL", cfg " F::#OFF ";' for i in range(1001))+'\n'
    fixture += '\n'.join('net "dummy'+str(i)+'";' for i in range(1001))+'\n'
    for word in range(16):
        for bit in range(11):
            fixture += 'inst "stack'+str(word)+'_'+str(bit)+'" "SLICEL", cfg " FFX:snes_dspx/stack_'+str(word)+'_'+str(bit)+':#FF ";\n'
    for bit in range(16):
        fixture += 'inst "decode'+str(bit)+'" "SLICEL", cfg " FFX:snes_dspx/stack_restore_addr/word_'+str(bit)+':#FF FFX_INIT_ATTR::INIT0 CLKINV::CLK ";\n'
    fixture += 'net "CLK2", '+', '.join('inpin "decode'+str(bit)+'" CLK' for bit in range(16))+';\n'
    cases = [('complete original and decoder state', fixture, True),
             ('retimed stack aliases retained', fixture.replace('stack_0_0:#FF', 'stack_0_0_BRB1:#FF'), True),
             ('output-named decoder state', fixture.replace('stack_restore_addr/word_', 'stack_addr_word_q_'), True),
             ('missing stack bit', fixture.replace('stack_0_0:#FF', 'other_0_0:#FF'), False),
             ('missing decoder bit', fixture.replace('stack_restore_addr/word_5:#FF', 'other5:#FF'), False),
             ('LUT is not FF', fixture.replace('FFX:snes_dspx/stack_0_0:#FF', 'F:snes_dspx/stack_0_0:#LUT:D=A1'), False),
             ('duplicate instance', fixture+'inst "dummy0" "SLICEL", cfg " F::#OFF ";\n', False),
             ('duplicate net', fixture+'net "dummy0";\n', False),
             ('incomplete record', fixture+'net "incomplete"', False),
             ('duplicate FF slot', fixture.replace('FFX:snes_dspx/stack_0_0:#FF', 'FFX:snes_dspx/stack_0_0:#FF FFX:snes_dspx/stack_0_1:#FF'), False),
             ('decoder clock absent', fixture.replace('inpin "decode0" CLK', 'inpin "decode0" CE'), False),
             ('decoder inverted clock', fixture.replace('CLKINV::CLK', 'CLKINV::CLK_B'), False),
             ('decoder init changed', fixture.replace('FFX_INIT_ATTR::INIT0', 'FFX_INIT_ATTR::INIT1'), False),
             ('decoder retimed', fixture.replace('word_0:#FF', 'word_0_BRB1:#FF'), False)]
    rows = []
    for i, (name, text, expected) in enumerate(cases):
        path = output/(str(i)+'.xdl.txt'); path.write_text(text, encoding='utf-8')
        error = None
        try:
            collect(path, output/str(i)); accepted = True
        except ValueError as failure:
            accepted, error = False, str(failure)
        rows.append(dict(name=name, expected=expected, accepted=accepted, error=error, passed=accepted == expected))
    save(output/'results.json', dict(controls=rows, passed=all(row['passed'] for row in rows)))
    need(all(row['passed'] for row in rows), 'Physical text collector controls failed')


def timing(text):
    par, twr = text['par'], text['twr']
    scores = re.findall(r'Timing Score:\s*(\d+)\s*\(Setup:\s*(\d+), Hold:\s*(\d+), Component Switching Limit:\s*(\d+)\)', par)
    traces = re.findall(r'Timing errors:\s*(\d+)\s+Score:\s*(\d+)\s+\(Setup/Max:\s*(\d+), Hold:\s*(\d+)\)', twr)
    need(len(scores) == len(traces) == 1 and 'All signals are completely routed.' in par, 'Incomplete or ambiguous implementation report')
    values = []
    for line in twr.splitlines():
        if not line.lstrip().startswith('Slack'):
            continue
        match = re.match(r'\s*Slack(?:\s+\(([^)]*)\))?:\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))ns\b', line)
        need(match is not None, 'Unknown actual slack record')
        values.append((match.group(1) or 'component', float(match.group(2))))
    need(values and any(kind == 'setup path' for kind, _ in values) and any(kind == 'hold path' for kind, _ in values), 'Missing setup/hold detail')
    score, setup, hold, component = map(int, scores[0])
    errors, trace_score, trace_setup, trace_hold = map(int, traces[0])
    return dict(parScore=score, parSetupScore=setup, parHoldScore=hold, componentSwitchingScore=component,
                traceErrors=errors, traceScore=trace_score, traceSetupScore=trace_setup, traceHoldScore=trace_hold,
                worstDisplayedSetupSlackNs=min(value for kind, value in values if kind == 'setup path'),
                worstDisplayedHoldSlackNs=min(value for kind, value in values if kind == 'hold path'),
                worstDisplayedOtherSlackNs=min((value for kind, value in values if kind not in ('setup path','hold path')), default=0.0),
                minimumDisplayedSlackNs=min(value for _, value in values),
                displayedNegativePaths=sum(value < 0 for _, value in values), displayedSlackRecords=len(values))

def progress(baseline, candidate):
    # Keep a better result only when the scored setup measures agree and no
    # hold/component regression is introduced. Remaining failures stay failures.
    nonregression = (candidate['traceErrors'] <= baseline['traceErrors']
                     and candidate['parScore'] <= baseline['parScore']
                     and candidate['worstDisplayedSetupSlackNs'] >= baseline['worstDisplayedSetupSlackNs']
                     and candidate['parHoldScore'] == candidate['traceHoldScore'] == candidate['componentSwitchingScore'] == 0
                     and candidate['worstDisplayedHoldSlackNs'] >= 0
                     and candidate['worstDisplayedOtherSlackNs'] >= 0)
    better = (candidate['traceErrors'] < baseline['traceErrors']
              or candidate['parScore'] < baseline['parScore']
              or candidate['worstDisplayedSetupSlackNs'] > baseline['worstDisplayedSetupSlackNs'])
    return bool(nonregression and better)

def analysis_controls(output):
    base = dict(traceErrors=13, parScore=1503, worstDisplayedSetupSlackNs=-0.206,
                parHoldScore=0, traceHoldScore=0, componentSwitchingScore=0, worstDisplayedHoldSlackNs=0.798, worstDisplayedOtherSlackNs=5.651)
    cases = [('unchanged is not improvement', {}, False),
             ('unscored plain negative slack rejects', dict(worstDisplayedOtherSlackNs=-0.001), False),
             ('fewer failures while still failing', dict(traceErrors=12), True),
             ('less negative slack while still failing', dict(worstDisplayedSetupSlackNs=-0.205), True),
             ('lower total score while still failing', dict(parScore=1502), True),
             ('worse slack rejects lower count', dict(traceErrors=9, worstDisplayedSetupSlackNs=-0.680), False),
             ('worse score rejects lower count', dict(traceErrors=9, parScore=1740), False),
             ('more failures reject better slack', dict(traceErrors=14, worstDisplayedSetupSlackNs=-0.100), False),
             ('hold errors reject', dict(traceErrors=12, traceHoldScore=1), False),
             ('unscored negative hold rejects', dict(traceErrors=12, worstDisplayedHoldSlackNs=-0.001), False),
             ('component errors reject', dict(traceErrors=12, componentSwitchingScore=1), False),
             ('current failed rewrite rejects', dict(traceErrors=173, parScore=50505, worstDisplayedSetupSlackNs=-1.324), False),
             ('seconds reset mapping regression rejects', dict(traceErrors=43, parScore=9812, worstDisplayedSetupSlackNs=-0.650), False),
             ('DR late selection regression rejects', dict(traceErrors=193, parScore=147633, worstDisplayedSetupSlackNs=-2.527), False)]
    rows = []
    for name, change, expected in cases:
        candidate = {**base, **change}; result = progress(base, candidate)
        rows.append(dict(name=name, expected=expected, result=result, passed=result == expected))
    save(output, dict(controls=rows, passed=all(row['passed'] for row in rows)))
    need(all(row['passed'] for row in rows), 'Timing-progress controls failed')
    print('Passed fourteen incremental-adoption controls, including remaining-failure positives')

def analyze(report, baseline_dir):
    baseline_paths = {}
    for name, expected in [('main.twr', 'cbdfa669beca53cd215d6e81f9759d5053fc8c2746f94fdc43a8f469605973cf'),
                           ('main.par', '4e44e96e979c704cdf205f552be45cdf6e4fe9f0008b51ab351bb9d731494012')]:
        paths = list(baseline_dir.rglob(name)); need(len(paths) == 1, 'Missing/duplicate original production report')
        need(sha(paths[0].read_bytes()) == expected, 'Original production report identity changed')
        baseline_paths[name] = paths[0]
    baseline = timing({key: baseline_paths['main.' + key].read_text() for key in ('par', 'twr')})
    native = report / 'native-reports'
    text = {key: (native / name).read_text(encoding='utf-8') for key, name in
            [('par', 'main.par'), ('twr', 'main.twr'), ('pcf', 'main.pcf'), ('mrp', 'main_map.mrp')]}
    candidate = timing(text)
    need(len(re.findall(r'^par -w -ol high -xe c -t 68 main_map\.ncd main\.ncd main\.pcf\s*$', text['par'], re.M)) == 1, 'Original PAR invocation changed')
    need(len(re.findall(r'/trce -v 10 -n 10 -u 10\s+-fastpaths main\.ncd main\.pcf -o main\.twr', text['twr'])) == 1, 'Original TRACE invocation changed')
    expected_map = 'map -p xc3s400-4pq208 -timing -logic_opt on -ol high -xe n -t 68 -register_duplication on -cm area -detail -ir off -ignore_keep_hierarchy -pr b -bp -power off -o main_map.ncd main.ngd main.pcf'
    command = re.search(r'Command Line\s*:\s*(.*?)\s*Target Device', text['mrp'], re.S)
    need(command is not None and ' '.join(command.group(1).split()) == expected_map, 'Original MAP invocation changed')
    need(re.findall(r'^SYSTEM_JITTER\s*=\s*([^;\r\n]+);', text['pcf'], re.M) == ['480 ps'], 'Original jitter changed')
    periods = re.findall(r'(TS_\w+) = PERIOD TIMEGRP "([^"]+)" ([0-9.]+) MHz HIGH 50%;', text['pcf'])
    expected_periods = {('TS_CLKIN','CLKIN','24.01'),('TS_SPI_SCK','SPI_SCK','48.1'),('TS_SNES_SYSCLK','SNES_SYSCLK','21.5'),('TS_CLK21','CLK21','96.04')}
    need(len(periods) == 4 and set(periods) == expected_periods, 'Original periods changed')
    need(set(re.findall(r'^(TS_\w+)\s*=', text['pcf'], re.M)) == {x[0] for x in expected_periods}, 'Extra timing specification')
    need((report / 'integrity-verified.txt').read_text().strip() == 'Full source/index/IP immutability verified', 'Input integrity not established')
    finished, = json.loads((report / 'native-container-finished.json').read_text())
    native_exit = int((report / 'native-exit.txt').read_text())
    need(finished['State']['ExitCode'] == native_exit and not finished['State']['OOMKilled'], 'Native exit or OOM mismatch')
    log = (report / 'native-build.log').read_text()
    if native_exit != 0:
        need(native_exit == 2 and 'make[1]: *** [../common.mk:198: main.ncd] Error 55' in log,
             'Actual compilation/native error is not the original strict timing gate')
        need(candidate['traceErrors'] > 0 or candidate['parScore'] > 0, 'Timing-gate failure without reported timing violations')
    physical = json.loads((report / 'physical' / 'stack-address-physical-index.json').read_text())
    need(not physical['missingStackWordBits'] and not physical['extraStackWordBits'], 'Incomplete mapped176-bit observations')
    bindings = physical['decoderBindings']
    need(len(bindings) == 16 and {b['bit'] for b in bindings} == set(range(16)), 'Missing sixteen captured address bits')
    need(all(b['suffix'] == '' and b['positiveClock'] and b['init0'] and b['clockNets'] == ['CLK2'] for b in bindings), 'Captured address FF contract changed')
    syr = (native / 'main.syr').read_text(encoding='utf-8')
    pattern = r'Set property "REGISTER_BALANCING = no" for unit <dspx_stack_restore_address_decoder(?:_[^>]*)?>\.'
    need(re.search(pattern, syr, re.I) is not None, 'Decoder module retiming control not recognized')
    need(not re.search(r'Register\(s\) snes_dspx/(?:stack_restore_addr/word|stack_addr_word_q)[^\n]*balanced into', syr), 'Address bits still retimed')
    passed = (native_exit == 0 and candidate['parScore'] == candidate['traceErrors'] == 0
              and candidate['minimumDisplayedSlackNs'] >= 0)
    result = dict(baselineRun=42507318034, baseline=baseline, candidate=candidate,
                  reportedTimingPassed=passed, measuredImprovement=progress(baseline, candidate),
                  nativeBuildExit=native_exit, nativeBuildSucceeded=native_exit == 0,
                  originalTimingGateFailure=native_exit == 2, constraintsAndOptionsUnchanged=True,
                  addressOnlyCaptureStage=True, mappedDecoderBindings=bindings,
                  mappedStackBindings=physical['stackBindings'],
                  unconstrainedIoSignoff=False, hardwareQualified=False,
                  limits='Remaining violations are not passes. Improvement permits source adoption only after evidence review; no whole mapped/electrical qualification.')
    save(report / 'timing-progress-result.json', result)
    print(json.dumps(result, indent=2))

def main():
    if len(sys.argv) == 3 and sys.argv[1] == 'prepare':
        prepare(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == 'prove':
        prove(Path(sys.argv[2]))
    elif len(sys.argv) == 4 and sys.argv[1] == 'collect':
        collect(Path(sys.argv[2]), Path(sys.argv[3]))
    elif len(sys.argv) == 3 and sys.argv[1] == 'analysis-controls':
        analysis_controls(Path(sys.argv[2]))
    elif len(sys.argv) == 3 and sys.argv[1] == 'collect-controls':
        collect_controls(Path(sys.argv[2]))
    elif len(sys.argv) == 4 and sys.argv[1] == 'analyze':
        analyze(Path(sys.argv[2]), Path(sys.argv[3]))
    else:
        raise SystemExit('Usage: prepare OUT | prove OUT | collect XDL OUT | collect-controls OUT | analysis-controls OUT | analyze REPORT BASELINE')


if __name__ == '__main__':
    main()
