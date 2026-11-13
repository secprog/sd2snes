`timescale 1ns/1ps
// Small memories belong in LUT RAM on Mk.II. Keeping the 128-byte HRAM and
// 256-byte OAM in separate RAMB16s would waste nearly two whole blocks.
// Port B is read-only in this build: SGB_MCU_ACCESS is disabled, while the
// bridge still reads OAM snapshots through it. Both clocks are the same CLK.
module gbc_small_ram #(parameter ABITS=8)(
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
    doutb<=ram[addrb];
  end
  // synthesis translate_off
  always @(posedge clka) if(web) $fatal(1,"Mk.II LUT RAM port B is read-only");
  // synthesis translate_on
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
  reg [6:0] read_sel;
  always @(BIDX) begin
    case (BIDX)
       0: read_sel={4'd0,3'd0};  1: read_sel={4'd0,3'd1};
       2: read_sel={4'd0,3'd2};  3: read_sel={4'd0,3'd3};
       4: read_sel={4'd0,3'd4};  5: read_sel={4'd1,3'd0};
       6: read_sel={4'd1,3'd1};  7: read_sel={4'd1,3'd2};
       8: read_sel={4'd1,3'd3};  9: read_sel={4'd1,3'd4};
      10: read_sel={4'd2,3'd0}; 11: read_sel={4'd2,3'd1};
      12: read_sel={4'd2,3'd2}; 13: read_sel={4'd2,3'd3};
      14: read_sel={4'd2,3'd4}; 15: read_sel={4'd3,3'd0};
      16: read_sel={4'd3,3'd1}; 17: read_sel={4'd3,3'd2};
      18: read_sel={4'd3,3'd3}; 19: read_sel={4'd3,3'd4};
      20: read_sel={4'd4,3'd0}; 21: read_sel={4'd4,3'd1};
      22: read_sel={4'd4,3'd2}; 23: read_sel={4'd4,3'd3};
      24: read_sel={4'd4,3'd4}; 25: read_sel={4'd5,3'd0};
      26: read_sel={4'd5,3'd1}; 27: read_sel={4'd5,3'd2};
      28: read_sel={4'd5,3'd3}; 29: read_sel={4'd5,3'd4};
      30: read_sel={4'd6,3'd0}; 31: read_sel={4'd6,3'd1};
      32: read_sel={4'd6,3'd2}; 33: read_sel={4'd6,3'd3};
      34: read_sel={4'd6,3'd4}; 35: read_sel={4'd7,3'd0};
      36: read_sel={4'd7,3'd1}; 37: read_sel={4'd7,3'd2};
      38: read_sel={4'd7,3'd3}; 39: read_sel={4'd7,3'd4};
      40: read_sel={4'd8,3'd0}; 41: read_sel={4'd8,3'd1};
      42: read_sel={4'd8,3'd2}; 43: read_sel={4'd8,3'd3};
      44: read_sel={4'd8,3'd4};
      default: read_sel={4'd0,3'd7};
    endcase
  end
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
