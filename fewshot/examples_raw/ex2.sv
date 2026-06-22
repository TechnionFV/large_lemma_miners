module main(input logic clk, input rst);

  logic [7:0] x, y, z, k;


  always_ff @(posedge clk) begin
    if (rst) begin
      x = 0;
      y = 0;
      z = 0;
      k = 0;
    end
    else if (x < 2**6) begin
        if (k % 3 == 0) begin
            x = x + 1;
        end
        y = y + 1;
        z = z + 1;
        k = x + y + z;
    end
  end


  property prop;
   @(posedge clk) disable iff (rst) (x == y && y == z);
  endproperty
  
  
endmodule
