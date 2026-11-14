`timescale 1ns / 1ps
module gbc_dirty_ram_tb;
  reg CLK=0, RST=1, ALL=0, SET=0;
  reg [4:0] ROW=0, COL=0;
  reg [17:0] CLEAR=0;
  reg [6:0] BIDX=0;
  wire [7:0] BYTE;
  c6_dirty_ram dut(.CLK(CLK), .RST(RST), .ALL(ALL), .SET(SET),
    .ROW(ROW), .COL(COL), .CLEAR(CLEAR), .BIDX(BIDX), .BYTE(BYTE));
  reg [359:0] expected;
  reg [7:0] expected_byte;
  reg [23:0] expected_row;
  integer i, row_i, byte_i, seed=32'h76b38a2, checks=0;
  task tick;
    begin
      #2;
      // Independent packed-bitmap specification: clear complete rows, then
      // set the changed cell. Restart marks all cells dirty immediately.
      if(ALL) expected={360{1'b1}};
      else begin
        for(row_i=0;row_i<18;row_i=row_i+1)
          if(RST || CLEAR[row_i]) expected[20*row_i +: 20]=0;
        if(SET && ROW<18 && COL<20) expected[20*ROW+COL]=1;
      end
      CLK=1; #1;
      for(byte_i=0;byte_i<128;byte_i=byte_i+1) begin
        BIDX=byte_i; #1;
        expected_row=byte_i/4<18 ? (expected>>(20*(byte_i/4))) & 20'hfffff : 0;
        if((byte_i/4)%2) expected_row=expected_row<<4;
        expected_byte=byte_i%4<3 ? expected_row>>(8*(byte_i%4)) : 0;
        if(BYTE !== expected_byte) begin
          $display("dirty bitmap mismatch step=%0d byte=%0d got=%h expected=%h",
                   checks/128,byte_i,BYTE,expected_byte);
          $fatal(1);
        end
        checks=checks+1;
      end
      CLK=0;
    end
  endtask
  initial begin
    expected=0; tick; RST=0;
    // Every cell individually, followed by clearing/reusing every row. This
    // catches row padding, nibble alignment and stale RAM bits.
    SET=1;
    for(i=0;i<360;i=i+1) begin ROW=i/20; COL=i%20; tick; end
    SET=0;
    for(i=0;i<18;i=i+1) begin CLEAR=18'd1<<i; tick; end
    CLEAR=0; SET=1;
    for(i=0;i<18;i=i+1) begin ROW=i; COL=(i*7)%20; tick; end
    for(i=0;i<3000;i=i+1) begin
      ROW=$unsigned($random(seed))%32; COL=$unsigned($random(seed))%32;
      SET=$random(seed); CLEAR=$random(seed);
      if(i%7) CLEAR=0;
      RST=(i%89==0); ALL=(i%113==0);
      tick;
    end
    $display("PASS: padded dirty rows match packed 360-bit oracle in %0d byte checks",checks);
    $finish;
  end
endmodule
