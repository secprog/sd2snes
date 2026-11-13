`timescale 1ns/1ps
// Real main.v SRAM controller + real producer, with 45 ns external SRAM.
// A byte read by the SNES must win even at the shortest ROM bus period.
module gbc_sram_bus_tb;
  reg clk=0;
  always #6 clk=~clk;
  reg rst=1,wr=0,last=0;
  reg [4:0] row=0,col=0;
  reg [2:0] line=0;
  reg [63:0] pixels=64'h13579bdf2468ace0;
  wire req,mwr,ack,commit,overflow;
  wire [18:0] addr;
  wire [7:0] data,q;
  wire [18:0] ram_addr;
  wire [7:0] ram_data;
  wire ram_we,ram_oe;
  reg [23:0] snes_addr=24'he40000;
  reg cart_n=0;
  reg [23:0] addr_pipe[0:6];
  reg [6:0] cart_pipe=0;
  integer i,phase=0;
  reg foreground=0;
  // Fast ROM: 24 FPGA clocks ~= six SNES master cycles. Slow DMA: 32.
  integer period=32;
  wire cycle_start=(phase==8);
  wire pulse_end=(phase==period-1);
  wire rom_hit=!cart_pipe[6];
  wire [18:0] mapped={addr_pipe[6][19:16],addr_pipe[6][14:0]};
  always @(posedge clk) begin
    phase <= phase==period-1 ? 0 : phase+1;
    addr_pipe[0]<=snes_addr;
    for(i=1;i<7;i=i+1)addr_pipe[i]<=addr_pipe[i-1];
    cart_pipe<={cart_pipe[5:0],cart_n};
  end
  gbc_sram_arb_model arb(.CLK2(clk),.SNES_ADDR_IN(snes_addr),
    .SNES_ROMSEL_IN(cart_n),.SNES_cycle_start(cycle_start),
    .SNES_PULSE_end(pulse_end),.ROM_HIT(rom_hit),.MAPPED_SNES_ADDR(mapped),
    .FB_MEM_REQ(req),.FB_MEM_WR(mwr),.FB_MEM_ADDR(addr),.FB_MEM_DATA(data),
    .FB_MEM_ACK(ack),.FB_MEM_Q(q),.RAM_ADDR(ram_addr),.RAM_DATA(ram_data),
    .RAM_WE(ram_we),.RAM_OE(ram_oe));
  c6_sram producer(.CLK(clk),.RST(rst),.WR(wr),.WR_ROW(row),.WR_COL(col),
    .WR_LINE(line),.WR_LAST(last),.WR_PIXELS(pixels),.COMMIT(commit),
    .OVERFLOW(overflow),.PREPARE(1'b0),.PREPARE_ROW(5'd0),.STRETCH(1'b0),
    .FROZEN(18'd0),.INVALIDATE(18'd0),.VADDR(16'd0),.MEM_REQ(req),.MEM_WR(mwr),
    .MEM_ADDR(addr),.MEM_DATA(data),.MEM_ACK(ack),.MEM_Q(q));
  reg [7:0] ram[0:524287];
  // SRAM output settles 45 ns after address/enable changes. Writes commit on
  // /WE's rising edge; main.v must keep address/data through that edge.
  assign #45 ram_data=ram_we&&!ram_oe ? ram[ram_addr] : 8'bz;
  integer writes=0;
  always @(posedge ram_we) if(!rst)begin
    if(ram_addr<19'h70000 || ram_addr>=19'h79000 || (^ram_data)===1'bx)
      $fatal(1,"write lost address/data hold at SRAM: %h %h",ram_addr,ram_data);
    ram[ram_addr]=ram_data;writes=writes+1;
  end
  integer commits=0,reads=0;
  always @(posedge clk)if(!rst&&commit)commits=commits+1;
  // Sample before changing the next bus address, as the actual CPU does.
  always @(negedge clk)if(!rst&&foreground&&phase==period-1)begin
    if(ram_we!==1'b1 || ram_addr!==mapped || ram_data!==ram[mapped])
      $fatal(1,"foreground ROM missed its latch: phase=%d addr=%h want=%h data=%h",phase,ram_addr,mapped,ram_data);
    reads=reads+1;
  end
  integer y,c,k,start_count;
  initial begin
    for(i=0;i<524288;i=i+1)ram[i]=(i^8'h5a)&255;
    for(i=0;i<7;i=i+1)addr_pipe[i]=snes_addr;
    repeat(10)@(negedge clk);rst=0;
    // A continuous video-view DMA leaves SRAM free, even with /CART low.
    // At the old one-transfer-per-SNES-cycle rate this overflows by line 3.
    for(y=0;y<16;y=y+1)begin
      for(c=0;c<20;c=c+1)begin
        @(negedge clk);row=y/8;line=y%8;col=c;last=c==19&&y%8==7;wr=1;
        @(negedge clk);wr=0;
        repeat(159)@(negedge clk);
      end
      repeat(5920)@(negedge clk);
      if(overflow)$fatal(1,"producer overflow during view DMA");
    end
    while(commits<320)@(negedge clk);
    if(writes!=2560)$fatal(1,"lost/duplicated physical writes: %d",writes);
    $display("PASS: full-rate LCD producer during continuous slow video DMA");
    // Try every alignment of a background operation with an incoming fast
    // ROM cycle. Pending writes must retire and yield in time for its latch.
    period=24;
    for(k=0;k<48;k=k+1)begin
      @(negedge clk);snes_addr=24'he20200;foreground=0;
      repeat(40)@(negedge clk);
      start_count=commits;
      row=2;col=k%20;line=k%8;wr=1;last=0;
      @(negedge clk);wr=0;
      repeat(k)@(negedge clk);
      snes_addr=24'h008100+k;foreground=1;phase=0;
      repeat(120)@(negedge clk);
      foreground=0;snes_addr=24'he20200;
      while(commits==start_count)@(negedge clk);
    end
    if(overflow||reads<100)$fatal(1,"bus recovery coverage incomplete");
    $display("PASS: %0d fast ROM latches, all background alignments, 45 ns SRAM and write hold",reads);
    $finish;
  end
  initial begin #10000000;$fatal(1,"watchdog");end
endmodule
