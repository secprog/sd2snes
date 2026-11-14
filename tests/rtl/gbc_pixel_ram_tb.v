`timescale 1ns/1ps
module gbc_pixel_ram_tb;
  reg CLK=0, WE=0;
  reg [4:0] WADDR=0, RADDR=0;
  reg [3:0] DATA=0;
  wire [3:0] write_q, read_q;
  wire [1:0] bg_q;
  gbc_pixel_ram #(.WIDTH(4)) obj(.CLK(CLK),.WE(WE),.WADDR(WADDR),
    .RADDR(RADDR),.DATA(DATA),.WRITE_Q(write_q),.READ_Q(read_q));
  gbc_pixel_ram #(.WIDTH(2)) bg(.CLK(CLK),.WE(WE),.WADDR(WADDR),
    .RADDR(RADDR),.DATA(DATA[1:0]),.WRITE_Q(),.READ_Q(bg_q));
  reg [3:0] reference [0:31];
  integer i, j, seed=32'h24a68bc, checks=0;
  task tick;
    begin
      #2; CLK=1;
      if(WE) reference[WADDR]=DATA;
      #1;
      // The PPU depends on both ports being asynchronous, including the
      // read-modify-write port used to decide OBJ opacity/priority.
      for(j=0;j<32;j=j+1) begin
        RADDR=j; #1;
        if(read_q !== reference[j] || bg_q !== reference[j][1:0]
             || write_q !== reference[WADDR]) $fatal(1,"pixel RAM read mismatch");
        checks=checks+1;
      end
      CLK=0;
    end
  endtask
  initial begin
    // As in the PPU, write all slots before publishing pixels. No array reset
    // is required: the hardware clears the OBJ ring before its first line.
    WE=1;
    for(i=0;i<32;i=i+1) begin
      WADDR=i; DATA=i; reference[i]=DATA;
      #2; CLK=1; #1; CLK=0;
    end
    for(i=0;i<3000;i=i+1) begin
      WADDR=$random(seed); DATA=$random(seed); WE=$random(seed);
      tick;
    end
    $display("PASS: BG/OBJ FIFO ports and same-address writes (%0d reads)",checks);
    $finish;
  end
endmodule
