`timescale 1ns/1ps
module gbc_starvation_tb;
  reg CLK=0,cpu_ireset_r=1,CLK_BUS_EDGE=0,mct_conflict_r=0;
  reg [7:0] mct_state_r=0;
  reg [2:0] mct_settle_r=0;
  reg [1:0] dma_cred_r=0;
  wire [15:0] STARVATION;
  reg [15:0] original=0,expected;
  reg late_access;
  integer i,checks=0,seed=32'h5704b22;
  gbc_starvation_actual dut(.*);
  task tick;
    begin
      #1;
      late_access=((mct_state_r[1] || mct_state_r[6] || mct_state_r[7]) && !mct_conflict_r)
                  || mct_settle_r!=0 || dma_cred_r!=0;
      if(cpu_ireset_r) original=0;
      else if(CLK_BUS_EDGE && late_access && original!=16'hffff) original=original+16'd1;
`ifdef MK2
      expected=original!=0;
`else
      expected=original;
`endif
      CLK=1; #1;
      if(STARVATION !== expected)
        $fatal(1,"starvation diagnostic mismatch got=%h expected=%h",STARVATION,expected);
      CLK=0; checks=checks+1;
    end
  endtask
  initial begin
    tick;
    // Every combination of controller state, conflict, settle, DMA credit,
    // clock enable and reset, including reset/event collisions.
    for(i=0;i<65536;i=i+1) begin
      {mct_state_r,mct_conflict_r,mct_settle_r,dma_cred_r,CLK_BUS_EDGE,cpu_ireset_r}=i;
      tick;
    end
    cpu_ireset_r=1; tick; cpu_ireset_r=0;
    CLK_BUS_EDGE=1; mct_state_r=8'h40; mct_conflict_r=0; mct_settle_r=0; dma_cred_r=0;
    // The original counter saturates. The Mk.II flag must never clear or wrap.
    for(i=0;i<70000;i=i+1) tick;
    CLK_BUS_EDGE=0;
    for(i=0;i<1000;i=i+1) tick;
    for(i=0;i<10000;i=i+1) begin
      {mct_state_r,mct_conflict_r,mct_settle_r,dma_cred_r,CLK_BUS_EDGE}=$random(seed);
      cpu_ireset_r=i%191==0; tick;
    end
    $display("PASS: starvation diagnostic preserves the original zero/nonzero failure and reset contract (%0d cycles)",checks);
    $finish;
  end
endmodule
