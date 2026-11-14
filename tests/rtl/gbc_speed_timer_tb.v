`timescale 1ns/1ps
module gbc_speed_timer_tb;
  reg CLK=0,reset=1,bus_edge=0,load=0,new_op=0,cb=0;
  reg [23:0] op=0;
  reg [7:0] ie=0,flags=0;
  wire [23:0] actual,reference;
  wire parked,reference_parked;
  integer checks=0,i,j,pass,seed=32'h53575044,until_irq;
  gbc_speed_actual dut(.CLK(CLK),.cpu_ireset_r(reset),.CLK_BUS_EDGE(bus_edge),
    .IFD_stop_switch(load),.IFD_EXE_new(new_op),.IFD_EXE_cb(cb),.IFD_EXE_op(op),
    .REG_IE_r(ie),.REG_IF_r(flags),.observable(actual),.parked(parked));
  gbc_speed_reference ref_dut(.CLK(CLK),.cpu_ireset_r(reset),.CLK_BUS_EDGE(bus_edge),
    .IFD_stop_switch(load),.IFD_EXE_new(new_op),.IFD_EXE_cb(cb),.IFD_EXE_op(op),
    .REG_IE_r(ie),.REG_IF_r(flags),.observable(reference),.parked(reference_parked));
  task tick;
    begin
      #2; CLK=1; #1;
      if(actual !== reference || parked !== reference_parked)
        $fatal(1,"speed-switch mismatch clock=%0d actual=%h reference=%h",checks,actual,reference);
      CLK=0; checks=checks+1;
    end
  endtask
  initial begin
    tick; reset=0;
    // Finish in both speed directions, with intervening clocks on which the
    // bus is stopped. Check the exact boundary, not merely eventual expiry.
    for(pass=0;pass<4;pass=pass+1) begin
      load=1; bus_edge=1; tick; load=0;
      if(!parked) $fatal(1,"switch failed to park");
      for(i=1;i<=32768;i=i+1) begin
        bus_edge=0;
        for(j=0;j<(i%4);j=j+1) tick;
        bus_edge=1; tick;
        if(parked !== (i<32768)) $fatal(1,"wrong park length edge=%0d",i);
      end
      repeat(8) tick;
      new_op=1; op=0; tick; new_op=0;
    end
    // IRQ aborts at early and expiry-adjacent edges, followed by a new load.
    for(pass=0;pass<10;pass=pass+1) begin
      until_irq=(pass<5) ? pass : 32763+(pass-5);
      load=1; ie=0; flags=0; tick; load=0;
      repeat(until_irq) tick;
      ie=8'h01; flags=8'h01; bus_edge=pass[0]; tick;
      if(parked) $fatal(1,"IRQ failed to release park");
      bus_edge=1; repeat(4) tick;
      ie=0; flags=0;
    end
    // Arbitrary reset/load/IRQ coincidences and STOP handoffs. Control inputs
    // may change every clock, a stronger condition than the GB bus cadence.
    for(i=0;i<100000;i=i+1) begin
      reset=(i%127)==0; load=(i%97)==0; bus_edge=$random(seed);
      new_op=$random(seed); op=$random(seed); cb=$random(seed);
      ie=$random(seed); flags=(i%11) ? 0 : $random(seed); tick;
    end
    $display("PASS: speed-switch timer, IRQ wake, reload and reset match on %0d clocks",checks);
    $finish;
  end
endmodule
