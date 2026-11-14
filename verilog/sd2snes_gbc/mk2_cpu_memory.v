`timescale 1ns/1ps
// One block RAM holds the 128 palette bytes and 128 HRAM bytes. The CPU
// accesses them through port A; the pixel/snapshot engine retains port B.
// HRAM_SEL is driven by the real MCT state, whose mutual exclusion and read
// windows are proved in check-gbc-smallmem.py. Reads remain one clock late,
// including READ_FIRST when either port addresses the byte being written.
// The decoder uses logic instead of occupying the second RAM port. Every
// opcode is checked against the original SGB CoreGen COE in hosted tests.
module gbc_cpu_memory(input CLK,
  input [7:0] DEC_ADDR, output reg [15:0] DEC_Q,
  input HRAM_SEL, HRAM_WE, input [6:0] HRAM_ADDR, input [7:0] HRAM_DATA,
  output [7:0] HRAM_Q,
  input CRAM_WE, input [6:0] CRAM_ADDR_A, input [7:0] CRAM_DATA,
  output [7:0] CRAM_Q_A,
  input [6:0] CRAM_ADDR_B, output reg [7:0] CRAM_Q_B);
  (* ram_style = "block" *) reg [7:0] bytes [0:255];
  wire [7:0] cpu_addr = HRAM_SEL ? {1'b1,HRAM_ADDR} : {1'b0,CRAM_ADDR_A};
  wire [7:0] cpu_data = HRAM_SEL ? HRAM_DATA : CRAM_DATA;
  wire cpu_we = HRAM_SEL ? HRAM_WE : CRAM_WE;
  reg [7:0] cpu_q;
  integer init_i;
  initial begin
    // HRAM retains its zero initialization. Palette power-up data is not
    // specified by the GB interface; the boot ROM programs its contents.
    for(init_i=0;init_i<256;init_i=init_i+1) bytes[init_i]=0;
  end
  // The regular MOV, ALU, INC/DEC and register-pair families share their
  // operand fields. Keep the irregular control opcodes in an explicit table.
  // This is the same 256-entry decoder, including every illegal opcode.
  function [15:0] decode_opcode;
    input [7:0] op;
    reg [3:0] pair16, pairmem, dst8, src8;
    reg dstmem, srcmem;
    begin
      case(op[5:4])
        0: pair16=4'h4; // BC
        1: pair16=4'h5; // DE
        2: pair16=4'he; // HL
        3: pair16=4'h6; // SP
      endcase
      pairmem=op[5] ? 4'he : {3'b010,op[4]};
      dst8={1'b1,op[5:3]}; src8={1'b1,op[2:0]};
      dstmem=op[5:3]==3'd6; srcmem=op[2:0]==3'd6;
      decode_opcode=16'h0000;
      case(op[7:6])
        2'b00: case(op[2:0])
          0: case(op[5:3])
            0,2: decode_opcode=16'h0000;
            1: decode_opcode=16'ha368;
            default: decode_opcode=16'h4126;
          endcase
          1: decode_opcode=op[3] ? {4'h0,4'he,pair16,4'h4}
                                          : {4'h8,pair16,4'h3,4'h1};
          2: decode_opcode=op[3] ? {4'h1,4'hf,pairmem,4'h9}
                                          : {4'h1,pairmem,4'hf,4'h8};
          3: decode_opcode={4'h0,pair16,pair16,3'b001,op[3]};
          4,5: decode_opcode={2'd0,dstmem,1'b0,dst8,dst8,dstmem,2'b01,op[0]};
          6: decode_opcode={2'd1,1'b0,dstmem,dst8,4'h2,(dstmem ? 4'h8 : 4'h1)};
          7: decode_opcode={4'h0,4'hf,4'hf,(op[5] ? 4'h4 : 4'h5)};
        endcase
        2'b01: if(!(dstmem && srcmem))
          decode_opcode={2'd0,1'b0,(dstmem|srcmem),dst8,src8,
                         (dstmem ? 4'h8 : srcmem ? 4'h9 : 4'h1)};
        2'b10: decode_opcode={2'd0,1'b0,srcmem,4'hf,src8,srcmem,3'b100};
        2'b11: case(op[2:0])
          6: decode_opcode=16'h4f24;
          7: decode_opcode=16'h061e;
          default: case(op)
            8'hc0,8'hc8,8'hc9,8'hd0,8'hd8,8'hd9: decode_opcode=16'h016f;
            8'hc1: decode_opcode=16'h2469;
            8'hc2,8'hc3,8'hca,8'hd2,8'hda: decode_opcode=16'h8136;
            8'hc4,8'hcc,8'hcd,8'hd4,8'hdc: decode_opcode=16'h861e;
            8'hc5: decode_opcode=16'h3648;
            8'hcb: decode_opcode=16'h4005;
            8'hd1: decode_opcode=16'h2569;
            8'hd5: decode_opcode=16'h3658;
            8'he0: decode_opcode=16'h52f8;
            8'he1: decode_opcode=16'h2e69;
            8'he2: decode_opcode=16'h19f8;
            8'he5: decode_opcode=16'h36e8;
            8'he8: decode_opcode=16'h4624;
            8'he9: decode_opcode=16'h01e6;
            8'hea: decode_opcode=16'h93f8;
            8'hf0: decode_opcode=16'h5f29;
            8'hf1: decode_opcode=16'h2769;
            8'hf2: decode_opcode=16'h1f99;
            8'hf5: decode_opcode=16'h3678;
            8'hf8: decode_opcode=16'h4e24;
            8'hf9: decode_opcode=16'h06e1;
            8'hfa: decode_opcode=16'h9f39;
            default: decode_opcode=16'h0000;
          endcase
        endcase
      endcase
    end
  endfunction
  always @(posedge CLK) begin
    DEC_Q <= decode_opcode(DEC_ADDR);
    if(cpu_we) bytes[cpu_addr] <= cpu_data;
    cpu_q <= bytes[cpu_addr];
    CRAM_Q_B <= bytes[{1'b0,CRAM_ADDR_B}];
  end
  assign HRAM_Q = cpu_q;
  assign CRAM_Q_A = cpu_q;
endmodule
