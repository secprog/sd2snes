`timescale 1ns/1ps
module dirty_pages_case #(parameter PAGES=8)(output reg DONE=0);
  reg CLK=0,RST=1,SWAP=0,ALL=0,SET=0;
  reg [2:0] WPAGE=0,BIT=0,RPAGE=0;
  wire [7:0] Q;
  reg [63:0] acc=0,pub=0,events;
  localparam [63:0] MASK=64'hffffffffffffffff >> (64-PAGES*8);
  integer i,j,k,mode,checks=0,seed=32'h31677a+PAGES;
  gbc_dirty_pages #(.PAGES(PAGES)) dut(.CLK(CLK),.RST(RST),.SWAP(SWAP),
    .ALL(ALL),.SET(SET),.WPAGE(WPAGE),.BIT(BIT),.RPAGE(RPAGE),.Q(Q));
  task tick;
    begin
      events=ALL ? MASK : (SET ? ((64'd1 << (WPAGE*8+BIT)) & MASK) : 64'd0);
      #2; CLK=1;
      // Original vector contract: publish pre-edge dirt, reload this edge's
      // writes into the next frame. Reset wins over every event.
      if(RST) begin acc=0; pub=0; end
      else if(SWAP) begin pub=acc; acc=events; end
      else acc=acc | events;
      #1;
      for(k=0;k<8;k=k+1) begin
        RPAGE=k; #1;
        if(Q !== pub[k*8 +: 8])
          $fatal(1,"dirty-page mismatch pages=%0d cycle=%0d page=%0d got=%h expected=%h",
                 PAGES,i,k,Q,pub[k*8 +: 8]);
        checks=checks+1;
      end
      CLK=0;
    end
  endtask
  initial begin
    tick; RST=0;
    // Every event combination at every bit, including pages outside the
    // smaller memories, with a seeded live word before each combination.
    for(mode=0;mode<16;mode=mode+1) begin
      for(j=0;j<64;j=j+1) begin
        RST=0; ALL=0; SWAP=0; SET=1; WPAGE=j/8; BIT=j%8; tick;
        {RST,SWAP,ALL,SET}=mode; tick;
      end
    end
    for(i=0;i<20000;i=i+1) begin
      RST=(i%113==0); SWAP=$random(seed); ALL=($random(seed)%7==0);
      SET=$random(seed); WPAGE=$random(seed); BIT=$random(seed); tick;
    end
    $display("PASS: %0d-page published dirty RAM matches vector contract (%0d bytes)",PAGES,checks);
    DONE=1;
  end
endmodule
module gbc_dirty_pages_tb;
  wire a,b,c;
  dirty_pages_case #(.PAGES(4)) obj(.DONE(a));
  dirty_pages_case #(.PAGES(6)) chr(.DONE(b));
  dirty_pages_case #(.PAGES(8)) map(.DONE(c));
  initial begin wait(a && b && c); $finish; end
endmodule
