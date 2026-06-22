// Adpated from: data/benchmarks/sv-benchmarks/loop-lit/gr2006.c

module main #(parameter WIDTH = 1024) (input logic clk, input rst);

  logic signed [WIDTH-1:0] x, y;

  always_ff @(posedge clk) begin
    if (rst) begin
      x = 0;
      y = 0;
    end
    if (y >= 0) begin
        if (x < 50) begin
            y = y + 1;
        end
        else begin
            y = y - 1;
        end

        x = x + 1;
    end

  end

  property prop;
    @(posedge clk) disable iff (rst) x <= 101;
  endproperty



  endmodule
