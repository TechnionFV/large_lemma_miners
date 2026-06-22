
module main (clk, rst);
input clk;
input rst;
reg [2500:0] a,b;	
	

always @ (posedge clk) begin
	if (rst) begin
		a <= 1;
		b <= 0;
	end
	else begin
	    if (a<100) begin 
	       a<=b+a;
	    end

	   b <=a;
        end
end


property prop;
 @(posedge clk) disable iff (rst) a < 200;
endproperty


endmodule

