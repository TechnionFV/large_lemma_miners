//Adapted from dyn_partition

module main #(parameter WIDTH=64) (i, rst, clk);
localparam BOUND = 2**WIDTH;
input i,clk;
input rst;
reg [WIDTH-1:0]x,y;
reg b0, b1;



always @ (posedge clk) begin
if (rst) begin
    b0 <= 0;
    b1 <= 0;
    x <= 0;
    y <= 0;
end else begin
  b0 <= ~b1;
  b1 <= b0;
  if (b0 == b1 && x < BOUND -1) begin
     x <= x + 1;
   end
  else begin
     y <= y + 1;
  end	   	   
end
end

property prop;
 @(posedge clk) disable iff (rst) (y <= x);
endproperty



endmodule
