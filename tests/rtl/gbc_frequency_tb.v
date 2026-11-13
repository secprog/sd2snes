`timescale 1ns/1ps
module gbc_frequency_tb;
  reg clk=0, sysclk=0;
  wire [31:0] actual, expected;
  integer i,j,seed=32'h53e019a,checks=0;
  reg [31:0] start_count, start_value;
  clk_test dut(.clk(clk),.sysclk(sysclk),.snes_sysclk_freq(actual));
  clk_test_ref reference(.clk(clk),.sysclk(sysclk),.snes_sysclk_freq(expected));
  task tick;
    begin
      #2; clk=1; #1;
      if(actual !== expected || dut.sysclk_counter !== reference.sysclk_counter
         || dut.sysclk_value !== reference.sysclk_value)
        $fatal(1,"frequency counter mismatch at %0d: result %h/%h",checks,actual,expected);
      checks=checks+1; clk=0;
    end
  endtask
  initial begin
    #1;
    if(actual !== 32'hffffffff || expected !== 32'hffffffff)
      $fatal(1,"initial unknown-frequency marker changed");
    // Enter legal states close to the end of the 96M-clock interval, rather
    // than spending a simulation minute repeating an ordinary increment.
    // This also checks carry propagation through every retained counter bit.
    for(i=0;i<31;i=i+1) begin
      start_count=i<27 ? (32'd1<<i)-1 : 96000000-(i-27);
      start_value=start_count/2;
      dut.sysclk_counter=start_count; reference.sysclk_counter=start_count;
      dut.sysclk_value=start_value; reference.sysclk_value=start_value;
      for(j=0;j<16;j=j+1) begin sysclk=~sysclk; tick; end
    end
    // Maximum event counts around publication, then continuously randomized
    // synchronizer traffic. The original 32-bit implementation is the oracle.
    dut.sysclk_counter=95999990; reference.sysclk_counter=95999990;
    dut.sysclk_value=47999995; reference.sysclk_value=47999995;
    repeat(32) begin sysclk=~sysclk; tick; end
    for(i=0;i<100000;i=i+1) begin sysclk=$random(seed); tick; end
    $display("PASS: bounded frequency measurement matches original on %0d clocks",checks);
    $finish;
  end
endmodule
