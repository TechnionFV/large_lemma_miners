// Verilog model for the round-robin arbiter described in
// the CHARME99 paper by Katz, Grumberg, and Geist.

// Author: Fabio Somenzi <Fabio@Colorado.EDU>

module main(clk,rst, ir0,ir1,ack0,ack1);
    input  clk;
    input  rst;
    input  ir0, ir1;
    output ack0, ack1;

    reg    req0, req1, ack0, ack1, robin;

    task initialize;
    begin
	    ack0 = 0; ack1 = 0; robin = 0;
	    req0 = ir0; req1 = ir1;	// nondeterministic initial requests
    end
    endtask

    always @ (posedge clk) begin
    if (rst) initialize;
    else begin
        if (~req0)
          ack0 <= 0;		// no request -> no ack
        else if (~req1)
          ack0 <= 1;		// a single request
        else if (~ack0 & ~ack1)
          ack0 <= ~robin;	// simultaneous request assertions
        else
          ack0 <= ~ack0;		// both requesting: toggle ack
  

        if (~req1)
          ack1 <= 0;		// no request -> no ack
        else if (~req0)
          ack1 <= 1;		// a single request
        else if (~ack0 & ~ack1)
          ack1 <= robin;		// simultaneous request assertions
        else
          ack1 <= ~ack1;		// both requesting: toggle ack
        

        if (req0 & req1 & ~ack0 & ~ack1)
          robin <= ~robin;	// simultaneous request assertions
  

        // Latched inputs.

          req0 <= ir0;
          req1 <= ir1;
      end         // not rst
  end           // posedge clk

  // Mutual exclusion.


  property prop;
    @(posedge clk) disable iff (rst) (req1==1 && ack0==1 |-> ##1 ack1==1);
  endproperty


endmodule // rrobin
