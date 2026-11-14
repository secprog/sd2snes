`timescale 1ns/1ps
// Wave RAM has two asynchronous readers and one CPU write address. A validity
// bit per byte restores the exact SGB2 reset pattern immediately, while the
// payload remains in LUT RAM. Disabling the APU does not clear the contents.
module gbc_wave_ram(input CLK, RST, WE, input [3:0] CPU_ADDR, WAVE_ADDR,
                    input [7:0] DATA, output [7:0] CPU_Q, WAVE_Q);
  (* ram_style="distributed" *) reg [7:0] bytes [0:15];
  reg [15:0] valid;
  localparam [127:0] RESET_BYTES=128'h9f00ff08ff0257007f006608df04f708;
  always @(posedge CLK) if(WE && !RST) bytes[CPU_ADDR]<=DATA;
  genvar byte_index;
  generate for(byte_index=0;byte_index<16;byte_index=byte_index+1) begin : g_byte
    always @(posedge CLK)
      if(RST) valid[byte_index]<=0;
      else if(WE && CPU_ADDR==byte_index) valid[byte_index]<=1;
  end endgenerate
  assign CPU_Q=valid[CPU_ADDR] ? bytes[CPU_ADDR] : RESET_BYTES[CPU_ADDR*8 +: 8];
  assign WAVE_Q=valid[WAVE_ADDR] ? bytes[WAVE_ADDR] : RESET_BYTES[WAVE_ADDR*8 +: 8];
endmodule

// Double-buffered page dirt. COMMIT swaps the published/live banks, and a
// simultaneous write belongs to the new live bank. Per-byte validity clears
// a bank immediately without clearing RAM; ALL supplies an all-one default.
// Only the requested published byte is read, so this remains a two-port RAM.
module gbc_dirty_pages #(parameter PAGES=8)(input CLK, RST, SWAP, ALL, SET,
  input [2:0] WPAGE, BIT, RPAGE, output [7:0] Q);
  reg live=0;
  reg [1:0] defaults=0;
  reg [15:0] valid=0;
  (* ram_style="distributed" *) reg [7:0] bytes [0:15];
  wire write_bank=live ^ SWAP;
  wire [3:0] wa={write_bank,WPAGE}, ra={~live,RPAGE};
  wire set_ok=SET && WPAGE<PAGES;
  wire old_valid=!SWAP && valid[{live,WPAGE}];
  wire [7:0] base=old_valid ? bytes[wa] : {8{!SWAP && defaults[live]}};
  always @(posedge CLK) begin
    if(!RST && !ALL && set_ok) bytes[wa]<=base | (8'b1 << BIT);
    if(RST) begin live<=0; defaults<=0; end
    else begin
      if(SWAP) live<=~live;
      if(SWAP || ALL) defaults[write_bank]<=ALL;
    end
  end
  genvar bank,page;
  generate for(bank=0;bank<2;bank=bank+1) begin : g_bank
    for(page=0;page<PAGES;page=page+1) begin : g_page
      wire selected=write_bank==bank;
      wire clear_here=selected && (SWAP || ALL);
      wire set_here=selected && set_ok && WPAGE==page && !ALL;
      always @(posedge CLK)
        valid[bank*8+page]<=!RST && (set_here || (!clear_here && valid[bank*8+page]));
    end
  end endgenerate
  assign Q=RPAGE>=PAGES ? 8'd0 : valid[ra]
          ? bytes[ra] : {8{defaults[~live & 1'b1]}};
endmodule

// Sprite positions are inserted once and invalidated after use. Keep the
// original $f0 sentinel using a validity bit, instead of writing eight bits
// on every clear/consume. Lookup order and combinational latency are unchanged.
module gbc_oam_positions #(parameter SLOTS=10)(input CLK, CLEAR, WRITE, CONSUME,
  input [3:0] WADDR, CADDR, RADDR, input [7:0] DATA, input [4:0] TILE,
  output [7:0] Q, output FOUND, output [3:0] MATCH);
  wire [SLOTS*8-1:0] positions;
  wire [SLOTS-1:0] valid_slots, match_slots;
  genvar slot;
  generate for(slot=0;slot<SLOTS;slot=slot+1) begin : g_slot
    reg [7:0] xpos;
    reg valid=0;
    wire write_here=WRITE && WADDR==slot;
    wire consume_here=CONSUME && CADDR==slot;
    always @(posedge CLK) begin
      if(write_here) xpos<=DATA;
      valid<=!consume_here && (write_here || (!CLEAR && valid));
    end
    assign positions[slot*8 +: 8]=xpos;
    assign valid_slots[slot]=valid;
    assign match_slots[slot]=valid ? xpos[7:3]==TILE : TILE==5'd30;
  end endgenerate
  // Apply the sentinel after selecting a byte. Masking every stored position
  // would put an eight-bit mux in front of each slot and its lookup comparator.
  assign Q=valid_slots[RADDR] ? positions[RADDR*8 +: 8] : 8'hf0;
  function [4:0] select_first_slot;
    input [SLOTS-1:0] hits;
    integer lookup;
    begin
      select_first_slot={1'b0,4'hf};
      for(lookup=SLOTS-1;lookup>=0;lookup=lookup-1)
        if(hits[lookup]) select_first_slot={1'b1,lookup[3:0]};
    end
  endfunction
  assign {FOUND,MATCH}=select_first_slot(match_slots);
endmodule

// Per-row enables avoid a variable bit write becoming a wide feedback mux.
// Preserve the original procedural priority even when C6_OFF, ROW_DONE,
// thaw and a delayed SRAM commit coincide on one clock.
module c6_row_flags(input CLK, RST, OFF, THAW, FREEZE, CLID,
  input [17:0] DONE, input [4:0] THAW_ROW, FREEZE_ROW,
  output reg [17:0] FROZEN, PENDING, ROW_CLID);
  wire keep_pending = !OFF || (|DONE);
  genvar row;
  generate for(row=0;row<18;row=row+1) begin : g_row
    wire thaw_here = THAW && THAW_ROW==row;
    wire freeze_here = FREEZE && FREEZE_ROW==row;
    always @(posedge CLK) begin
      if(RST) begin
        FROZEN[row] <= 0;
        PENDING[row] <= 0;
        ROW_CLID[row] <= 0;
      end else begin
        FROZEN[row] <= freeze_here || (!OFF && !thaw_here && FROZEN[row]);
        PENDING[row] <= !thaw_here && ((keep_pending && PENDING[row]) || DONE[row]);
        if(thaw_here) ROW_CLID[row] <= CLID;
      end
    end
  end endgenerate
endmodule

// Small memories can use LUT RAM on Mk.II when no block RAM is available.
// Port B is read-only in this build: SGB_MCU_ACCESS is disabled. Both clocks
// are the same CLK; HRAM removes the unused second port before inference.
module gbc_small_ram #(parameter ABITS=8, READ_B=1)(
  input clka, wea,
  input [ABITS-1:0] addra,
  input [7:0] dina,
  output reg [7:0] douta,
  input clkb, web,
  input [ABITS-1:0] addrb,
  input [7:0] dinb,
  output reg [7:0] doutb
);
  (* ram_style = "distributed" *) reg [7:0] ram[0:(1<<ABITS)-1];
  integer i;
  initial for(i=0;i<(1<<ABITS);i=i+1)ram[i]=0;
  always @(posedge clka) begin
    if(wea)ram[addra]<=dina;
    douta<=ram[addra];
  end
  // HRAM has no bridge reader and its MCU debug port is disabled. Remove the
  // read port before RAM inference so XST can use single-port LUT memories.
  generate if (READ_B) begin : g_read_b
    always @(posedge clka) doutb<=ram[addrb];
  end else begin : g_no_read_b
    always @(posedge clka) doutb<=0;
  end endgenerate
  // synthesis translate_off
  always @(posedge clka) if(web) $fatal(1,"Mk.II LUT RAM port B is read-only");
  // synthesis translate_on
endmodule

// One 256x32 block RAM for the double-buffered OAM and palette snapshots.
// OAM occupies words 0..127; CRAM occupies words 128..191. The bridge's copy
// stream groups four OAM bytes into a word and delivers CRAM byte by byte.
// Schedule the resulting OAM/CRAM writes on consecutive clocks. The read
// still has one clock of latency, and its byte lane is registered with it.
module gbc_snapshot_ram(input CLK, RST,
  input OAM_WE, input [6:0] OAM_WADDR, input [31:0] OAM_DATA,
  input CRAM_WE, input [7:0] CRAM_WADDR, input [7:0] CRAM_DATA,
  input [6:0] OAM_RADDR, input [7:0] CRAM_RADDR, input CRAM_READ,
  output [31:0] OAM_Q, output [7:0] CRAM_Q);
  (* ram_style = "block" *) reg [31:0] words [0:255];
  reg [31:0] q;
  reg [1:0] read_byte;
  wire [7:0] read_addr = CRAM_READ ? {2'b10,CRAM_RADDR[7:2]} : {1'b0,OAM_RADDR};
  reg oam_pending=0, cram_pending=0, cram_delayed=0;
  reg [6:0] oam_addr;
  reg [5:0] cram_addr;
  reg [31:0] oam_word, cram_word;
  reg [23:0] cram_shift;
  // Present exactly one write address/data/enable to XST. Separate indexed
  // assignments are treated as multiple write ports and flatten this RAM.
  wire write_enable = !RST && (oam_pending || cram_delayed);
  wire [7:0] write_addr = oam_pending ? {1'b0,oam_addr} : {2'b10,cram_addr};
  wire [31:0] write_data = oam_pending ? oam_word : cram_word;
  integer init_i;
  initial for(init_i=0;init_i<256;init_i=init_i+1) words[init_i]=0;
  always @(posedge CLK) begin
    oam_pending <= OAM_WE & ~RST;
    cram_pending <= CRAM_WE & (&CRAM_WADDR[1:0]) & ~RST;
    cram_delayed <= cram_pending & ~RST;
    if(OAM_WE) begin oam_addr<=OAM_WADDR; oam_word<=OAM_DATA; end
    if(CRAM_WE) begin
      cram_shift <= {CRAM_DATA,cram_shift[23:8]};
      if(&CRAM_WADDR[1:0]) begin
        cram_addr <= CRAM_WADDR[7:2];
        cram_word <= {CRAM_DATA,cram_shift};
      end
    end
    if(write_enable) words[write_addr] <= write_data;
    q <= words[read_addr];
    read_byte <= CRAM_RADDR[1:0];
  end
  assign OAM_Q = q;
  assign CRAM_Q = read_byte == 0 ? q[7:0] : read_byte == 1 ? q[15:8]
                : read_byte == 2 ? q[23:16] : q[31:24];
  // synthesis translate_off
  always @(posedge CLK) if(!RST && oam_pending && cram_delayed)
    $fatal(1,"snapshot copy stream violates the four-byte write cadence");
  // synthesis translate_on
endmodule

// PPU pixel FIFO, two asynchronous read ports and one clocked write. Keeping
// the entire word on each read lets XST share the colour/priority/palette
// address decode instead of treating an expanded case as a third read port.
module gbc_pixel_ram #(parameter WIDTH=4)(input CLK, WE,
  input [4:0] WADDR, RADDR, input [WIDTH-1:0] DATA,
  output [WIDTH-1:0] WRITE_Q, READ_Q);
  (* ram_style = "distributed" *) reg [WIDTH-1:0] pixels [0:31];
  always @(posedge CLK) if(WE) pixels[WADDR] <= DATA;
  assign WRITE_Q = pixels[WADDR];
  assign READ_Q = pixels[RADDR];
endmodule

// Wire $05 gives each 20-cell row four status-byte addresses. The player
// still reads three bytes, with the original odd-row nibble alignment. Row
// padding removes cross-row reads and their division/parity/bank selection.
// Tags retain immediate reset/restart/ROW_DONE, and SET still wins CLEAR.
module c6_dirty_ram(input CLK, RST, ALL, SET, input [4:0] ROW, COL,
                    input [17:0] CLEAR, input [6:0] BIDX, output reg [7:0] BYTE);
  reg [17:0] valid, default_one;
  wire [17:0] clear_rows = CLEAR | {18{RST}};
  wire set_ok = SET && ROW < 18 && COL < 20;
  wire [17:0] set_rows = set_ok ? (18'd1 << ROW) : 18'd0;
  wire [19:0] col_mask = 20'd1 << COL;
  wire [4:0] read_row = BIDX[6:2];
  // Keep each parity in a 16-deep RAM. Selecting the byte before combining
  // the banks avoids a 20-bit, 32-deep read mux and a wide nibble shifter.
  (* ram_style = "distributed" *) reg [19:0] even_rows [0:15];
  (* ram_style = "distributed" *) reg [19:0] odd_rows [0:15];
  wire [19:0] write_word = ROW[0] ? odd_rows[ROW[4:1]] : even_rows[ROW[4:1]];
  wire [19:0] base_word = clear_rows[ROW] ? 20'd0
                         : valid[ROW] ? write_word : {20{default_one[ROW]}};
  wire [19:0] read_even = even_rows[BIDX[6:3]], read_odd = odd_rows[BIDX[6:3]];
  reg [7:0] read_byte, mask_byte;
  always @(posedge CLK) begin
    if(set_ok && !ALL && !ROW[0]) even_rows[ROW[4:1]] <= base_word | col_mask;
    if(set_ok && !ALL &&  ROW[0])  odd_rows[ROW[4:1]] <= base_word | col_mask;
    valid <= ALL ? 18'd0 : ((valid & ~clear_rows) | set_rows);
    default_one <= ALL ? 18'h3ffff : (default_one & ~clear_rows);
  end
  always @(*) begin
    case(BIDX[2:0])
      0: begin read_byte=read_even[7:0]; mask_byte=8'hff; end
      1: begin read_byte=read_even[15:8]; mask_byte=8'hff; end
      2: begin read_byte={4'd0,read_even[19:16]}; mask_byte=8'h0f; end
      4: begin read_byte={read_odd[3:0],4'd0}; mask_byte=8'hf0; end
      5: begin read_byte=read_odd[11:4]; mask_byte=8'hff; end
      6: begin read_byte=read_odd[19:12]; mask_byte=8'hff; end
      default: begin read_byte=0; mask_byte=0; end
    endcase
    BYTE = read_row >= 18 ? 8'd0 : valid[read_row] ? read_byte
                               : (mask_byte & {8{default_one[read_row]}});
  end
endmodule
// Three physical 512x32 / 2048x8 blocks. The hardware's narrow read port
// selects the byte, so only eight bits need the three-bank output mux.
// READ_FIRST also preserves the old data on a same-clock same-word write.
module gbc_log_ram(input CLK, WE, input [10:0] WADDR,
                   input [31:0] DATA, input [12:0] RADDR, output [7:0] Q);
  wire [23:0] bank_q;
  reg [1:0] read_bank;
  genvar bank;
  generate
    for (bank=0; bank<3; bank=bank+1) begin : g_bank
      RAMB16_S9_S36 #(.WRITE_MODE_A("READ_FIRST"), .WRITE_MODE_B("READ_FIRST")) words(
        .CLKA(CLK), .ENA(1'b1), .SSRA(1'b0), .WEA(1'b0),
        .ADDRA(RADDR[10:0]), .DIA(8'd0), .DIPA(1'b0),
        .DOA(bank_q[8*bank +: 8]), .DOPA(),
        .CLKB(CLK), .ENB(1'b1), .SSRB(1'b0), .WEB(WE && WADDR[10:9]==bank),
        .ADDRB(WADDR[8:0]), .DIB(DATA), .DIPB(4'd0), .DOB(), .DOPB());
    end
  endgenerate
  always @(posedge CLK) read_bank <= RADDR[12:11];
  assign Q = read_bank == 0 ? bank_q[7:0]
           : read_bank == 1 ? bank_q[15:8]
           : read_bank == 2 ? bank_q[23:16] : 8'd0;
endmodule
