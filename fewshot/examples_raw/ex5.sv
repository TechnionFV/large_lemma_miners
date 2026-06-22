
module main(input logic clk, input logic signed [15:0] j, input rst);

    logic signed [15:0] i;
    logic signed [15:0] k;
    

  always_ff @(posedge clk) begin
    if (rst) begin
       i <= 0;
       k <= 0;
    end
    else if (i < 200) begin
        if (1 <= j && j < 200) begin
            i <= i + j;
            k <= k + 1;
        end
    end
  end

    property prop;
        @(posedge clk) disable iff (rst) (k <= 200);
    endproperty
    

endmodule
