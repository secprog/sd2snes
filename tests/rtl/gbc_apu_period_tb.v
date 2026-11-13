`timescale 1ns/1ps
module gbc_apu_period_tb;
  reg [7:0] REG_NR10_r=0, REG_NR43_r=0;
  reg [10:0] apu_square1_sweep_freq_r=0;
  wire [15:0] sweep;
  wire [21:0] noise;
  reg [15:0] old_sweep, delta;
  reg [21:0] old_noise;
  integer control,frequency,checks=0;
  gbc_apu_period_actual dut(.*);
  initial begin
    for(control=0;control<256;control=control+1) begin
      REG_NR10_r=control; REG_NR43_r=control;
      old_noise=(control[2:0] ? control[2:0]*16 : 8) << control[7:4];
      for(frequency=0;frequency<2048;frequency=frequency+1) begin
        apu_square1_sweep_freq_r=frequency;
        delta=frequency >> control[2:0];
        old_sweep=control[3] ? frequency-delta : frequency+delta;
        #1;
        if(sweep !== old_sweep || noise !== old_noise)
          $fatal(1,"APU period mismatch NR10/NR43=%h frequency=%d sweep=%h/%h noise=%h/%h",
                 control,frequency,sweep,old_sweep,noise,old_noise);
        checks=checks+1;
      end
    end
    $display("PASS: all APU sweep and noise period inputs (%0d combinations)",checks);
    $finish;
  end
endmodule
