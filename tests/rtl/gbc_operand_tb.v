`timescale 1ns/1ps
module gbc_operand_tb;
  reg CLK=0;
  reg [7:0] A_r=0,F_r=0,B_r=0,C_r=0,D_r=0,E_r=0,H_r=0,L_r=0;
  reg [15:0] SP_r=0, IFD_EXE_pc_next=0, IFD_EXE_decode=0;
  reg [23:0] IFD_EXE_op=0;
  wire [15:0] src,dst;
  reg [15:0] old_src,old_dst;
  integer i,j,k,bit_index,checks=0,seed=32'h438d215;
  gbc_operand_actual dut(.*);
  // The original flat operand table, independent of the pair mux encoding.
  function [15:0] read_original(input [3:0] sel, input [15:0] previous);
    begin
      case(sel)
        0: read_original=previous;
        1: read_original=IFD_EXE_pc_next;
        2: read_original={{8{IFD_EXE_op[15]}},IFD_EXE_op[15:8]};
        3: read_original=IFD_EXE_op[23:8];
        4: read_original={B_r,C_r};
        5: read_original={D_r,E_r};
        6: read_original=SP_r;
        7: read_original={A_r,F_r};
        8: read_original={8'd0,B_r};
        9: read_original={8'd0,C_r};
        10: read_original={8'd0,D_r};
        11: read_original={8'd0,E_r};
        12: read_original={8'd0,H_r};
        13: read_original={8'd0,L_r};
        14: read_original={H_r,L_r};
        15: read_original={8'd0,A_r};
      endcase
    end
  endfunction
  task tick;
    begin
      #2; old_src=read_original(IFD_EXE_decode[7:4],old_src);
      old_dst=read_original(IFD_EXE_decode[11:8],old_dst);
      CLK=1; #1;
      if({src,dst} !== {old_src,old_dst})
        $fatal(1,"operand read mismatch selectors=%h src=%h/%h dst=%h/%h",
               IFD_EXE_decode[11:4],src,old_src,dst,old_dst);
      CLK=0; checks=checks+1;
    end
  endtask
  initial begin
    // All selector pairs, basis bits through every source, then arbitrary
    // transitions including selector zero retaining the preceding operand.
    for(i=0;i<112;i=i+1) begin
      {IFD_EXE_pc_next,IFD_EXE_op[23:8],SP_r,A_r,F_r,B_r,C_r,D_r,E_r,H_r,L_r}=112'd1<<i;
      for(j=0;j<16;j=j+1) for(k=0;k<16;k=k+1) begin
        IFD_EXE_decode[11:4]={j[3:0],k[3:0]}; tick;
      end
    end
    for(i=0;i<10000;i=i+1) begin
      {A_r,F_r,B_r,C_r}=$random(seed);
      {D_r,E_r,H_r,L_r}=$random(seed);
      {SP_r,IFD_EXE_pc_next}=$random(seed);
      IFD_EXE_op=$random(seed); IFD_EXE_decode=$random(seed); tick;
    end
    $display("PASS: production CPU operand reads (%0d cycles, all selector pairs and source basis bits)",checks);
    $finish;
  end
endmodule
