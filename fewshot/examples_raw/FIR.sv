module Fir3Tap (
  input logic clk,
  input logic rstN,
  input logic [700:0] x,
  output logic [700:0] y
);

  logic [700:0] h[2:0] = '{701'h1, 701'h2, 701'h1}; // 1 2 1
  logic [700:0] delay1, delay2;

  assign y = h[2]*x + h[1] * delay1 + h[0] * delay2;
  
  always_ff @(posedge clk or negedge rstN) begin
    if (!rstN) begin
      delay1 <= 0;
      delay2 <= 0;
    end
    else begin
      delay1 <= x;
      delay2 <= delay1;
    end
  end
 
 property prop;
    @(posedge clk) disable iff (!rstN) ($stable(x) [*3] |-> y == x * 701'd4);
 endproperty
  

endmodule


