
module DivideBy3 #(
    parameter int PARAM = 3,
    parameter int LOG_PARAM = 2
)(
  input  logic clk,
  input  logic rstN,
  output logic clkOut
);

  logic [LOG_PARAM-1:0] count;

  always_ff @(posedge clk or negedge rstN) begin
    if (!rstN) begin
      count  <= 0;
      clkOut <= 0;
    end
    else begin
      count <= count + 1;
      if (count == PARAM) begin
        count  <= 0;
        clkOut <= ~clkOut;
      end
    end
  end

property prop;
  @(posedge clk) disable iff (!rstN) (not ((clkOut == 1) [*(PARAM+2)])); 
endproperty 


endmodule