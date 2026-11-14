`timescale 1ns/1ps
module gbc_oam_positions_tb;
  reg CLK=0, CLEAR=1, WRITE=0, CONSUME=0;
  reg [3:0] WADDR=0,CADDR=0,RADDR=0;
  reg [7:0] DATA=0;
  reg [4:0] TILE=0;
  wire [7:0] Q;
  wire FOUND;
  wire [3:0] MATCH;
  reg [7:0] original[0:9];
  reg expected_found;
  reg [3:0] expected_match;
  integer i,j,k,checks=0,seed=32'h37a129b;
  gbc_oam_positions dut(.CLK(CLK),.CLEAR(CLEAR),.WRITE(WRITE),.CONSUME(CONSUME),
    .WADDR(WADDR),.CADDR(CADDR),.RADDR(RADDR),.DATA(DATA),.TILE(TILE),
    .Q(Q),.FOUND(FOUND),.MATCH(MATCH));
  task tick;
    begin
      #2; CLK=1;
      if(CLEAR) for(j=0;j<10;j=j+1) original[j]=8'hf0;
      if(WRITE && WADDR<10) original[WADDR]=DATA;
      if(CONSUME && CADDR<10) original[CADDR]=8'hf0;
      #1;
      for(k=0;k<32;k=k+1) begin
        TILE=k; RADDR=k%10; #1;
        expected_found=0; expected_match=15;
        // Descending overwrite expresses the original first-slot priority
        // independently of the implementation's ascending early-match loop.
        for(j=9;j>=0;j=j-1)
          if(original[j][7:3]==k) begin expected_found=1; expected_match=j; end
        if({FOUND,MATCH,Q} !== {expected_found,expected_match,original[RADDR]})
          $fatal(1,"sprite mismatch cycle=%0d tile=%0d slot=%0d found=%b/%b match=%h/%h data=%h/%h",
                 i,k,RADDR,FOUND,expected_found,MATCH,expected_match,Q,original[RADDR]);
        checks=checks+1;
      end
      CLK=0;
    end
  endtask
  initial begin
    tick; CLEAR=0;
    // Every entry shares a tile; consuming entries must expose the next one
    // in original OAM order, including the $f0 sentinel's tile 30 behavior.
    WRITE=1;
    for(i=0;i<10;i=i+1) begin WADDR=i; DATA=8'h58+i%8; tick; end
    WRITE=0; CONSUME=1;
    for(i=0;i<10;i=i+1) begin CADDR=i; tick; end
    for(i=0;i<10000;i=i+1) begin
      CLEAR=(i%29==0); WRITE=$random(seed); CONSUME=$random(seed);
      WADDR=$random(seed); CADDR=$random(seed); DATA=$random(seed); tick;
    end
    $display("PASS: sprite position storage and first-match lookup (%0d comparisons)",checks);
    $finish;
  end
endmodule
