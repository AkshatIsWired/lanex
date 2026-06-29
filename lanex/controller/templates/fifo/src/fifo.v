// Synchronous FIFO: single clock, registered output, full/empty flags.
module fifo #(
    parameter WIDTH = 8,
    parameter DEPTH = 16,
    parameter AW    = 4   // ceil(log2(DEPTH))
) (
    input  wire             clk,
    input  wire             rst,
    input  wire             wr_en,
    input  wire             rd_en,
    input  wire [WIDTH-1:0] din,
    output reg  [WIDTH-1:0] dout,
    output wire             full,
    output wire             empty
);
    reg [WIDTH-1:0] mem [0:DEPTH-1];
    reg [AW:0]      count;
    reg [AW-1:0]    wptr, rptr;

    assign full  = (count == DEPTH[AW:0]);
    assign empty = (count == {(AW+1){1'b0}});

    wire do_wr = wr_en && !full;
    wire do_rd = rd_en && !empty;

    always @(posedge clk) begin
        if (rst) begin
            wptr  <= {AW{1'b0}};
            rptr  <= {AW{1'b0}};
            count <= {(AW+1){1'b0}};
            dout  <= {WIDTH{1'b0}};
        end else begin
            if (do_wr) begin
                mem[wptr] <= din;
                wptr      <= wptr + 1'b1;
            end
            if (do_rd) begin
                dout <= mem[rptr];
                rptr <= rptr + 1'b1;
            end
            case ({do_wr, do_rd})
                2'b10:   count <= count + 1'b1;
                2'b01:   count <= count - 1'b1;
                default: count <= count;
            endcase
        end
    end
endmodule
