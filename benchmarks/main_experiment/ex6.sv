
module main (
  input logic clk,
  input y_raw,
  input z_raw,
  input rst
);

  logic [7:0] x, y, z;
  logic first;



  always_ff @(posedge clk) begin
    if (rst) begin
      first = 1;
      x = 0;
      y = y_raw;
      z = z_raw;
    end
    else begin
      first = 0;
      if (x < 5) begin
        x = x + 1;
        if (z <= y) begin
          y = z;
        end
      end
    end
  end


property prop;
    @(posedge clk) disable iff (rst) (first || (z >= y)); 
endproperty


endmodule
