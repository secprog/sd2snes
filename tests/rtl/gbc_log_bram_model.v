`timescale 1ns/1ps
// Fast RTL-test model of the restricted port shape used by gbc_log_ram.
// The native ISE job runs the same test against Xilinx's installed model.
module RAMB16_S9_S36 #(parameter WRITE_MODE_A="READ_FIRST", WRITE_MODE_B="READ_FIRST")(
  input CLKA,ENA,SSRA,WEA, input [10:0] ADDRA, input [7:0] DIA, input DIPA,
  output reg [7:0] DOA=0, output DOPA,
  input CLKB,ENB,SSRB,WEB, input [8:0] ADDRB, input [31:0] DIB, input [3:0] DIPB,
  output reg [31:0] DOB=0, output [3:0] DOPB);
  reg [31:0] memory[0:511];
  integer i;
  initial begin
    if(WRITE_MODE_A!="READ_FIRST" || WRITE_MODE_B!="READ_FIRST")
      $fatal(1,"log RAM requires READ_FIRST ports");
    for(i=0;i<512;i=i+1) memory[i]=0;
  end
  assign DOPA=0;
  assign DOPB=0;
  always @(posedge CLKA) if(ENA) begin
    if(WEA) $fatal(1,"log byte port must be read-only");
    DOA<=SSRA ? 8'd0 : (memory[ADDRA/4] >> (8*(ADDRA%4)));
  end
  always @(posedge CLKB) if(ENB) begin
    DOB<=SSRB ? 32'd0 : memory[ADDRB];
    if(WEB) memory[ADDRB]<=DIB;
  end
endmodule
