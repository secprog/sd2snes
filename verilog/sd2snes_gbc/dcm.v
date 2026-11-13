`timescale 1ns/1ps
// Same 24 MHz -> 84 MHz Spartan-3 clock configuration as the SGB core.
// Kept in this project so its include search cannot pick the SGB config.vh.
module my_dcm(input CLKIN, RST, output CLKFX, LOCKED);
  DCM #(
    .SIM_MODE("SAFE"), .CLKDV_DIVIDE(2.0),
    .CLKFX_DIVIDE(2), .CLKFX_MULTIPLY(7),
    .CLKIN_DIVIDE_BY_2("FALSE"), .CLKIN_PERIOD(41.667),
    .CLKOUT_PHASE_SHIFT("NONE"), .CLK_FEEDBACK("NONE"),
    .DESKEW_ADJUST("SYSTEM_SYNCHRONOUS"),
    .DFS_FREQUENCY_MODE("LOW"), .DLL_FREQUENCY_MODE("LOW"),
    .DUTY_CYCLE_CORRECTION("TRUE"), .FACTORY_JF(16'hffff),
    .PHASE_SHIFT(0), .STARTUP_WAIT("TRUE")
  ) dcm(.CLKIN(CLKIN), .RST(RST), .CLKFX(CLKFX), .LOCKED(LOCKED),
        .CLKFB(1'b0), .PSCLK(1'b0), .PSEN(1'b0), .PSINCDEC(1'b0));
endmodule
