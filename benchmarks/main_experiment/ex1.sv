module ex1(input logic clk, input rst);

logic [31:0] a;
logic [31:0] b;
logic [31:0] c;


always_ff @(posedge clk) begin
    if (rst) begin
        a <= 1;
        b <= 2;
        c <= 3;
    end
    else begin
        a <= b;
        b <= c;
        c <= a;
    end
end

property prop;
    @(posedge clk) disable iff (rst) (a != b); 
endproperty


endmodule
