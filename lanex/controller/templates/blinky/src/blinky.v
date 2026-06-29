// Free-running counter; the MSB toggles slowly -> drives an LED.
module blinky #(
    parameter WIDTH = 24
) (
    input  wire clk,
    input  wire rst,
    output wire led
);
    reg [WIDTH-1:0] ctr;
    always @(posedge clk) begin
        if (rst)
            ctr <= {WIDTH{1'b0}};
        else
            ctr <= ctr + 1'b1;
    end
    assign led = ctr[WIDTH-1];
endmodule
