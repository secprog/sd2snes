`timescale 1ns/1ps
module gbc_command_tb;
  reg CLK2=0;
  reg [23:0] SNES_ADDR_IN=0;
  wire [23:0] ADDRESS;
  wire [8:0] MATCH;
  reg [8:0] original;
  integer i,j,cycles=0,seed=32'h128c73;
  gbc_command_actual dut(.*);
  task tick;
    begin
      #2; CLK2=1; #1;
      for(j=0;j<9;j=j+1) original[j]=(ADDRESS == 24'hef0000+j);
      if(cycles>=8 && MATCH !== original)
        $fatal(1,"command alignment changed cycle=%0d address=%h got=%h old=%h",
               cycles,ADDRESS,MATCH,original);
      CLK2=0; cycles=cycles+1;
    end
  endtask
  initial begin
    repeat(10) tick;
    // Every command/reserved low byte, then every high address word.
    for(i=0;i<256;i=i+1) begin
      SNES_ADDR_IN=24'hef0000+i; repeat(10) tick;
    end
    for(i=0;i<65536;i=i+1) begin
      SNES_ADDR_IN={i[15:0],8'd5}; tick;
    end
    // Deliberately unstable/glitching addresses also have exactly the same
    // bitwise-AND deglitch behavior as the original combinational decoder.
    for(i=0;i<20000;i=i+1) begin SNES_ADDR_IN=$random(seed); tick; end
    repeat(10) tick;
    $display("PASS: retimed command decode matches original on %0d address clocks",cycles);
    $finish;
  end
endmodule
