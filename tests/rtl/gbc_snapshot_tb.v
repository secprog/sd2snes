`timescale 1ns/1ps
// Exercise the complete copy engine and its SNES views. The oracle keeps the
// original byte-addressed GB memories, independent of the packed FPGA layout.
module gbc_snapshot_tb;
  reg CLK=0, RST=1, WR=0, VIEW=0, EF=0, LY0=0, COMPAT=0;
  reg [23:0] ADDR=0;
  reg [7:0] DIN=0, LCDC=8'h87;
  reg FB_ACK=0, PIXEL=0;
  reg VWE=0, VBANK=0;
  reg [12:0] VADDR=0;
  reg [7:0] PX_X=0,PX_Y=0;
  wire [7:0] DOUT, OADDR;
  wire [6:0] CADDR;
  wire OREQ, CREQ;
  reg [7:0] ODATA=0, CDATA=0;
  reg [7:0] live_oam[0:159], live_cram[0:127];
  reg [7:0] shown_oam[0:159], shown_cram[0:127];
  reg [7:0] shown_lcdc;
  reg shown_compat;
  integer frame, i, checks=0, seq_expected=0, seed=32'h4319eb7;

  gbc_bridge dut(.CLK(CLK),.RST(RST),.SNES_WR_end(WR),.SNES_ADDR(ADDR),
    .DATA_IN(DIN),.VIEW_ENABLE(VIEW),.EF_ENABLE(EF),.DATA_OUT(DOUT),
    .FB_MEM_ACK(FB_ACK),.FB_MEM_Q(8'd0),.CE1(1'b0),.BUS_EDGE(1'b0),
    .STARVATION(16'd0),.DILATION(16'd0),.P1I(2'b11),
    .PPU_DOT_EDGE(1'b0),.PPU_VSYNC_EDGE(1'b0),.LCD_ON(1'b1),.COMPAT(COMPAT),
    .C6_PX_VALID(PIXEL),.C6_PX_X(PX_X),.C6_PX_Y(PX_Y),.C6_PX_BGR(15'd0),
    .TAP_VRAM_WE(VWE),.TAP_VRAM_BANK(VBANK),.TAP_VRAM_ADDR(VADDR),
    .TAP_OAM_WE(1'b0),.TAP_CRAM_WE(1'b0),.TAP_CRAM_IDX(7'd0),.TAP_CRAM_DATA(8'd0),
    .TAP_LY0(LY0),.TAP_VBLANK(1'b0),.TAP_LY(8'd0),.TAP_LCDC(LCDC),
    .TAP_SCX(8'd0),.TAP_SCY(8'd0),.TAP_WX(8'd0),.TAP_WY(8'd0),
    .TAP_BGP(8'h1b),.TAP_OBP0(8'h6c),.TAP_OBP1(8'h93),.TAP_OPRI(8'd0),
    .TAP_KEY0(8'd0),.TAP_KEY1(8'd0),.TAP_VBK(8'd0),.TAP_SVBK(8'd0),
    .TAP_SPEED_REQ(1'b0),.TAP_MF_VALID(1'b0),.TAP_MF_KIND(4'd0),
    .TAP_MF_IDX(6'd0),.TAP_MF_VALUE(8'd0),.TAP_MF_LY(8'd0),
    .TAP_MF_BEFORE_MODE3(1'b0),.VRAM0_B_DATA(8'd0),.VRAM1_B_DATA(8'd0),
    .OAM_RD_REQ(OREQ),.OAM_RD_ADDR(OADDR),.OAM_RD_DATA(ODATA),
    .CRAM_RD_REQ(CREQ),.CRAM_RD_ADDR(CADDR),.CRAM_RD_DATA(CDATA),
    .LOCKED(1'b0),.SYNC_ERR_LAST(16'd0),.DBG_ADDR(12'd0));

  always @(posedge CLK) begin
    if(OREQ) ODATA <= live_oam[OADDR];
    if(CREQ) CDATA <= live_cram[CADDR];
  end
  // Independent original whole-vector CHR and OBJ accumulators. In
  // particular, writes on COMMIT belong to the NEXT published frame.
  reg [47:0] chr_acc=0, chr_pub=0;
  reg [31:0] obj_acc=0, obj_pub=0;
  reg gold_busy=0;
  wire [47:0] chr_set=(VWE && VADDR<13'h1800)
                     ? (48'd1 << (24*VBANK+(VADDR/256))) : 48'd0;
  wire [31:0] obj_set=(VWE && VADDR<13'h1000)
                     ? (32'd1 << (16*VBANK+(VADDR/256))) : 32'd0;
  always @(posedge CLK) begin
    if(RST) begin
      chr_acc<=0; chr_pub<=0; obj_acc<=0; obj_pub<=0; gold_busy<=0;
    end else begin
      if(EF && WR && ADDR[7:0]==2 && !gold_busy) begin
        chr_pub<=chr_acc; obj_pub<=obj_acc; chr_acc<=chr_set; obj_acc<=obj_set;
      end else begin chr_acc<=chr_acc|chr_set; obj_acc<=obj_acc|obj_set; end
      if(EF && WR && ADDR[7:0]==2) gold_busy<=1;
      if(EF && WR && ADDR[7:0]==5) gold_busy<=0;
    end
  end
  task tick;
    begin #4; CLK=1; #1; CLK=0; #5; end
  endtask
  task read_status(input [23:0] a, input [7:0] expected);
    begin
      // Wire $04 permits up to three clocks for the full view window.
      VIEW=1; ADDR=a; tick; tick; tick;
      if(DOUT !== expected)
        $fatal(1,"C6 status address=%h got=%h expected=%h",a,DOUT,expected);
      checks=checks+1;
    end
  endtask
  task command(input [7:0] a);
    begin VIEW=0; EF=1; ADDR={16'hef00,a}; WR=1; tick; WR=0; EF=0; end
  endtask
  task read_dirty;
    integer n;
    begin
      for(n=0;n<6;n=n+1) read_status(24'he20210+n,chr_pub>>(8*n));
      for(n=0;n<4;n=n+1) read_status(24'he20216+n,obj_pub>>(8*n));
    end
  endtask
  task read_byte(input [23:0] a, input [7:0] expected);
    begin
      VIEW=1; ADDR=a; tick; tick;
      if(DOUT !== expected) begin
        $display("snapshot frame=%0d addr=%h got=%h expected=%h",frame,a,DOUT,expected);
        $fatal(1);
      end
      checks=checks+1;
    end
  endtask
  function [7:0] palette_byte(input integer a);
    integer color, p, k, idx, mapping;
    reg [7:0] result;
    begin
      color=a/2;
      if(color<128) begin
        p=color%32/4; k=color%4;
        if(color>=64) k=0;
        if(shown_compat) k=(8'h1b>>(2*k))&3;
        idx=p*8+k*2+a%2;
      end else begin
        p=(color-128)/16; k=color%16;
        mapping=p==0 ? 8'h6c : 8'h93;
        if(shown_compat) k=(mapping>>(2*k))&3;
        idx=64+p*8+k*2+a%2;
      end
      result=shown_cram[idx];
      if(a%2) result=result&8'h7f;
      if(color<128 && color>=64 && color%4!=1) result=0;
      if(color>=128 && (color%16==0 || color%16>3)) result=0;
      if(color==0) result=0;
      if(color==98) result=a%2 ? 8'h7f : 8'hff;
      palette_byte=result;
    end
  endfunction
  function [7:0] sprite_byte(input integer a);
    integer sprite, half, byte_n, y, x, tile, attr, pri, pal, visible;
    begin
      sprite=a/8; half=a%8/4; byte_n=a%4;
      y=0; x=0; tile=0; attr=0;
      if(sprite<40) begin
        y=shown_oam[sprite*4]; x=shown_oam[sprite*4+1];
        tile=shown_oam[sprite*4+2]; attr=shown_oam[sprite*4+3];
      end
      visible=shown_lcdc[1] && sprite<40 && x>=1 && x<=167 && y<=159
        && (shown_lcdc[2] ? y>=1 : y>=9) && (!half || shown_lcdc[2]);
      if(shown_lcdc[2]) tile=(tile&254) | (half ^ ((attr>>6)&1));
      pri=(attr&128) && (shown_compat || shown_lcdc[0]) ? 1 : 2;
      pal=shown_compat ? ((attr>>4)&1) : (attr&7);
      if(!visible) sprite_byte=byte_n==1 ? 8'hf0 : 0;
      else case(byte_n)
        0: sprite_byte=x+40;
        1: sprite_byte=y+24+half*8;
        2: sprite_byte=tile;
        3: sprite_byte=((attr&64)<<1)|((attr&32)<<1)|(pri<<4)|(pal<<1)
                       | (!shown_compat && (attr&8)!=0);
      endcase
    end
  endfunction
  task remember;
    integer n;
    begin
      for(n=0;n<160;n=n+1) shown_oam[n]=live_oam[n];
      for(n=0;n<128;n=n+1) shown_cram[n]=live_cram[n];
      shown_lcdc=LCDC; shown_compat=COMPAT;
      seq_expected=seq_expected+1;
    end
  endtask
  task check_views;
    integer n, idx;
    reg [7:0] expected;
    begin
      // Alternate read ports on every transaction, including unused sprites,
      // all palette lanes and both copies of the BG palette.
      for(n=0;n<512;n=n+1) begin
        read_byte(24'he30000+n,sprite_byte(n));
        read_byte(24'he20000+n,palette_byte(n));
      end
      for(n=0;n<24;n=n+1) begin
        idx=n<8 ? n : 64+n-8;
        expected=shown_cram[idx]; if(n%2) expected=expected&8'h7f;
        read_byte(24'he20240+n,expected);
      end
      read_byte(24'he2020e,seq_expected);
    end
  endtask
  initial begin
    tick; tick; RST=0;
    for(frame=0;frame<24;frame=frame+1) begin
      for(i=0;i<160;i=i+1) live_oam[i]=(i*29+frame*73)%256;
      for(i=0;i<128;i=i+1) live_cram[i]=(i*53+frame*17)%256;
      LCDC=8'h80 | (frame%8); COMPAT=(frame/8)%2;
      // Keep the last sprite visible: the first read after publication must
      // see all four bytes, including the word written on that same edge.
      live_oam[156]=40+frame; live_oam[157]=80+frame;
      if(frame%2) command(8'h02);
      LY0=1; tick; LY0=0;
      if(frame%2) begin
        // Read the previous snapshot while the hidden half is overwritten.
        // It must remain coherent even after copying has finished.
        check_views;
        command(8'h05);
      end else repeat(163) tick;
      remember;
      read_byte(24'he30138,sprite_byte(312));
      read_byte(24'he3013b,sprite_byte(315));
      check_views;
    end
    // Reset at each position in the copy, including its two write-drain
    // cycles, then overwrite the same hidden half with a complete snapshot.
    for(frame=0;frame<164;frame=frame+1) begin
      LY0=1; tick; LY0=0; repeat(frame) tick;
      RST=1; tick; tick; RST=0; seq_expected=0;
      for(i=0;i<160;i=i+1) live_oam[i]=i+frame;
      for(i=0;i<128;i=i+1) live_cram[i]=i+frame;
      LY0=1; tick; LY0=0; repeat(163) tick;
      remember; check_views;
    end
    $display("PASS: shared snapshot RAM, coherent publication, two-cycle views and copy reset (%0d bytes)",checks);
    // Real bridge/row/cache handshake, including alternating the registered
    // READY status with ordinary status and dirty bytes. SRAM content is zero;
    // its electrical timing/backpressure are exercised by gbc_sram_bus_tb.
    FB_ACK=1; DIN=3; command(8'h06); repeat(4) tick;
    LY0=1; tick; LY0=0; repeat(4) tick;
    for(i=0;i<1280;i=i+1) begin
      PX_X=i%160; PX_Y=i/160; PIXEL=1; tick;
      PIXEL=0; repeat(19) tick;
    end
    repeat(200) tick;
    read_status(24'he2025a,1);
    read_status(24'he20292,8'hff);
    DIN=0; command(8'h08);
    VIEW=1; ADDR=24'he20292; repeat(3) tick; i=0;
    while(DOUT!==0 && i<20000) begin tick; i=i+1; end
    if(DOUT!==0) $fatal(1,"C6 row cache never became ready");
    read_status(24'he20200,4);
    read_status(24'he20260,8'hff);
    read_status(24'he20292,0);
    DIN=18; command(8'h07); // Invalid release must not invalidate row 0.
    read_status(24'he20292,0);
    DIN=0; command(8'h07);
    read_status(24'he20292,8'hff);
    read_status(24'he20260,0);
    read_status(24'he20261,0);
    read_status(24'he20262,8'hf0);
    read_status(24'he20263,8'hff);
    read_status(24'he20292,8'hff);
    $display("PASS: complete C6 bridge prepare/ready/release and mixed status latency");
    // One-hot writes in every bank/block, including map-only addresses,
    // reset, repeated COMMIT, and a write concurrent with the first COMMIT.
    for(i=0;i<64;i=i+1) begin
      RST=1; tick; RST=0;
      VWE=1; VBANK=i/32; VADDR=(i%32)*256+255; tick;
      command(2); read_dirty;
      command(2); VWE=0; read_dirty; // busy: publish must remain unchanged
      command(5); command(2); read_dirty;
      command(5); command(2); read_dirty; // now empty
    end
    for(i=0;i<2000;i=i+1) begin
      VWE=$random(seed); VBANK=$random(seed); VADDR=$random(seed);
      if(i%11==0) command(2);
      else if(i%13==0) command(5);
      else tick;
      if(i%7==0) read_dirty;
    end
    VWE=0;
    $display("PASS: shared CHR/OBJ dirt matches independent published vectors across all blocks and commit collisions");
    $finish;
  end
endmodule
