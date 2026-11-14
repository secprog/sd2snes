`timescale 1ns/1ps
module gbc_command_tb;
  reg CLK2=0;
  reg [23:0] SNES_ADDR_IN=0;
  wire [23:0] ADDRESS;
  wire [8:0] MATCH,VIEW_MATCH;
  reg [8:0] original,original_view;
  reg [23:0] address_history[0:6];
  wire [23:0] original_address = address_history[6] & address_history[5];
  integer stage;
  always @(posedge CLK2) begin
    address_history[0] <= SNES_ADDR_IN;
    for(stage=1;stage<7;stage=stage+1)
      address_history[stage] <= address_history[stage-1];
  end
  integer i,j,b,cycles=0,seed=32'h128c73;
  gbc_command_actual dut(.*);
  task tick;
    begin
      #2; CLK2=1; #1;
      if(cycles>=8 && ADDRESS !== original_address)
        $fatal(1,"registered deglitch changed cycle=%0d got=%h old=%h",
               cycles,ADDRESS,original_address);
      for(j=0;j<9;j=j+1) original[j]=(ADDRESS == 24'hef0000+j);
      original_view=0;
      case(ADDRESS[23:16])
        8'he0: begin
          original_view[0]=ADDRESS[15:0]<16'h3000;
          original_view[1]=ADDRESS[15:0]>=16'h4000 && ADDRESS[15:0]<16'h8000;
        end
        8'he1: original_view[2]=ADDRESS[15:0]<16'h2000;
        8'he2: begin
          original_view[3]=ADDRESS[15:0]<16'h0200;
          original_view[4]=ADDRESS[15:0]>=16'h0200 && ADDRESS[15:0]<16'h0300;
          original_view[6]=ADDRESS[15:0]>=16'h0400 && ADDRESS[15:0]<16'h0c00;
          original_view[8]=ADDRESS[15:0]>=16'h0240 && ADDRESS[15:0]<16'h0258;
        end
        8'he3: original_view[5]=ADDRESS[15:0]<16'h0200;
        8'he4: original_view[7]=1;
      endcase
      if(cycles>=8 && MATCH !== original)
        $fatal(1,"command alignment changed cycle=%0d address=%h got=%h old=%h",
               cycles,ADDRESS,MATCH,original);
      if(cycles>=8 && VIEW_MATCH !== original_view)
        $fatal(1,"view alignment changed cycle=%0d address=%h got=%h old=%h",
               cycles,ADDRESS,VIEW_MATCH,original_view);
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
    // Every byte in all five views and their adjacent reserved banks.
    for(b=8'hdf;b<=8'he5;b=b+1)
      for(i=0;i<65536;i=i+1) begin SNES_ADDR_IN={b[7:0],i[15:0]}; tick; end
    // Deliberately unstable/glitching addresses also have exactly the same
    // bitwise-AND deglitch behavior as the original combinational decoder.
    for(i=0;i<20000;i=i+1) begin SNES_ADDR_IN=$random(seed); tick; end
    repeat(10) tick;
    $display("PASS: retimed command and view decode match original on %0d address clocks",cycles);
    $finish;
  end
endmodule
