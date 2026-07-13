`timescale 1ns/1ns
module tb_counter;
  reg clk = 1'b0;
  reg rst = 1'b1;
  wire [3:0] q;
  counter dut(.clk(clk), .rst(rst), .q(q));
  always #5 clk = ~clk;
  initial begin
    $dumpfile("dump.vcd");
    $dumpvars(0, tb_counter);
    #12 rst = 1'b0;
    #88 $finish;
  end
endmodule
