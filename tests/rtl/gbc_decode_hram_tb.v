`timescale 1ns/1ps
module gbc_decode_hram_tb;
  reg CLK=0, WE=0, HRAM_SEL=1, CRAM_WE=0;
  reg [7:0] opcode=0, data=0;
  reg [7:0] cram_data=0;
  reg [6:0] addr=0, cram_a=0, cram_b=0;
  wire [15:0] decode;
  wire [7:0] q, cram_qa, cram_qb;
  reg [15:0] reference_decode[0:255];
  reg [7:0] reference_hram[0:127];
  reg [7:0] reference_cram[0:127];
  reg [7:0] old_byte, old_b;
  reg [15:0] held_decode;
  reg [7:0] held_q, held_b;
  integer i,j,checks=0,seed=32'h53b9e81;
  gbc_cpu_memory dut(.CLK(CLK),.DEC_ADDR(opcode),.DEC_Q(decode),
    .HRAM_SEL(HRAM_SEL),.HRAM_WE(WE),.HRAM_ADDR(addr),.HRAM_DATA(data),.HRAM_Q(q),
    .CRAM_WE(CRAM_WE),.CRAM_ADDR_A(cram_a),.CRAM_DATA(cram_data),.CRAM_Q_A(cram_qa),
    .CRAM_ADDR_B(cram_b),.CRAM_Q_B(cram_qb));
  task tick;
    begin
      old_byte=HRAM_SEL ? reference_hram[addr] : reference_cram[cram_a];
      old_b=reference_cram[cram_b];
      held_decode=decode; held_q=q; held_b=cram_qb;
      #1;
      if(decode !== held_decode || q !== held_q || cram_qb !== held_b)
        $fatal(1,"memory read bypassed its clock");
      #2; CLK=1; #1;
      if(decode !== reference_decode[opcode] || q !== old_byte || cram_qa !== old_byte)
        $fatal(1,"decoder/HRAM mismatch opcode=%h decode=%h expected=%h addr=%h q=%h old=%h",
               opcode,decode,reference_decode[opcode],addr,q,old_byte);
      if(cram_qb !== old_b)
        $fatal(1,"palette port B mismatch addr=%h actual=%h expected=%h",cram_b,cram_qb,old_b);
      if(HRAM_SEL && WE) reference_hram[addr]=data;
      if(!HRAM_SEL && CRAM_WE) reference_cram[cram_a]=cram_data;
      checks=checks+1;
      CLK=0;
    end
  endtask
  initial begin
    // This file comes directly from the original SGB CoreGen COE in the
    // hosted runner, not from the new module's initialization statements.
    $readmemh("decode_reference.hex",reference_decode);
    for(i=0;i<128;i=i+1) begin reference_hram[i]=0; reference_cram[i]=0; end
    // Retain the original exhaustive opcode/HRAM address combinations.
    for(i=0;i<32768;i=i+1) begin
      opcode=i%256; addr=i/256; WE=$random(seed); data=$random(seed);
      tick;
    end
    WE=0;
    for(i=0;i<256;i=i+1) begin opcode=i; addr=i%128; tick; end
    // All independent CPU and palette-engine addresses, with both CPU banks
    // alternating every clock. Equal indices exercise read/write collisions.
    for(i=0;i<128;i=i+1) for(j=0;j<128;j=j+1) begin
      opcode=$random(seed); addr=i; cram_a=i; cram_b=j;
      HRAM_SEL=0; WE=0; CRAM_WE=1; cram_data=$random(seed); tick;
      HRAM_SEL=1; WE=1; CRAM_WE=0; data=$random(seed); tick;
      HRAM_SEL=0; WE=0; cram_b=i; tick;
      HRAM_SEL=1; tick;
    end
    for(i=0;i<20000;i=i+1) begin
      opcode=$random(seed); addr=$random(seed); cram_a=$random(seed);
      cram_b=(i%3) ? $random(seed) : cram_a;
      HRAM_SEL=$random(seed); WE=HRAM_SEL & $random(seed);
      CRAM_WE=!HRAM_SEL & $random(seed); data=$random(seed); cram_data=$random(seed);
      tick;
    end
    $display("PASS: canonical decoder, shared HRAM/palette ports and READ_FIRST collisions (%0d clocks)",checks);
    $finish;
  end
endmodule
