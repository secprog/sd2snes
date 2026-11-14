`timescale 1ns/1ps
// The unchanged SGB DAC is the reference, with its PCM input forced to zero.
// Compare the complete GB filter/volume/serializer output, not just liveness.
module gbc_audio_tb;
  reg clk=0;
  always #5 clk=~clk;
  reg reset=1, ce=0;
  reg [19:0] apu=0;
  reg [2:0] boost=0;
  wire sd,mc,lr,sc,ref_sd,ref_mc,ref_lr,ref_sc;
  dac dut(.clkin(clk),.reset(reset),.sgb_apu_dat(apu),.sgb_apu_clk_edge(ce),
    .sgb_vol_select(boost),.sdout(sd),.mclk_out(mc),.lrck_out(lr),.sclk_out(sc));
  dac_ref reference(.clkin(clk),.sysclk(clk),.we(1'b1),.pgm_address(11'd0),
    .pgm_data(8'd0),.volume(8'd0),.sgb_apu_dat(apu),.sgb_apu_clk_edge(ce),
    .vol_latch(1'b0),.vol_select(3'd0),.sgb_vol_select(boost),
    .dac_address_ext(9'd0),.play(1'b0),.reset(reset),.palmode(1'b0),
    .sdout(ref_sd),.mclk_out(ref_mc),.lrck_out(ref_lr),.sclk_out(ref_sc));
  reg [19:0] random_state=20'habcde;
  reg [27:0] expected_stage;
  integer n,b,ones=0,channel,stage,until_ce=0,warmup=1024;
  always @(negedge clk) begin
    // Let the driver change APU data before checking combinational operands.
    #1;
    if(!reset) begin
      for(channel=0;channel<2;channel=channel+1) begin
        if(dut.sgb_co[2][channel] !== reference.sgb_co[2][channel])
          $fatal(1,"full-precision CIC output differs channel=%0d",channel);
        if(dut.sgb_cicstate == dut.ST0_IDLE)
          for(stage=0;stage<3;stage=stage+1)
            if(dut.sgb_io[stage][channel] !== reference.sgb_io[stage][channel]
               || dut.sgb_ci[stage][channel] !== reference.sgb_ci[stage][channel])
              $fatal(1,"CIC stage state differs after complete rotation");
        case(dut.sgb_cicstate)
          dut.ST4_INT1: expected_stage=reference.sgb_io[0][channel]+reference.sgb_bufi[channel];
          dut.ST5_INT2: expected_stage=reference.sgb_io[1][channel]+reference.sgb_io[0][channel];
          dut.ST6_INT3: expected_stage=reference.sgb_io[2][channel]+reference.sgb_io[1][channel];
          dut.ST1_COMB1: expected_stage=reference.sgb_io[2][channel]-reference.sgb_ci[0][channel];
          dut.ST2_COMB2: expected_stage=reference.sgb_co[0][channel]-reference.sgb_ci[1][channel];
          dut.ST3_COMB3: expected_stage=reference.sgb_co[1][channel]-reference.sgb_ci[2][channel];
          default: expected_stage=dut.sgb_filter_result[channel];
        endcase
        if(dut.sgb_filter_result[channel] !== expected_stage)
          $fatal(1,"shared CIC stage differs state=%h channel=%0d",dut.sgb_cicstate,channel);
      end
    end
  end
  initial begin
    repeat(20) @(negedge clk);
    reset=0;
    for(b=0;b<8;b=b+1) begin
      boost=b;
      for(n=0;n<40000;n=n+1) begin
        @(negedge clk);
        ce=(n%20==0);
        if(ce) begin
          random_state={random_state[18:0],random_state[19]^random_state[16]};
          apu=random_state;
        end
        if(n>1024) begin
          if({sd,mc,lr,sc}!=={ref_sd,ref_mc,ref_lr,ref_sc})
            $fatal(1,"GB audio differs after PCM removal boost=%d cycle=%d",b,n);
          if(sd) ones=ones+1;
        end
      end
    end
    // Vary input data every clock, not just CE, and include the minimum
    // supported 7-clock interval (production CE1 is >=19). Exercise resets
    // at unrelated serializer/filter phases and all volume settings.
    for(n=0;n<200000;n=n+1) begin
      @(negedge clk);
      random_state={random_state[18:0],random_state[19]^random_state[16]};
      apu=random_state;
      boost=(n/2000)%8;
      reset=(n%4093==0);
      ce=(until_ce==0);
      if(ce) until_ce=6+(random_state%34);
      else until_ce=until_ce-1;
      if(reset) warmup=1024;
      else if(warmup>0) warmup=warmup-1;
      else if({sd,mc,lr,sc}!=={ref_sd,ref_mc,ref_lr,ref_sc})
        $fatal(1,"GB audio differs with jitter/reset cycle=%d",n);
    end
    if(ones==0) $fatal(1,"APU output is silent");
    $display("PASS: GB APU filter, all volume settings and I2S equal the SGB reference (%0d high bits)",ones);
    $finish;
  end
endmodule
module dac_buf(input clock,wren,input [10:0] wraddress,input [7:0] data,
               input [8:0] rdaddress,output [31:0] q);
  assign q=32'd0;
endmodule
