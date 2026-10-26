`timescale 1ns/1ps
module tb_sms_ce;
  reg CLK2 = 0;
  always #5 CLK2 = ~CLK2;
  `include "sms_ce.vh"

  // gcd(1251194, 2**25) = 2: this visits every reachable accumulator state.
  localparam integer PERIOD = 16777216;
  integer cycle;
  integer previous = -1;
  integer pulses = 0;
  integer gap;
  initial begin
    for (cycle = 1; cycle <= PERIOD; cycle = cycle + 1) begin
      @(negedge CLK2);
      if (sms_ce) begin
        if (previous >= 0) begin
          gap = cycle - previous;
          if (gap != 26 && gap != 27)
            $fatal(1, "Invalid SMS clock-enable spacing: %0d", gap);
        end
        previous = cycle;
        pulses = pulses + 1;
      end
    end
    if (pulses != 625597 || sms_ce_acc != 0)
      $fatal(1, "SMS CE period mismatch: pulses=%0d accumulator=%0d", pulses, sms_ce_acc);
    $display("SMS CE: all %0d reachable phases checked, %0d pulses, spacing 26/27 clocks", PERIOD, pulses);
    $finish;
  end
endmodule
