`timescale 1ns / 1ps
module mult_tb;
    reg         clk = 1'b0;
    reg         rst = 1'b1;
    reg  [7:0]  a = 8'd0, b = 8'd0;
    wire [15:0] p;

    mult dut (.clk(clk), .rst(rst), .a(a), .b(b), .p(p));

    always #5 clk = ~clk;

    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, mult_tb);
        #12 rst = 1'b0;
        @(posedge clk); a = 8'd7;  b = 8'd6;
        @(posedge clk); a = 8'd15; b = 8'd15;
        @(posedge clk); a = 8'd200; b = 8'd3;
        @(posedge clk);
        #20 $finish;
    end
endmodule
