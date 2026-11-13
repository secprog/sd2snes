`timescale 1ns/1ps
// Small memories belong in LUT RAM on Mk.II. Keeping the 128-byte HRAM and
// 256-byte OAM in separate RAMB16s would waste nearly two whole blocks.
// Port B is read-only in this build: SGB_MCU_ACCESS is disabled, while the
// bridge still reads OAM snapshots through it. Both clocks are the same CLK.
module gbc_small_ram #(parameter ABITS=8)(
  input clka, wea,
  input [ABITS-1:0] addra,
  input [7:0] dina,
  output reg [7:0] douta,
  input clkb, web,
  input [ABITS-1:0] addrb,
  input [7:0] dinb,
  output reg [7:0] doutb
);
  (* ram_style = "distributed" *) reg [7:0] ram[0:(1<<ABITS)-1];
  integer i;
  initial for(i=0;i<(1<<ABITS);i=i+1)ram[i]=0;
  always @(posedge clka) begin
    if(wea)ram[addra]<=dina;
    douta<=ram[addra];
    doutb<=ram[addrb];
  end
  // synthesis translate_off
  always @(posedge clka) if(web) $fatal(1,"Mk.II LUT RAM port B is read-only");
  // synthesis translate_on
endmodule
