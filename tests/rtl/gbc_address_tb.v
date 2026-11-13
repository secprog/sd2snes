`timescale 1ns/1ps
module gbc_address_tb;
  reg CLK=0;
  reg [7:0] A_r=0,F_r=0,B_r=0,C_r=0,D_r=0,E_r=0,H_r=0,L_r=0;
  reg [15:0] SP_r=0,IFD_EXE_pc_next=0,dec_data=0,exe_mem_addr_mod_r=0;
  reg [23:0] IFD_EXE_op=0;
  reg [2:0] exe_stage=0;
  reg ifd_int_r=0,ifd_cb_r=0;
  reg [7:0] ifd_data_r=0;
  wire [15:0] src,dst,decoded,address;
  wire wr;
  reg [15:0] decoder[0:255];
  reg [15:0] expected,chosen;
  reg old_wr;
  integer op,stage,mode,sample,addr_i,checks=0,los_checks=0,seed=32'h647c120;
  gbc_address_actual dut(.*);

  task tick;
    begin #1; CLK=1; #1; CLK=0; end
  endtask
  task check;
    begin
      #1;
      old_wr = decoded[3:0]==8 || decoded[3:0]==14
            || (exe_stage[0] && (decoded[3:0]==10 || decoded[3:0]==11 || decoded[3:0]==13));
      chosen = old_wr ? dst : src;
      if(old_wr ? (decoded[11:8]==2 || decoded[11:8]==9)
                : (decoded[7:4]==2 || decoded[7:4]==9)) chosen[15:8]=8'hff;
      expected=chosen+exe_mem_addr_mod_r;
      if(wr !== old_wr || address !== expected)
        $fatal(1,"address changed decode=%h stage=%d addr=%h expected=%h",decoded,exe_stage,address,expected);
      if(decoded[3:0]==10 || decoded[3:0]==11 || decoded[3:0]==13) begin
        if(decoded[11:4] !== 8'hee || src !== dst)
          $fatal(1,"memory read/modify/write operands are not identical HL latches");
        los_checks=los_checks+1;
      end
      checks=checks+1;
    end
  endtask
  task random_operands;
    begin
      {A_r,F_r,B_r,C_r}=$random(seed);
      {D_r,E_r,H_r,L_r}=$random(seed);
      {SP_r,IFD_EXE_pc_next}=$random(seed);
      IFD_EXE_op=$random(seed);
      exe_mem_addr_mod_r=$random(seed);
    end
  endtask
  initial begin
    $readmemh("decode_reference.hex",decoder);
    // Production decoder ROM, all CB overrides and interrupt dispatch.
    // Decode becomes visible first; operands follow one clock later, exactly
    // the existing delay before ST_MCT_DEC consumes the address.
    for(mode=0;mode<3;mode=mode+1) begin
      ifd_cb_r=mode==1; ifd_int_r=mode==2;
      for(op=0;op<256;op=op+1) begin
        dec_data=decoder[op]; ifd_data_r=op;
        for(sample=0;sample<16;sample=sample+1) begin
          random_operands; tick; tick;
          for(stage=0;stage<8;stage=stage+1) begin exe_stage=stage; check; end
        end
      end
    end
    // Every possible HL address and every stage for INC, DEC and memory CB.
    // Vary the CB instruction too, including BIT's skipped write stage.
    ifd_int_r=0;
    for(mode=0;mode<3;mode=mode+1) begin
      ifd_cb_r=mode==2; dec_data=decoder[mode==0 ? 8'h34 : 8'h35];
      for(addr_i=0;addr_i<65536;addr_i=addr_i+1) begin
        {H_r,L_r}=addr_i; ifd_data_r={addr_i[4:0],3'b110};
        exe_mem_addr_mod_r=addr_i[1:0]-16'd2;
        tick; tick;
        for(stage=0;stage<8;stage=stage+1) begin exe_stage=stage; check; end
      end
    end
    $display("PASS: CPU address selection matches the original in %0d checks (%0d read/modify/write)",checks,los_checks);
    $finish;
  end
endmodule
