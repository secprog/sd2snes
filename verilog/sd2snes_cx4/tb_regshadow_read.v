`timescale 1 ns / 1 ns
// Exercise the production main.v read-address path with its 80 MHz address held
// at a different bus transaction.  Only the 96 MHz snoop samples may address the
// shadow RAM.  Unrelated vendor modules are ignored by iverilog's -i option:
//   iverilog -g2012 -i -DMK3 -s tb_regshadow_read -o /tmp/rs-read \
//     tb_regshadow_read.v main.v regshadow.v && vvp /tmp/rs-read
// Also run with -DMK2 -DREGSHADOW_1DEEP for the MkII storage layout.
module tb_regshadow_read;
  reg clk96 = 0;
  always #5 clk96 = ~clk96;
  reg [23:0] bus_addr = 0;

  main dut(.SNES_ADDR_IN(bus_addr));

  task check_read(input [23:0] addr, input [7:0] expected);
    begin
      @(negedge clk96);
      bus_addr = addr;
      // Six address samples plus the synchronous RAM read must settle without
      // any edge on CLK2 or any change to its held address.
      repeat (9) @(negedge clk96);
      if (dut.regshadow_dout !== expected)
        $fatal(1, "%h: expected %h, received %h", addr, expected, dut.regshadow_dout);
    end
  endtask

  initial begin
    force dut.CLK96 = clk96;
    force dut.CLK2 = 1'b0;
    force dut.SNES_ADDR = 24'hF9071F;
    force dut.IS_PATCH = 1'b1;
    force dut.rs96_pawr_end_r = 1'b0;
    force dut.rs96_wr_end = 1'b0;

    // Distinct values expose selecting the wrong window, stride or byte.
    dut.snes_regshadow.mem[8'h00] = 8'h11;
`ifdef REGSHADOW_1DEEP
    dut.snes_regshadow.mem[8'h3F] = 8'h33;
    dut.snes_regshadow.mem[8'h40] = 8'h44;
    dut.snes_regshadow.mem[8'h5F] = 8'h55;
`else
    dut.snes_regshadow.mem[8'h01] = 8'h22;
    dut.snes_regshadow.mem[8'h7F] = 8'h33;
    dut.snes_regshadow.mem[8'h80] = 8'h44;
    dut.snes_regshadow.mem[8'h9F] = 8'h55;
`endif

    check_read(24'hF90500, 8'h11);
`ifdef REGSHADOW_1DEEP
    check_read(24'hF90501, 8'h11);
`else
    check_read(24'hF90501, 8'h22);
`endif
    check_read(24'hF9057F, 8'h33);
    check_read(24'hF90700, 8'h44);
    check_read(24'hF9071F, 8'h55);
    // Switch back across windows to check the address decode changes too.
    check_read(24'hF90500, 8'h11);
    $display("PASS: CX4 shadow reads use the 96 MHz address samples");
    $finish;
  end
endmodule
