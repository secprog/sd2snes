`timescale 1ns/1ps
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

// 18 rows of 20 dirty cells. Even/odd rows have separate dual-port LUT RAMs:
// the producer can read-modify-write one row while the SNES reads both rows
// touched by a packed status byte. Tags give every row an immediate all-zero
// or all-one default after reset/restart/ROW_DONE, without resetting the RAM.
// SET wins over CLEAR, including a simultaneous update of that same row.
module c6_dirty_ram(input CLK, RST, ALL, SET, input [4:0] ROW, COL,
                    input [17:0] CLEAR, input [5:0] BIDX, output reg [7:0] BYTE);
  reg [17:0] valid, default_one;
  wire [17:0] clear_rows = CLEAR | {18{RST}};
  wire set_ok = SET && ROW < 18 && COL < 20;
  wire [17:0] set_rows = set_ok ? (18'd1 << ROW) : 18'd0;
  wire [19:0] col_mask = 20'd1 << COL;
  wire [39:0] write_q, read_q;
  wire [19:0] old_word = write_q[ROW[0]*20 +: 20];
  wire [19:0] base_word = clear_rows[ROW] ? 20'd0
                       : valid[ROW] ? old_word : {20{default_one[ROW]}};

  // Five status bytes contain exactly two 20-cell rows. A small constant
  // lookup avoids a divider and reads one even/odd pair in parallel.
  function [6:0] read_select;
    input [5:0] index;
    begin
    case (index)
       0: read_select={4'd0,3'd0};  1: read_select={4'd0,3'd1};
       2: read_select={4'd0,3'd2};  3: read_select={4'd0,3'd3};
       4: read_select={4'd0,3'd4};  5: read_select={4'd1,3'd0};
       6: read_select={4'd1,3'd1};  7: read_select={4'd1,3'd2};
       8: read_select={4'd1,3'd3};  9: read_select={4'd1,3'd4};
      10: read_select={4'd2,3'd0}; 11: read_select={4'd2,3'd1};
      12: read_select={4'd2,3'd2}; 13: read_select={4'd2,3'd3};
      14: read_select={4'd2,3'd4}; 15: read_select={4'd3,3'd0};
      16: read_select={4'd3,3'd1}; 17: read_select={4'd3,3'd2};
      18: read_select={4'd3,3'd3}; 19: read_select={4'd3,3'd4};
      20: read_select={4'd4,3'd0}; 21: read_select={4'd4,3'd1};
      22: read_select={4'd4,3'd2}; 23: read_select={4'd4,3'd3};
      24: read_select={4'd4,3'd4}; 25: read_select={4'd5,3'd0};
      26: read_select={4'd5,3'd1}; 27: read_select={4'd5,3'd2};
      28: read_select={4'd5,3'd3}; 29: read_select={4'd5,3'd4};
      30: read_select={4'd6,3'd0}; 31: read_select={4'd6,3'd1};
      32: read_select={4'd6,3'd2}; 33: read_select={4'd6,3'd3};
      34: read_select={4'd6,3'd4}; 35: read_select={4'd7,3'd0};
      36: read_select={4'd7,3'd1}; 37: read_select={4'd7,3'd2};
      38: read_select={4'd7,3'd3}; 39: read_select={4'd7,3'd4};
      40: read_select={4'd8,3'd0}; 41: read_select={4'd8,3'd1};
      42: read_select={4'd8,3'd2}; 43: read_select={4'd8,3'd3};
      44: read_select={4'd8,3'd4};
      default: read_select={4'd0,3'd7};
    endcase
    end
  endfunction
  wire [6:0] read_sel = read_select(BIDX);
  wire [3:0] pair_index = read_sel[6:3];
  wire [4:0] even_row = {pair_index,1'b0};
  wire [4:0] odd_row = {pair_index,1'b1};
  wire [19:0] even_bits = valid[even_row] ? read_q[19:0]
                       : {20{default_one[even_row]}};
  wire [19:0] odd_bits = valid[odd_row] ? read_q[39:20]
                      : {20{default_one[odd_row]}};
  genvar parity;
  generate
    for(parity=0; parity<2; parity=parity+1) begin : g_rows
      (* ram_style = "distributed" *) reg [19:0] rows [0:8];
      always @(posedge CLK)
        if(set_ok && !ALL && ROW[0] == parity)
          rows[ROW[4:1]] <= base_word | col_mask;
      assign write_q[parity*20 +: 20] = rows[ROW[4:1]];
      assign read_q[parity*20 +: 20] = rows[pair_index];
    end
  endgenerate
  always @(posedge CLK) begin
    valid <= ALL ? 18'd0 : ((valid & ~clear_rows) | set_rows);
    default_one <= ALL ? 18'h3ffff : (default_one & ~clear_rows);
  end
  always @(*) begin
    case(read_sel[2:0])
      0: BYTE=even_bits[7:0];
      1: BYTE=even_bits[15:8];
      2: BYTE={odd_bits[3:0],even_bits[19:16]};
      3: BYTE=odd_bits[11:4];
      4: BYTE=odd_bits[19:12];
      default: BYTE=0;
    endcase
  end
endmodule
// Three 512x32 RAMB16s rather than a power-of-two-rounded 2048x32 array.
// All banks read in parallel; the registered bank select belongs to the same
// request as their registered data. Read-during-write is READ_FIRST, as in
// the original simple dual-port log. The published and live banks differ.
module gbc_log_ram(input CLK, WE, input [10:0] WADDR,
                   input [31:0] DATA, input [10:0] RADDR, output [31:0] Q);
  wire [95:0] bank_q;
  reg [1:0] read_bank;
  genvar bank;
  generate
    for (bank=0; bank<3; bank=bank+1) begin : g_bank
      (* ram_style = "block" *) reg [31:0] words [0:511];
      reg [31:0] q;
      integer init_i;
      initial begin
        for (init_i=0; init_i<512; init_i=init_i+1) words[init_i]=0;
      end
      always @(posedge CLK) begin
        if (WE && WADDR[10:9] == bank) words[WADDR[8:0]] <= DATA;
        q <= words[RADDR[8:0]];
      end
      assign bank_q[32*bank +: 32] = q;
    end
  endgenerate
  always @(posedge CLK) read_bank <= RADDR[10:9];
  assign Q = read_bank == 0 ? bank_q[31:0]
           : read_bank == 1 ? bank_q[63:32]
           : read_bank == 2 ? bank_q[95:64] : 32'd0;
endmodule
