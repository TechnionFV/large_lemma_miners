module main #(parameter WIDTH=32) (input logic clk, input rst);

  logic [WIDTH-1:0] x, y;
  wire [WIDTH-1:0] n = 100;


  always_ff @(posedge clk) begin  
    if (rst) begin
      x <= n;
      y <= 0;
    end 
    else if (x > 0) begin
      x <= x - 1;
      y <= y + 1;
    end
  end

  property prop;
      @(posedge clk) disable iff (rst) (x > 0 || y == n);
  endproperty



endmodule
