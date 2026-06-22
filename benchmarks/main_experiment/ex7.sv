// Adapted from: data/benchmarks/code2inv/120.c

module main(input logic clk, input rst);

  logic [7:0] i, sn;
  logic in;
  
  always_ff @(posedge clk) begin
    if (rst) begin
      i <= 1;
      sn <= 0;
      in <= 0;
    end
    else if (i <= 8) begin
      i  <= i + 1;
      sn <= sn + 1;
      in <= 1;
    end
    else begin
      in <= 0;
    end
  end


  property prop;
    @(posedge clk) disable iff (rst) (~in |-> (sn == 0 || sn == 8));
  endproperty


endmodule
