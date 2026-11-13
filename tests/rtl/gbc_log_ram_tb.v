`timescale 1ns / 1ps
module gbc_log_ram_tb;
  reg CLK=0, WE=0;
  always #5 CLK=~CLK;
  reg [10:0] WADDR=0, RADDR=0;
  reg [31:0] DATA=0;
  wire [31:0] Q;
  gbc_log_ram dut(.CLK(CLK), .WE(WE), .WADDR(WADDR),
                   .DATA(DATA), .RADDR(RADDR), .Q(Q));
  reg [31:0] reference [0:1535];
  reg [31:0] expected;
  integer i, seed=32'h75413409, checks=0;
  // Score the old single-array READ_FIRST behavior, including changing bank
  // on every cycle and simultaneous independent write/read transactions.
  task tick;
    begin
      expected=RADDR<1536 ? reference[RADDR] : 32'd0;
      @(posedge CLK);
      if (WE && WADDR<1536) reference[WADDR]=DATA;
      #1;
      if (Q !== expected) begin
        $display("log RAM mismatch addr=%h got=%h expected=%h",RADDR,Q,expected);
        $fatal(1);
      end
      checks=checks+1;
      @(negedge CLK);
    end
  endtask
  initial begin
    for(i=0;i<1536;i=i+1) reference[i]=0;
    @(negedge CLK);
    for(i=0;i<1536;i=i+1) begin
      WE=1; WADDR=i; RADDR=(i*733)%1536;
      DATA=32'h9e3779b9*i ^ (32'h10001<<(i%16));
      tick;
    end
    WE=0;
    for(i=0;i<1536;i=i+1) begin RADDR=i; tick; end
    for(i=0;i<12000;i=i+1) begin
      WE=$random(seed); WADDR=$unsigned($random(seed))%2048;
      RADDR=$unsigned($random(seed))%2048; DATA=$random(seed);
      // Exercise READ_FIRST at a same-address write explicitly.
      if(i%13==0) begin WE=1; RADDR=WADDR; end
      tick;
    end
    $display("PASS: three-bank log RAM matches one-cycle array in %0d accesses",checks);
    $finish;
  end
endmodule
