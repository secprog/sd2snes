`timescale 1ns / 1ps
// Mk.II C6 storage. The complete, UNCHANGED BBGGGRRR image lives in the
// cartridge SRAM at $70000..$78fff (18 rows, 2048 bytes/row). Each row has
// 20 tiles of 64 chunky bytes; the remaining 12 tile slots are unused.
//
// A 16-word distributed FIFO absorbs the PPU's bursts. A word is committed
// only after all eight read/compare/write transactions complete. In particular
// the last-word response, rather than enqueueing it, freezes the row.
//
// $EF0008 prepares one FROZEN row. SRAM is read in the background and a single
// 2 KiB block RAM receives SNES planar bytes, including the existing 5:8
// stretch. The player waits for status $92 == row before starting DMA. A cache
// miss NEVER returns old pixels. ROW_DONE invalidates the cache before thaw.
// MEM_REQ is held, with address/data stable, until MEM_ACK; an arbiter may
// delay it arbitrarily. Reset cancels requests and invalidates all cache tags.
module c6_sram(
  input CLK, RST,
  input WR,
  input [4:0] WR_ROW, WR_COL,
  input [2:0] WR_LINE,
  input WR_LAST,
  input [63:0] WR_PIXELS,
  output reg COMMIT,
  output reg [4:0] COMMIT_ROW, COMMIT_COL,
  output reg COMMIT_LAST, COMMIT_DIFF,
  output reg OVERFLOW,

  input PREPARE,
  input [4:0] PREPARE_ROW,
  input STRETCH,
  input [17:0] FROZEN,
  input [17:0] INVALIDATE,
  input [15:0] VADDR,
  output [7:0] VIEW_BYTE,
  output [7:0] READY_ROW,

  output reg MEM_REQ, MEM_WR,
  output reg [18:0] MEM_ADDR,
  output reg [7:0] MEM_DATA,
  input MEM_ACK,
  input [7:0] MEM_Q
);
  // A dynamic 16-tap shift register uses one SRL16E LUT per payload bit,
  // whereas a dual-port 16-word RAM uses two. Only occupancy needs reset.
  // The oldest word is tap count-1; simultaneous push/pop keeps that tap.
  reg [4:0] fifo_count;
  wire empty = fifo_count == 0;
  wire full = fifo_count == 16;
  wire fifo_push = WR && !full && !RST;
  wire fifo_pop;
  wire [3:0] fifo_tap = fifo_count[3:0] - 1'b1;
  // {last, row, col, line, eight pixels}, oldest pixel in bits 63:56.
  wire [77:0] fifo_data = {WR_LAST,WR_ROW,WR_COL,WR_LINE,WR_PIXELS};
  wire [77:0] head;
  genvar fifo_bit;
  generate for (fifo_bit=0; fifo_bit<78; fifo_bit=fifo_bit+1) begin : g_fifo
    (* shreg_extract = "yes" *) reg [15:0] bits;
    always @(posedge CLK)
      if (fifo_push) bits <= {bits[14:0],fifo_data[fifo_bit]};
    assign head[fifo_bit] = bits[fifo_tap];
  end endgenerate
  always @(posedge CLK) begin
    if (RST) fifo_count <= 0;
    else case ({fifo_push,fifo_pop})
      2'b10: fifo_count <= fifo_count + 1'b1;
      2'b01: fifo_count <= fifo_count - 1'b1;
      default: ;
    endcase
  end
  reg [2:0] byte_index;
  // The FIFO retains its oldest word until the final store is acknowledged.
  // New pushes move both the shift register and its tap, preserving HEAD.
  // Read that word in place instead of copying and shifting another 64 bits.
  reg [7:0] write_pixel;
  always @(*) begin
    case(byte_index)
      0: write_pixel=head[63:56];
      1: write_pixel=head[55:48];
      2: write_pixel=head[47:40];
      3: write_pixel=head[39:32];
      4: write_pixel=head[31:24];
      5: write_pixel=head[23:16];
      6: write_pixel=head[15:8];
      default: write_pixel=head[7:0];
    endcase
  end
  reg different;

  reg cache_valid, cache_stretch, cache_active, cache_discard;
  reg [4:0] cache_row;
  reg prepare_pending;
  reg [4:0] request_row;
  reg request_stretch;
  reg [4:0] column;
  reg [2:0] line, pixel, plane;
  reg [63:0] pixels;
  reg cache_we;
  reg [10:0] cache_addr;
  reg [7:0] cache_data;
  wire [7:0] cache_q;
  // Source x for this output tile. Stretch is exactly [0,0,1,2,2,3,4,4].
  wire [7:0] start_x = cache_stretch
      ? ({1'b0,column,2'b00} + {3'b000,column}) : {column,3'b000};
  wire [7:0] source_x = start_x + {5'd0,pixel};
  wire [18:0] source_addr = {3'b111,cache_row,source_x[7:3],line,source_x[2:0]};
  wire invalidating = INVALIDATE[cache_row];
  assign READY_ROW = cache_valid && !invalidating && !OVERFLOW
                   ? {3'b000,cache_row} : 8'hff;
  reg view_ok;
  always @(posedge CLK)
    view_ok <= cache_valid && !invalidating && !OVERFLOW
            && VADDR[15:11] == cache_row
            && (cache_stretch || VADDR[10:6] < 20);
  assign VIEW_BYTE = view_ok ? cache_q : 8'h00;

  c6_row_cache cache(.CLK(CLK), .WE(cache_we), .WADDR(cache_addr),
                     .DATA(cache_data), .RADDR(VADDR[10:0]), .Q(cache_q));

  // Multiplying a pair of bytes by 2^(7-plane) puts the selected bits at
  // product[7] and product[15]. Four spare MULT18X18s replace eight variable
  // bit selectors, with no rounding, pixel loss, or extra pipeline cycle.
  wire [7:0] plane_scale = 8'h80 >> plane;
  wire [7:0] plane_bits;
  genvar pair;
  generate for(pair=0; pair<4; pair=pair+1) begin : g_planar_pair
    (* mult_style = "block" *) wire [22:0] product =
        pixels[pair*16 +: 16] * plane_scale;
    assign plane_bits[pair*2] = product[7];
    assign plane_bits[pair*2+1] = product[15];
  end endgenerate
  wire [7:0] planar_byte = cache_stretch
      ? {plane_bits[7],plane_bits[7],plane_bits[6],plane_bits[5],
         plane_bits[5],plane_bits[4],plane_bits[3],plane_bits[3]} : plane_bits;

  localparam IDLE=0, WRITE_READ=1, WRITE_STORE=2, CACHE_READ=3, CACHE_PLANES=4;
  reg [2:0] state;
  assign fifo_pop = state == WRITE_STORE && MEM_REQ && MEM_ACK && byte_index == 7;
  always @(posedge CLK) begin
    COMMIT <= 0;
    cache_we <= 0;
    if (RST) begin
      OVERFLOW <= 0;
      MEM_REQ <= 0; MEM_WR <= 0; MEM_ADDR <= 0; MEM_DATA <= 0;
      cache_valid <= 0; cache_row <= 0; cache_stretch <= 0;
      cache_active <= 0; cache_discard <= 0;
      prepare_pending <= 0; request_row <= 0; request_stretch <= 0;
      state <= IDLE; byte_index <= 0; different <= 0;
      column <= 0; line <= 0; pixel <= 0; plane <= 0; pixels <= 0;
      COMMIT_ROW <= 0; COMMIT_COL <= 0;
      COMMIT_LAST <= 0; COMMIT_DIFF <= 0;
    end else begin
      if (WR && full) OVERFLOW <= 1;
      if (invalidating || STRETCH != cache_stretch) begin
        cache_valid <= 0;
        cache_discard <= 1;
      end
      if (PREPARE && PREPARE_ROW < 18 && FROZEN[PREPARE_ROW]) begin
        if (!((cache_valid || (cache_active && !cache_discard))
            && cache_row == PREPARE_ROW && cache_stretch == STRETCH)) begin
          request_row <= PREPARE_ROW;
          request_stretch <= STRETCH;
          prepare_pending <= 1;
        end
      end
      case (state)
        IDLE: begin
          // Producer first. An idle PPU (HBlank/frozen row) lets prefetch run;
          // cache reads yield at each output tile, so neither side loses data.
          if (!empty) begin
            byte_index <= 0; different <= 0;
            MEM_ADDR <= {3'b111,head[76:64],3'b000};
            MEM_WR <= 0; MEM_REQ <= 1; state <= WRITE_READ;
          end else if (cache_active) state <= CACHE_READ;
          else if (prepare_pending) begin
            prepare_pending <= 0; cache_valid <= 0;
            cache_active <= 1; cache_discard <= 0;
            cache_row <= request_row; cache_stretch <= request_stretch;
            column <= 0; line <= 0; pixel <= 0; plane <= 0;
            state <= CACHE_READ;
          end
        end
        WRITE_READ: if (MEM_ACK) begin
          different <= different || MEM_Q != write_pixel;
          MEM_REQ <= 0; state <= WRITE_STORE;
        end
        WRITE_STORE: begin
          if (!MEM_REQ) begin
            MEM_WR <= 1; MEM_DATA <= write_pixel; MEM_REQ <= 1;
          end else if (MEM_ACK) begin
            MEM_REQ <= 0;
            if (byte_index == 7) begin
              COMMIT <= 1; COMMIT_ROW <= head[76:72];
              COMMIT_COL <= head[71:67]; COMMIT_LAST <= head[77];
              COMMIT_DIFF <= different;
              state <= IDLE;
            end else begin
              byte_index <= byte_index + 1'b1;
              // This arm runs only for bytes 0..6; the increment cannot
              // carry into the tile-line address.
              MEM_ADDR <= {MEM_ADDR[18:3],byte_index + 3'd1};
              MEM_WR <= 0; MEM_REQ <= 1; state <= WRITE_READ;
            end
          end
        end
        CACHE_READ: begin
          if (!MEM_REQ) begin
            MEM_ADDR <= source_addr; MEM_WR <= 0; MEM_REQ <= 1;
          end else if (MEM_ACK) begin
            MEM_REQ <= 0;
            // Fill the five/eight source bytes into the high end of pixels.
            case(pixel)
              0: pixels[63:56] <= MEM_Q;
              1: pixels[55:48] <= MEM_Q;
              2: pixels[47:40] <= MEM_Q;
              3: pixels[39:32] <= MEM_Q;
              4: pixels[31:24] <= MEM_Q;
              5: pixels[23:16] <= MEM_Q;
              6: pixels[15:8] <= MEM_Q;
              7: pixels[7:0] <= MEM_Q;
            endcase
            if (pixel == (cache_stretch ? 4 : 7)) begin
              pixel <= 0; plane <= 0; state <= CACHE_PLANES;
            end else pixel <= pixel + 1'b1;
          end
        end
        CACHE_PLANES: begin
          cache_we <= 1;
          cache_addr <= {column,plane[2:1],line,plane[0]};
          cache_data <= planar_byte;
          if (plane == 7) begin
            plane <= 0;
            if (line == 7 && column == (cache_stretch ? 31 : 19)) begin
              // Last write reaches the RAM on the following edge. Publication
              // also waits that edge (IDLE), never an uninitialised last byte.
              cache_active <= 0; state <= IDLE;
            end else begin
              if (line == 7) begin line <= 0; column <= column + 1'b1; end
              else line <= line + 1'b1;
              state <= IDLE;
            end
          end else plane <= plane + 1'b1;
        end
      endcase
      if (state == IDLE && cache_we && !cache_active && !prepare_pending)
        cache_valid <= FROZEN[cache_row] && !invalidating && !cache_discard
                     && STRETCH == cache_stretch;
    end
  end
endmodule

// One 2048x8 simple dual-port RAMB16. Registered read, no output register.
// Keep the portable model identical to the primitive's READ_FIRST timing.
module c6_row_cache(input CLK, WE, input [10:0] WADDR,
                    input [7:0] DATA, input [10:0] RADDR, output reg [7:0] Q);
  (* ram_style = "block" *) reg [7:0] ram [0:2047];
  always @(posedge CLK) begin
    if (WE) ram[WADDR] <= DATA;
    Q <= ram[RADDR];
  end
endmodule
