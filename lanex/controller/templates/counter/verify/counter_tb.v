// Self-checking-ish testbench for `counter`. Dumps a VCD the GUI waveform
// viewer can open (Phase 3 simulation). Verilator runs this with --binary.
`timescale 1ns / 1ps
module counter_tb;
    reg         clk = 1'b0;
    reg         rst = 1'b1;
    reg         en  = 1'b0;
    wire [7:0]  count;

    counter dut (.clk(clk), .rst(rst), .en(en), .count(count));

    always #5 clk = ~clk;

    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, counter_tb);
        #12 rst = 1'b0;
        en = 1'b1;
        #200;
        $display("final count = %0d", count);
        $finish;
    end
endmodule
