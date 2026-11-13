`timescale 1ns/1ps
module gbc_alu_tb;
  reg CLK=0;
  always #5 CLK=~CLK;
  reg [23:0] IFD_EXE_op=0;
  reg [15:0] exe_dst_r=0;
  reg [7:0] exe_src_alu_r=0, exe_cc_r=0;
  wire [7:0] result,compare_result,flags;
  wire c3,c7;
  gbc_alu_actual dut(.*);
  reg [7:0] old_result=0,old_cp=0,old_flags=0;
  reg old_c3=0,old_c7=0;
  integer pair,op,carry,cycle,checks=0;
  // Original separate SUB/CP datapaths, scored at every clock rather than
  // only after the nibble carry and flag pipelines have settled.
  always @(posedge CLK) begin
    case(IFD_EXE_op[5:3])
      0,1,2,3: begin
        {old_c3,old_result[3:0]} <= exe_dst_r[3:0]
          + (exe_src_alu_r[3:0] ^ {4{IFD_EXE_op[4]}})
          + ((IFD_EXE_op[3] & exe_cc_r[4]) ^ IFD_EXE_op[4]);
        {old_c7,old_result[7:4]} <= exe_dst_r[7:4]
          + (exe_src_alu_r[7:4] ^ {4{IFD_EXE_op[4]}}) + old_c3;
        old_flags <= {~|old_result,IFD_EXE_op[4],
          IFD_EXE_op[4]^old_c3,IFD_EXE_op[4]^old_c7,exe_cc_r[3:0]};
      end
      4: begin
        old_result <= exe_dst_r[7:0] & exe_src_alu_r;
        old_flags <= {~|old_result,3'b010,exe_cc_r[3:0]};
      end
      5: begin
        old_result <= exe_dst_r[7:0] ^ exe_src_alu_r;
        old_flags <= {~|old_result,3'b000,exe_cc_r[3:0]};
      end
      6: begin
        old_result <= exe_dst_r[7:0] | exe_src_alu_r;
        old_flags <= {~|old_result,3'b000,exe_cc_r[3:0]};
      end
      7: begin
        {old_c3,old_cp[3:0]} <= exe_dst_r[3:0] + (4'hf ^ exe_src_alu_r[3:0]) + 1'b1;
        {old_c7,old_cp[7:4]} <= exe_dst_r[7:4] + (4'hf ^ exe_src_alu_r[7:4]) + old_c3;
        old_flags <= {~|old_cp,1'b1,~old_c3,~old_c7,exe_cc_r[3:0]};
      end
    endcase
    #1;
    if({result,compare_result,flags,c3,c7} !== {old_result,old_cp,old_flags,old_c3,old_c7})
      $fatal(1,"ALU mismatch op=%h dst=%h src=%h flags=%h",IFD_EXE_op,exe_dst_r,exe_src_alu_r,exe_cc_r);
    checks=checks+1;
  end
  initial begin
    for(pair=0;pair<65536;pair=pair+1)
      for(op=0;op<8;op=op+1)
        for(carry=0;carry<2;carry=carry+1) begin
          @(negedge CLK);
          IFD_EXE_op=8'h80+(op<<3)+(pair%8);
          exe_dst_r=pair>>8; exe_src_alu_r=pair;
          exe_cc_r={3'b101,carry[0],pair[3:0]};
          // Include unstable pipeline clocks and the fully settled flags.
          for(cycle=0;cycle<3;cycle=cycle+1) @(posedge CLK);
        end
    #2;
    $display("PASS: shared CPU ALU matches every pipeline clock (%0d checks)",checks);
    $finish;
  end
endmodule
