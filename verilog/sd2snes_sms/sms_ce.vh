// Approximately 3.58 MHz from CLK2 = 96 MHz, retaining the existing fractional
// increment. Successive enables are 26 or
// 27 clocks apart; main.sdc qualifies internal TV80 paths by this enable.
reg [24:0] sms_ce_acc = 25'd0;
(* preserve *) reg sms_ce = 1'b0;
always @(posedge CLK2) begin
  {sms_ce, sms_ce_acc} <= {1'b0, sms_ce_acc} + 26'd1251194;
end
