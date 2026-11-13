`timescale 1ns/1ps
// GBC cartridge audio: the existing GB APU CIC decimator, volume boost,
// saturation and I2S serializer. No MSU-1 PCM path or sample buffer.
`include "config.vh"
module dac(input clkin, reset, input [19:0] sgb_apu_dat,
           input sgb_apu_clk_edge, input [2:0] sgb_vol_select,
           output sdout, mclk_out, lrck_out, sclk_out);
integer i;
reg [10:0] cnt = 11'h100;
(* shreg_extract = "no" *) reg [2:0] mclk_sreg = 0, lrck_sreg = 0;
reg [1:0] sclk_sreg = 0;
wire mclk = cnt[2], lrck = cnt[8], sclk = cnt[3];
assign mclk_out = ~mclk_sreg[2];
assign lrck_out = lrck_sreg[2];
assign sclk_out = sclk_sreg[1];
wire lrck_rising = ({lrck_sreg[0],lrck} == 2'b01);
wire lrck_falling = ({lrck_sreg[0],lrck} == 2'b10);
wire sclk_falling = ({sclk_sreg[0],sclk} == 2'b10);
reg [15:0] smpshift;
reg sdout_reg;
assign sdout = sdout_reg;
reg [10:0] sgb_vol_reg = 11'h100;
always @(posedge clkin) begin
  cnt <= cnt + 1'b1;
  mclk_sreg <= {mclk_sreg[1:0],mclk};
  lrck_sreg <= {lrck_sreg[1:0],lrck};
  sclk_sreg <= {sclk_sreg[0],sclk};
end
parameter ST0_IDLE  = 10'b1000000000;
parameter ST1_COMB1 = 10'b0000000001;
parameter ST2_COMB2 = 10'b0000000010;
parameter ST3_COMB3 = 10'b0000000100;
parameter ST4_INT1  = 10'b0000010000;
parameter ST5_INT2  = 10'b0000100000;
parameter ST6_INT3  = 10'b0001000000;

/*
  Downsampler for SGB
  4 MHz input sample rate
  /64 downsample
  
  10b input.
*/

`define SGB_CIC_BITS (10+3*6) // 3 stages, /64 (2^6)

reg [(`SGB_CIC_BITS-1):0] sgb_ci[2:0][1:0], sgb_io[2:0][1:0], sgb_co[2:0][1:0];
reg [9:0] sgb_cicstate = 10'h200;
reg [9:0] sgb_cicstate_next = 10'h200;
reg [5:0] sgb_phasediv = 0;
reg       sgb_apu_clk_edge_r = 0;

wire [(`SGB_CIC_BITS-1):0] sgb_bufi[1:0];
assign sgb_bufi[1] = {{(`SGB_CIC_BITS-10){sgb_apu_dat[19]}}, sgb_apu_dat[19:10]};
assign sgb_bufi[0] = {{(`SGB_CIC_BITS-10){sgb_apu_dat[9]}}, sgb_apu_dat[9:0]};

always @(posedge clkin) begin
  sgb_apu_clk_edge_r <= sgb_apu_clk_edge;

  if(reset) begin
    sgb_cicstate <= ST0_IDLE;
    for (i = 0; i < 2; i = i + 1) begin
      {sgb_ci[2][i], sgb_ci[1][i], sgb_ci[0][i]} <= 0;
      {sgb_io[2][i], sgb_io[1][i], sgb_io[0][i]} <= 0;
      {sgb_co[2][i], sgb_co[1][i], sgb_co[0][i]} <= 0;
    end
    
    sgb_phasediv <= 0;
  end else if(sgb_apu_clk_edge_r) begin
    sgb_cicstate <= ST4_INT1;
    sgb_cicstate_next <= ~|sgb_phasediv ? ST1_COMB1 : ST0_IDLE;
    
    sgb_phasediv <= sgb_phasediv + 1;
  end else begin
    case(sgb_cicstate)
/****** COMB STAGES ******/
      ST1_COMB1: begin
        sgb_cicstate <= ST2_COMB2;
        for (i = 0; i < 2; i = i + 1) begin
          sgb_ci[0][i] <= sgb_io[2][i];
          sgb_co[0][i] <= sgb_io[2][i] - sgb_ci[0][i];
        end
      end
      ST2_COMB2: begin
        sgb_cicstate <= ST3_COMB3;
        for (i = 0; i < 2; i = i + 1) begin
          sgb_ci[1][i] <= sgb_co[0][i];
          sgb_co[1][i] <= sgb_co[0][i] - sgb_ci[1][i];
        end
      end
      ST3_COMB3: begin
        sgb_cicstate <= ST0_IDLE;
        for (i = 0; i < 2; i = i + 1) begin
          sgb_ci[2][i] <= sgb_co[1][i];
          sgb_co[2][i] <= sgb_co[1][i] - sgb_ci[2][i];
        end
      end
/****** INTEGRATOR STAGES ******/
      ST4_INT1: begin
        for (i = 0; i < 2; i = i + 1) begin
          sgb_io[0][i] <= sgb_bufi[i] + sgb_io[0][i];
        end
        sgb_cicstate <= ST5_INT2;
      end
      ST5_INT2: begin
        for (i = 0; i < 2; i = i + 1) begin
          sgb_io[1][i] <= sgb_io[0][i] + sgb_io[1][i];
        end
        sgb_cicstate <= ST6_INT3;
      end
      ST6_INT3: begin
        for (i = 0; i < 2; i = i + 1) begin
          sgb_io[2][i] <= sgb_io[1][i] + sgb_io[2][i];
        end
        sgb_cicstate <= sgb_cicstate_next;
      end
      default: begin
        sgb_cicstate <= ST0_IDLE;
      end
    endcase
  end
end

// assign SGB volume boost
always @(posedge clkin) begin
  case(sgb_vol_select)
    3'b000:  sgb_vol_reg = 11'h100;//11'h101;
    3'b001:  sgb_vol_reg = 11'h160;//11'h181;
    3'b010:  sgb_vol_reg = 11'h220;//11'h202;
    3'b011:  sgb_vol_reg = 11'h300;//11'h302;
    3'b100:  sgb_vol_reg = 11'h380;//11'h402;
    default: sgb_vol_reg = 11'h100;
  endcase
end

// TODO: arbitrary scaling which used to be in SGB APU
wire signed [15:0] sgb_data_ch = lrck ? {{(16+18-`SGB_CIC_BITS-4){sgb_co[2][1][(`SGB_CIC_BITS-1)]}},sgb_co[2][1][(`SGB_CIC_BITS-1):18],4'h0} : {{(16+18-`SGB_CIC_BITS-4){sgb_co[2][0][(`SGB_CIC_BITS-1)]}},sgb_co[2][0][(`SGB_CIC_BITS-1):18],4'h0};
//wire signed [15:0] sgb_data_ch = lrck ? {{2{sgb_apu_dat[19]}},sgb_apu_dat[19:10],4'h0} : {{2{sgb_apu_dat[9]}},sgb_apu_dat[9:0],4'h0};
wire signed [25:0] sgb_vol_sample;

assign sgb_vol_sample = sgb_data_ch * $signed({1'b0, sgb_vol_reg});
reg signed [25:0] sgb_vol_sample_r;
always @(posedge clkin) sgb_vol_sample_r <= sgb_vol_sample;
wire signed [25:0] vol_sample = sgb_vol_sample_r;
wire signed [15:0] vol_sample_sat = ((vol_sample[25:23] == 3'b000 || vol_sample[25:23] == 3'b111) ? vol_sample[23:8]
                      : vol_sample[25] ? 16'sh8000 : 16'sh7fff);
always @(posedge clkin) begin
  if (sclk_falling) begin
    sdout_reg <= smpshift[15];
    if (lrck_rising | lrck_falling) smpshift <= vol_sample_sat;
    else smpshift <= {smpshift[14:0], 1'b0};
  end
end
endmodule
