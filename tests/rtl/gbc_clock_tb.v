`timescale 1ns/1ps
module gbc_clock_tb;
  reg CLK=0, RST=1, exact_mode=0, sync_strobe=0, lcd_on=1, hold=0;
  reg [16:0] dots=0;
  wire ce1,ce2,bus_edge,locked,ref_ce1,ref_ce2,ref_bus,ref_locked;
  wire [15:0] err,ref_err;
  integer i,j,cycles=0,seed=32'h7123bac;
  gbc_clk dut(.CLK(CLK),.RST(RST),.exact_mode(exact_mode),.sync_strobe(sync_strobe),
    .frame_dot_ctr(dots),.lcd_on(lcd_on),.hold(hold),.ce1(ce1),.ce2(ce2),
    .bus_edge(bus_edge),.locked(locked),.sync_err_last(err));
  gbc_clk_ref reference(.CLK(CLK),.RST(RST),.exact_mode(exact_mode),.sync_strobe(sync_strobe),
    .frame_dot_ctr(dots),.lcd_on(lcd_on),.hold(hold),.ce1(ref_ce1),.ce2(ref_ce2),
    .bus_edge(ref_bus),.locked(ref_locked),.sync_err_last(ref_err));
  task tick;
    begin
      #2; CLK=1; #1;
      if({ce1,ce2,bus_edge,locked,err} !== {ref_ce1,ref_ce2,ref_bus,ref_locked}
         || dut.k2_r !== reference.k2_r || $signed(dut.ki_r) !== $signed(reference.ki_r))
        $fatal(1,"clock mismatch cycle=%0d dots=%0d rate=%0d reference=%0d",cycles,dots,dut.k2_r,reference.k2_r);
      cycles=cycles+1; CLK=0;
    end
  endtask
  task sample;
    begin
      sync_strobe=1; tick; sync_strobe=0;
      repeat(16) tick;
    end
  endtask
  initial begin
    tick; tick; RST=0;
    // Every possible 17-bit input, including samples beyond the valid frame
    // range, catches signed extension and wrap-boundary changes.
    for(i=0;i<131072;i=i+1) begin dots=i; hold=(i%37==0); sample; end
    // Drive both integrator clamps and lock acquisition/loss. These are
    // repeated samples of small phase errors, not only reset-state checks.
    hold=0;
    for(i=0;i<6;i=i+1) begin
      dots=i%2 ? 17'd11014 : 17'd12036;
      repeat(100) sample;
      dots=11525; repeat(20) sample;
      dots=46637; sample;
    end
    // Reset, Exact-mode transitions, LCD freeze/restart, dilation and
    // strobes arriving during an update retain cycle-for-cycle behavior.
    for(i=0;i<200000;i=i+1) begin
      dots=$random(seed); hold=$random(seed); sync_strobe=($random(seed)%7==0);
      if(i%31==0) lcd_on=$random(seed);
      if(i%1001==0) exact_mode=$random(seed);
      RST=(i%2003==0); tick;
    end
    $display("PASS: MkII genlock/rate widths match original on %0d clocks and every 17-bit phase",cycles);
    $finish;
  end
endmodule
