module fifo #(
   parameter  DEPTH = 16,
   parameter  ALLOW_BYPASS = 0,
   localparam DEPTH_W = (DEPTH > 1) ? $clog2(DEPTH+1) : 1
) 
(
   input  logic clk               ,
   input        rst               ,
   input  logic data_in           ,
   input  logic push              ,
   input  logic pop               ,
   output logic empty             ,
   output logic full              ,
   output logic data_out          ,
   output logic [DEPTH_W-1:0] size,
   output logic error
);

////////////////////////////////////////////////////////////////
//////                Internal logic define                /////
////////////////////////////////////////////////////////////////

   logic               buffer [DEPTH];
   logic [DEPTH_W-1:0] next_size     ; 
   logic [DEPTH_W-1:0] head          ;
   logic [DEPTH_W-1:0] tail          ;

   logic bypass_detected;
 
////////////////////////////////////////////////////////////////
//////                    comb logic                       /////
////////////////////////////////////////////////////////////////
 
   assign bypass_detected =  (ALLOW_BYPASS == 1) && push && pop && empty;
   
   always_comb begin
      next_size = size;
      next_size = (next_size < DEPTH) ? next_size + push : next_size;
      next_size = (next_size > 0    ) ? next_size - pop  : next_size;
   end
   
   always_comb begin
      full  = (size == DEPTH);
      empty = (size == 0    );
   end
   
   always_comb begin
      error = (push && full  && !pop) || (pop  && empty && (!push || !ALLOW_BYPASS)) ;
   end
 
 always_comb begin
    data_out = 0; // we can skip this to save un-needed logic that outputs 0 when no pop
    if(pop  && !error) data_out = bypass_detected ? data_in : buffer[head];
 end
 
////////////////////////////////////////////////////////////////
//////                     ff logic                        /////
////////////////////////////////////////////////////////////////
   
   always_ff @(posedge clk) begin
      if(rst) size <= 0; 
      else         size <= error ? size : size + push - pop; 
   end
   
   always_ff @(posedge clk) begin
      if(rst) begin
         head <= 0;
         tail <= 0;
      end
      else begin 
         head <= (!empty         && !bypass_detected) ? (head + pop )%DEPTH : head;
         tail <= ((!full || pop) && !bypass_detected) ? (tail + push)%DEPTH : tail; 
      end
   end
   
   always_ff @(posedge clk) begin
      if(push && !error && !bypass_detected) buffer[tail] <= data_in; 

   end

endmodule



module fv_env
#(
   parameter      DEPTH        = 16,
   parameter  bit ALLOW_BYPASS = 0,
   localparam     DEPTH_W      = (DEPTH > 1) ? $clog2(DEPTH+1) : 1
)
////////////////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////////////////////INTERFACE//////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////////

(
input logic clk                   ,
input           rst               ,
input logic data_in           ,
input logic push                  ,
input logic pop                   ,
input logic empty                  ,
input logic full                   ,
input logic data_out           ,
input logic [DEPTH_W-1:0]          size,
input logic                        error
);
   ////////////////////////////////////////////////////////////////////////////////////////////////////
   ////////////////////////////////////////////////CLK////////////////////////////////////////////////
   ////////////////////////////////////////////////////////////////////////////////////////////////////

   default clocking @(posedge clk); endclocking
   

   ////////////////////////////////////////////////////////////////////////////////////////////////////
   ////////////////////////////////////////////////ENV/////////////////////////////////////////////////
   ////////////////////////////////////////////////////////////////////////////////////////////////////

   logic [DEPTH_W-1:0] fifo_size;
   always_ff @(posedge clk) begin
      
      if(rst) fifo_size = '0; 
      else begin
         fifo_size = fifo_size;
         if (push & (!full | pop )) fifo_size = fifo_size + 1;
         if (pop & (!empty | push)) fifo_size = fifo_size - 1;
      end
   end



   
   logic ref_fifo[DEPTH];
   logic [DEPTH_W-1:0] ref_fifo_head;
   logic [DEPTH_W-1:0] ref_fifo_tail;
   
   always_ff @(posedge clk) begin
	   if(rst) begin
		ref_fifo_head <= '0;
	       	ref_fifo_tail <= '0;	
	   end
	   else begin
         if (push & !error) begin
			   ref_fifo[ref_fifo_tail] <= data_in;
			   ref_fifo_tail  <= (ref_fifo_tail + 1)%DEPTH;
	      end
         if (pop & !error) begin
			   ref_fifo_head <= (ref_fifo_head + 1)%DEPTH;
		   end
	   end
   end

  
   
   ////////////////////////////////////////////////////////////////////////////////////////////////////
   ////////////////////////////////////////////////////////////////////////////////////////////////////
   ////////////////////////////////////////////////////////////////////////////////////////////////////


    property prop; 
      @(posedge clk) disable iff (rst) pop && (!ALLOW_BYPASS || (fifo_size > 0) ) |-> data_out == ref_fifo[ref_fifo_head];

   endproperty



endmodule //fv_env



 module main
#(
   parameter      DEPTH        = 16,
   parameter      ALLOW_BYPASS = 1,
   localparam     DEPTH_W      = (DEPTH > 1) ? $clog2(DEPTH+1) : 1
)
(
   input clk,
   input rst
);
   ////////////////////////////////////////////////////////////////////////////////////////////////////
   ////////////////////////////////////////////////WIRES////////////////////////////////////////////////
   ////////////////////////////////////////////////////////////////////////////////////////////////////


    logic           data_in;
    logic               push;
    logic               pop;
    logic                empty;
    logic                full;
    logic            data_out;
    logic [DEPTH_W-1:0]  size;
    logic                error;

   ////////////////////////////////////////////////////////////////////////////////////////////////////
   ////////////////////////////////////////////////DUT////////////////////////////////////////////////
   ////////////////////////////////////////////////////////////////////////////////////////////////////

   fifo #(
      .DEPTH(DEPTH),
      .ALLOW_BYPASS(ALLOW_BYPASS)
   )
   dut (.clk(clk), .rst(rst), .data_in(data_in), .push(push), .pop(pop), .empty(empty), .full(full), .data_out(data_out), .size(size), .error(error));

   ////////////////////////////////////////////////////////////////////////////////////////////////////
   ////////////////////////////////////////////////ENV////////////////////////////////////////////////
   ////////////////////////////////////////////////////////////////////////////////////////////////////

   fv_env #(
      .DEPTH(DEPTH),
      .ALLOW_BYPASS(ALLOW_BYPASS)
   )
   fv_env (.clk(clk), .rst(rst), .data_in(data_in), .push(push), .pop(pop), .empty(empty), .full(full), .data_out(data_out), .size(size), .error(error));

   ////////////////////////////////////////////////////////////////////////////////////////////////////////////////////

endmodule //fv_tb

