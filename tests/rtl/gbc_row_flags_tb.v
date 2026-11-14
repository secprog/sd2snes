`timescale 1ns/1ps
module gbc_row_flags_tb;
  reg CLK=0, RST=1, OFF=0, THAW=0, FREEZE=0, CLID=0;
  reg [17:0] DONE=0;
  reg [4:0] THAW_ROW=0, FREEZE_ROW=0;
  wire [17:0] frozen, pending, clids;
  reg [17:0] old_frozen, old_pending, old_clids;
  integer mode,a,b,checks=0,seed=32'h1ab79c5;
  c6_row_flags dut(.CLK(CLK),.RST(RST),.OFF(OFF),.THAW(THAW),.FREEZE(FREEZE),
    .CLID(CLID),.DONE(DONE),.THAW_ROW(THAW_ROW),.FREEZE_ROW(FREEZE_ROW),
    .FROZEN(frozen),.PENDING(pending),.ROW_CLID(clids));
  // Original c6_fb.v assignments, including the overlapping whole-vector
  // and indexed assignments whose ordering must survive the implementation.
  always @(posedge CLK) begin
    if(RST) begin old_frozen<=0; old_pending<=0; old_clids<=0; end
    else begin
      if(OFF) begin old_frozen<=0; old_pending<=0; end
      if(|DONE) old_pending<=old_pending|DONE;
      if(THAW) begin
        old_frozen[THAW_ROW]<=0;
        old_pending[THAW_ROW]<=0;
        old_clids[THAW_ROW]<=CLID;
      end
      if(FREEZE) old_frozen[FREEZE_ROW]<=1;
    end
  end
  task tick;
    begin
      #2; CLK=1; #1;
      if({frozen,pending,clids} !== {old_frozen,old_pending,old_clids})
        $fatal(1,"C6 row priority mismatch test=%0d mode=%0d thaw=%0d freeze=%0d",
               checks,mode,THAW_ROW,FREEZE_ROW);
      checks=checks+1; CLK=0;
    end
  endtask
  initial begin
    tick;
    for(mode=0;mode<16;mode=mode+1)
      for(a=0;a<18;a=a+1)
        for(b=0;b<18;b=b+1) begin
          // Seed unrelated state before exercising each combination of
          // simultaneous events, including off+done and thaw+freeze.
          RST=0; OFF=0; THAW=1; FREEZE=1; CLID=1;
          DONE=18'h3ffff; THAW_ROW=(a+7)%18; FREEZE_ROW=(b+9)%18; tick;
          {RST,OFF,THAW,FREEZE}=mode; THAW_ROW=a; FREEZE_ROW=b;
          CLID=$random(seed); DONE=$random(seed);
          if((a+b)%3==0) DONE=0;
          tick;
        end
    $display("PASS: C6 row-state priorities match original on %0d simultaneous-event checks",checks);
    $finish;
  end
endmodule
