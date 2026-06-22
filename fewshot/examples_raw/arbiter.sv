module Arbiter #(
  parameter NumRequests = 4
) (
  input logic [NumRequests-1:0] request_raw,
  input clk,
  input rst,
  output logic [NumRequests-1:0] grant
);
  reg granted;
  logic [NumRequests-1:0] request;


  always_ff @(posedge clk) begin
    if (rst) begin
        request = '0;
        grant = '0;
    end
    else begin
      request = request_raw;
      grant = '0;
      granted = 0;
      int i;
      for (i = 0; i < NumRequests; i++) begin
        if (!granted && request[i]) begin
          grant[i] = 1;
          granted = 1;
        end
      end
      end
  end

  wire prop_wire = (grant <= request);

  property prop;
   @(posedge clk)  disable iff (rst) prop_wire;
  endproperty
 

endmodule


