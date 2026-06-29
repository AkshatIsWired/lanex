`timescale 1ns / 1ps
module blinky_tb;
    reg  clk = 1'b0;
    reg  rst = 1'b1;
    wire led;

    // Small WIDTH so the LED toggles quickly in simulation.
    blinky #(.WIDTH(4)) dut (.clk(clk), .rst(rst), .led(led));

    always #5 clk = ~clk;

    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, blinky_tb);
        #12 rst = 1'b0;
        #400;
        $finish;
    end
endmodule
