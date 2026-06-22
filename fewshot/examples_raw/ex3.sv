
module main(input logic clk, input rst);

  logic signed [10:0] x, y, flag;
  
  
  always_ff @(posedge clk) begin
    if (rst) begin
      x = 0;
      y = 0;
      flag = 0;
    end
    else if (flag < 1) begin
      if (y < 0)
        flag = 1;

      if (flag < 1)
        x = x + 1;

      if (x < 50)
        y = y + 1;
      else
        y = y - 1;
    end
  end

  property prop;
   @(posedge clk) disable iff (rst) (flag < 1 || (y == -2 && x == 99));
  endproperty


endmodule
