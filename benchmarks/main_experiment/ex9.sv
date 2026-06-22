// Adapted from: data/benchmarks/code2inv/130.c 

module main(input logic clk, input rst, input logic signed [7:0] in_raw);

  logic signed [7:0] d1, d2, d3;
  logic signed [7:0] x1, x2, x3, in;

  always_ff @(posedge clk) begin
        if (rst) begin
            d1 <= 1;
            d2 <= 1;
            d3 <= 1;
            x1 <= 1;
            in <= in_raw;
            x2 <= in_raw;
        end
        else if (x1 > 0) begin
            if (x2 > 0 && x3 > 0) begin
              x1 <= x1 - d1;
              x2 <= x2 - d2;
              x3 <= x3 - d3;
            end
        end
  end

  
  property prop;
    @(posedge clk) disable iff (rst) (in <= 0 || x2 >= 0);
  endproperty
  

endmodule

