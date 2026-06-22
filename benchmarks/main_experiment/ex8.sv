module main(input logic clk, input logic [7:0] x_raw, input logic [7:0] y_raw, input rst);

  logic [7:0] i, j, x, y;
  
  always_ff @(posedge clk) begin
    if (rst) begin
      x = x_raw;
      i = x_raw;
      y = y_raw;
      j = y_raw;
    end
    if (x != 0) begin
      x = x - 1;
      y = y - 1;
    end
  end

  property prop;
    @(posedge clk) disable iff (rst) (x != 0 || y == 0 ||  i != j);
  endproperty
  
endmodule
