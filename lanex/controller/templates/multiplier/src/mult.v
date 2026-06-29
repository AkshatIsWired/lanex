// NxN registered multiplier: inputs and product are registered.
module mult #(
    parameter W = 8
) (
    input  wire           clk,
    input  wire           rst,
    input  wire [W-1:0]   a,
    input  wire [W-1:0]   b,
    output reg  [2*W-1:0] p
);
    always @(posedge clk) begin
        if (rst)
            p <= {(2*W){1'b0}};
        else
            p <= a * b;
    end
endmodule
