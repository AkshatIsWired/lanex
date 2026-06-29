// Replace this with your design.
//
// The module name must match DESIGN_NAME in config.json (default: `top`),
// and the clock input must match CLOCK_PORT (default: `clk`). Add your RTL
// files under src/ — VERILOG_FILES is set to `dir::src/*.v`, so any *.v you
// drop in here is picked up automatically.
module top (
    input  wire       clk,
    input  wire       rst,
    input  wire [7:0] a,
    output reg  [7:0] y
);
    always @(posedge clk) begin
        if (rst)
            y <= 8'b0;
        else
            y <= a;
    end
endmodule
