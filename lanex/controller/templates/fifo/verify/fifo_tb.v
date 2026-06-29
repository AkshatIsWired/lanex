`timescale 1ns / 1ps
module fifo_tb;
    reg        clk = 1'b0;
    reg        rst = 1'b1;
    reg        wr_en = 1'b0, rd_en = 1'b0;
    reg  [7:0] din = 8'h00;
    wire [7:0] dout;
    wire       full, empty;

    fifo dut (.clk(clk), .rst(rst), .wr_en(wr_en), .rd_en(rd_en),
              .din(din), .dout(dout), .full(full), .empty(empty));

    always #6 clk = ~clk;

    integer i;
    initial begin
        $dumpfile("dump.vcd");
        $dumpvars(0, fifo_tb);
        #15 rst = 1'b0;
        // Push 8 values.
        for (i = 0; i < 8; i = i + 1) begin
            @(posedge clk); din = i[7:0]; wr_en = 1'b1;
        end
        @(posedge clk); wr_en = 1'b0;
        // Pop them back.
        for (i = 0; i < 8; i = i + 1) begin
            @(posedge clk); rd_en = 1'b1;
        end
        @(posedge clk); rd_en = 1'b0;
        #20 $finish;
    end
endmodule
