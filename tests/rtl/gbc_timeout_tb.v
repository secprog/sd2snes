`timescale 1ns/1ps
module gbc_timeout_tb;
  reg CLK2=0;
  always #5 CLK2=~CLK2;
  reg [7:0] SNES_CPU_CLKr=0;
  wire dead,reset_strobe;
  gbc_timeout_actual dut(.*);
  reg [17:0] count=0;
  reg old_dead=1,old_strobe;
  integer i,j,run,seed=32'h479c153a,checks=0;
  always @(posedge CLK2) begin
    count <= SNES_CPU_CLKr[1] ? 18'd0 : count+1'b1;
    old_strobe<=0;
    if(SNES_CPU_CLKr[1]) begin
      old_dead<=0;
      if(old_dead) old_strobe<=1;
    end else if(count>84000) old_dead<=1;
    #1;
    if({dead,reset_strobe} !== {old_dead,old_strobe})
      $fatal(1,"SNES timeout mismatch at clock %0d count=%0d",checks,count);
    checks=checks+1;
  end
  task interval(input integer low_clocks);
    begin
      @(negedge CLK2); SNES_CPU_CLKr=2;
      @(negedge CLK2); SNES_CPU_CLKr=0;
      repeat(low_clocks) @(negedge CLK2);
    end
  endtask
  initial begin
    if(dut.SNES_DEAD_TIMEOUT!=84000)
      $fatal(1,"Recompute the LFSR terminal when the timeout changes");
    // Startup, exact threshold boundaries, pulses, and several wraps of both
    // counters. The original sticky result must survive every later wrap.
    repeat(270000) @(negedge CLK2);
    for(i=83996;i<=84005;i=i+1) interval(i);
    interval(600000);
    for(i=0;i<256;i=i+1) interval(i);
    for(i=0;i<50;i=i+1) begin
      run=$unsigned($random(seed))%180000;
      interval(run);
    end
    interval(0);
    #2;
    $display("PASS: SNES timeout and reset strobe match on %0d clocks",checks);
    $finish;
  end
endmodule
