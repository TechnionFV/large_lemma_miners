module main (input clk, input rst);

logic [10000:0] c;

always_ff @(posedge clk) begin
  if (rst)
    c <= '0;
  else if (c == 5000)
    c <= '0;
  else
    c <= c + 1;
end

property prop;
  @(posedge clk) disable iff (rst) c < 7800;
endproperty 


endmodule