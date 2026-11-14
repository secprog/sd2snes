`timescale 1ns/1ps
module gbc_wave_ram_tb;
  reg CLK=0, reset=1, request=0, debug_write=0, enabled=1, active=0, sample_update=0;
  reg [7:0] address=0, data=0;
  reg [4:0] position=0;
  wire [7:0] cpu_q, apu_q;
  wire [3:0] sample;
  gbc_wave_actual dut(.CLK(CLK), .cpu_ireset_r(reset), .REG_req_val(request),
    .REG_req_dbg(debug_write), .REG_NR52_r({enabled,7'd0}),
    .apu_wave_enable_r(active), .REG_address(address), .REG_req_data(data),
    .apu_wave_pos_r(position), .apu_wave_sample_update_r(sample_update),
    .cpu_q(cpu_q), .apu_q(apu_q), .sample(sample));
  reg [7:0] reference [0:15];
  reg [3:0] expected_sample;
  integer i,j,value,control,seed=32'hc6498a3,checks=0;
  task restore_reference;
    begin
      reference[0]=8'h08; reference[1]=8'hf7; reference[2]=8'h04; reference[3]=8'hdf;
      reference[4]=8'h08; reference[5]=8'h66; reference[6]=8'h00; reference[7]=8'h7f;
      reference[8]=8'h00; reference[9]=8'h57; reference[10]=8'h02; reference[11]=8'hff;
      reference[12]=8'h08; reference[13]=8'hff; reference[14]=8'h00; reference[15]=8'h9f;
    end
  endtask
  task check_reads;
    begin
      #1;
      if(cpu_q !== reference[address[3:0]] || apu_q !== reference[position[4:1]])
        $fatal(1,"Wave RAM mismatch at CPU=%h APU=%h",address,position);
      checks=checks+1;
    end
  endtask
  task tick;
    begin
      // The APU sample sees the old byte when a write or reset shares its edge.
      if(sample_update) expected_sample=position[0]
          ? reference[position[4:1]][3:0] : reference[position[4:1]][7:4];
      if(reset) restore_reference;
      else if(request && enabled && (!active || debug_write)
              && address>=8'h30 && address<=8'h3f) reference[address[3:0]]=data;
      #2; CLK=1; #1;
      if(sample_update && sample !== expected_sample)
        $fatal(1,"Wave sample changed its read-before-write timing");
      check_reads;
      CLK=0;
    end
  endtask
  initial begin
    tick; reset=0;
    // All data at every address, with both nibbles and every read address.
    request=1;
    for(i=0;i<16;i=i+1) begin
      for(value=0;value<256;value=value+1) begin
        address=8'h30+i; data=value; position=i*2; sample_update=1; tick;
        for(j=0;j<32;j=j+1) begin position=j; check_reads; end
      end
    end
    // Exhaust the transaction gate, including writes blocked by APU/channel
    // state, unrelated addresses, reset priority, and immediate reset reads.
    for(control=0;control<32;control=control+1) begin
      {reset,enabled,active,debug_write,request}=control;
      for(i=0;i<256;i=i+1) begin
        address=i; data=~i; position=i; sample_update=1; tick;
      end
    end
    for(i=0;i<12000;i=i+1) begin
      reset=(i%137)==0; enabled=$random(seed); active=$random(seed);
      debug_write=$random(seed); request=$random(seed); address=$random(seed);
      data=$random(seed); position=$random(seed); sample_update=$random(seed); tick;
    end
    reset=1; request=1; tick; reset=0; request=0;
    for(i=0;i<16;i=i+1) begin address=i; position=i*2; check_reads; end
    $display("PASS: wave RAM reset bytes, transaction gate, asynchronous ports and sample collisions (%0d checks)",checks);
    $finish;
  end
endmodule
