`timescale 1ns/1ps
module gbc_decode_hram_tb;
  reg CLK=0, WE=0;
  reg [7:0] opcode=0, data=0;
  reg [6:0] addr=0;
  wire [15:0] decode;
  wire [7:0] q;
  reg [15:0] reference_decode[0:255];
  reg [7:0] reference_hram[0:127];
  reg [7:0] old_byte;
  reg [15:0] held_decode;
  reg [7:0] held_q;
  integer i, checks=0, seed=32'h53b9e81;
  gbc_decode_hram dut(.CLK(CLK),.DEC_ADDR(opcode),.DEC_Q(decode),
    .HRAM_WE(WE),.HRAM_ADDR(addr),.HRAM_DATA(data),.HRAM_Q(q));
  task tick;
    begin
      old_byte=reference_hram[addr];
      #2; CLK=1; #1;
      if(decode !== reference_decode[opcode] || q !== old_byte)
        $fatal(1,"decoder/HRAM mismatch opcode=%h decode=%h expected=%h addr=%h q=%h old=%h",
               opcode,decode,reference_decode[opcode],addr,q,old_byte);
      if(WE) reference_hram[addr]=data;
      checks=checks+1;
      CLK=0;
    end
  endtask
  initial begin
    // This file comes directly from the original SGB CoreGen COE in the
    // hosted runner, not from the new module's initialization statements.
    $readmemh("decode_reference.hex",reference_decode);
    for(i=0;i<128;i=i+1) reference_hram[i]=0;
    for(i=0;i<32768;i=i+1) begin
      opcode=i%256; addr=i/256; WE=$random(seed); data=$random(seed);
      held_decode=decode; held_q=q; #1;
      if(decode !== held_decode || q !== held_q) $fatal(1,"read bypassed its clock");
      tick;
    end
    WE=0;
    for(i=0;i<256;i=i+1) begin opcode=i; addr=i%128; tick; end
    $display("PASS: all decoder entries and HRAM READ_FIRST, independent addresses (%0d cycles)",checks);
    $finish;
  end
endmodule
