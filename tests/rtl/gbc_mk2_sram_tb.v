`timescale 1ns/1ps
module gbc_mk2_sram_tb;
  reg clk=0;
  always #5 clk=~clk;
  reg rst=1, wr=0, last=0, prepare=0, stretch=0;
  reg [4:0] row=0, col=0, prep_row=0;
  reg [2:0] line=0;
  reg [63:0] pixels=0;
  reg [17:0] frozen=0, invalidate=0;
  reg [15:0] vaddr=0;
  wire commit, commit_last, commit_diff, overflow;
  wire [4:0] commit_row, commit_col;
  wire [7:0] view_byte, ready;
  wire req, mem_wr;
  wire [18:0] addr;
  wire [7:0] data;
  reg ack=0;
  reg [7:0] q=0;
  c6_sram dut(.CLK(clk),.RST(rst),.WR(wr),.WR_ROW(row),.WR_COL(col),
    .WR_LINE(line),.WR_LAST(last),.WR_PIXELS(pixels),.COMMIT(commit),
    .COMMIT_ROW(commit_row),.COMMIT_COL(commit_col),.COMMIT_LAST(commit_last),
    .COMMIT_DIFF(commit_diff),.OVERFLOW(overflow),.PREPARE(prepare),
    .PREPARE_ROW(prep_row),.STRETCH(stretch),.FROZEN(frozen),.INVALIDATE(invalidate),
    .VADDR(vaddr),.VIEW_BYTE(view_byte),.READY_ROW(ready),.MEM_REQ(req),
    .MEM_WR(mem_wr),.MEM_ADDR(addr),.MEM_DATA(data),.MEM_ACK(ack),.MEM_Q(q));

  reg [7:0] ram[0:65535];
  reg busy=0, allow=1;
  reg [18:0] held_addr;
  reg [7:0] held_data;
  reg held_wr;
  integer delay_count=0, slow=0, transactions=0;
  reg [15:0] random_state=16'hc6a5;
  // The SRAM arbiter can pause for arbitrary periods. Every pending request
  // must remain stable; ACK completes exactly one byte transaction.
  always @(posedge clk) begin
    ack<=0;
    if(rst) begin busy<=0; ack<=0; end
    else if(busy) begin
      if(!req || addr!==held_addr || mem_wr!==held_wr || data!==held_data)
        $fatal(1,"request changed while stalled");
      if(allow) begin
        if(delay_count==0) begin
          if(held_wr) ram[held_addr[15:0]]<=held_data;
          else q<=ram[held_addr[15:0]];
          ack<=1; busy<=0; transactions=transactions+1;
        end else delay_count=delay_count-1;
      end
    end else if(req && !ack && allow) begin
      if(addr<19'h70000 || addr>=19'h79000)
        $fatal(1,"framebuffer touched player memory: %h",addr);
      held_addr<=addr; held_wr<=mem_wr; held_data<=data;
      random_state<={random_state[14:0],random_state[15]^random_state[13]^random_state[12]^random_state[10]};
      delay_count=slow ? slow : (random_state[2:0]+1);
      busy<=1;
    end
  end
  integer commits=0, last_commits=0, diffs=0;
  always @(posedge clk) if(!rst && commit) begin
    commits=commits+1;
    if(commit_diff) diffs=diffs+1;
    if(commit_last) begin
      last_commits=last_commits+1;
      if(commit_col!=19) $fatal(1,"wrong last column");
    end
  end

  function [7:0] pixel_at;
    input integer x,y;
    begin pixel_at=((x*37)^(y*13)^(x>>2)^8'ha5)&255; end
  endfunction
  function [7:0] expected;
    input integer r,c,b,str;
    integer p,y,k,x;
    begin
      expected=0;
      p=((b>>4)<<1)|(b&1); y=8*r+((b>>1)&7);
      for(k=0;k<8;k=k+1) begin
        if(str) begin
          case(k)
            0,1:x=5*c;
            2:x=5*c+1;
            3,4:x=5*c+2;
            5:x=5*c+3;
            default:x=5*c+4;
          endcase
        end else x=8*c+k;
        if(x<160) expected[7-k]=(pixel_at(x,y)>>p)&1;
      end
    end
  endfunction
  task reset;
    begin
      @(negedge clk);rst=1;wr=0;prepare=0;invalidate=0;frozen=0;
      repeat(3) @(negedge clk);
      rst=0;
      repeat(2) @(negedge clk);
      if(ready!==8'hff || overflow) $fatal(1,"reset did not invalidate storage");
    end
  endtask
  task write_row;
    input integer r;
    integer y,c,k,n;
    begin
      n=last_commits;
      for(y=0;y<8;y=y+1) begin
        for(c=0;c<20;c=c+1) begin
          @(negedge clk);row=r;col=c;line=y;last=(y==7 && c==19);
          for(k=0;k<8;k=k+1) pixels[63-8*k -: 8]=pixel_at(8*c+k,8*r+y);
          wr=1;
          @(negedge clk);wr=0;
          repeat(159) @(negedge clk);
        end
        // Real mode 0/2 slack: 456 dots/line minus the visible 160 dots.
        repeat(5920) @(negedge clk);
      end
      while(last_commits==n) @(negedge clk);
      if(overflow) $fatal(1,"FIFO overflow at LCD cadence");
      frozen[r]=1;
    end
  endtask
  task prepare_row;
    input integer r,str;
    integer timeout;
    begin
      @(negedge clk);stretch=str;prep_row=r;prepare=1;
      @(negedge clk);prepare=0;
      timeout=0;
      while(ready!==r && timeout<200000) begin
        @(negedge clk); timeout=timeout+1;
      end
      if(ready!==r) $fatal(1,"cache prepare timed out r=%d str=%d state=%d",r,str,dut.state);
    end
  endtask
  task check_row;
    input integer r,str;
    integer c,b;
    reg [7:0] want;
    begin
      for(c=0;c<32;c=c+1) for(b=0;b<64;b=b+1) begin
        @(negedge clk);vaddr=(r<<11)|(c<<6)|b;
        @(negedge clk);
        want=(!str && c>=20)?0:expected(r,c,b,str);
        if(view_byte!==want) $fatal(1,"pixel mismatch r=%d c=%d b=%d str=%d got=%h want=%h",r,c,b,str,view_byte,want);
      end
    end
  endtask

  integer r,i,n,d;
  initial begin
    for(i=0;i<65536;i=i+1)ram[i]=0;
    reset;
    // Every byte, every row, both modes; no image quality is traded for RAM.
    for(r=0;r<18;r=r+1) begin
      write_row(r);
      prepare_row(r,0); check_row(r,0);
      prepare_row(r,1); check_row(r,1);
    end
    if(commits!=2880 || last_commits!=18) $fatal(1,"lost/duplicated commit");
    $display("PASS: all 160x144 pixels, native and stretched planar reads");
    // Same bytes must not dirty the image; one changed byte must dirty it.
    d=diffs; frozen[0]=0;write_row(0);
    if(diffs!=d) $fatal(1,"identical pixels became dirty");
    ram[0]=ram[0]^1;
    frozen[0]=0;write_row(0);
    if(diffs!=d+1) $fatal(1,"byte compare missed/duplicated a dirty cell");
    $display("PASS: read-before-write dirty detection and commit ordering");
    prepare_row(0,0);
    @(negedge clk);invalidate=1;
    #1;if(ready!==8'hff) $fatal(1,"ROW_DONE did not immediately invalidate tag");
    @(negedge clk);invalidate=0;frozen[0]=0;
    prepare=1;prep_row=0;
    @(negedge clk);prepare=0;
    repeat(30) @(negedge clk);
    if(ready!==8'hff) $fatal(1,"open row was exposed");
    $display("PASS: ROW_DONE and open-row rejection");
    // Simultaneous cache fills and PPU bursts exercise preemption/resume.
    slow=12;frozen[0]=1;
    @(negedge clk);prep_row=0;prepare=1;
    @(negedge clk);prepare=0;
    write_row(1);
    prepare_row(0,0);check_row(0,0);
    if(overflow) $fatal(1,"prefetch starved producer");
    $display("PASS: cache preemption, SRAM stalls and PPU burst buffering");
    // Reset in flight must hide partial caches, and a hard overflow must be
    // visible rather than publishing incomplete pixels.
    @(negedge clk);stretch=1;prep_row=2;prepare=1;
    @(negedge clk);prepare=0;
    repeat(100) @(negedge clk);
    reset;
    allow=0;
    for(i=0;i<20;i=i+1)begin
      @(negedge clk);wr=1;
      @(negedge clk);wr=0;
    end
    if(!overflow || ready!==8'hff) $fatal(1,"overflow was not fail-closed");
    reset;
    $display("PASS: reset during prefetch, overflow detection and recovery");
    $display("PASS: %0d external SRAM transactions",transactions);
    $finish;
  end
  initial begin #100000000;$fatal(1,"watchdog");end
endmodule
