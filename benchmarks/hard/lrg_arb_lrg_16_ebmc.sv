module main
#(
   parameter  NUM_REQ   = 16,
   localparam NUM_REQ_W = (NUM_REQ > 1) ? $clog2(NUM_REQ+1) : 1 
)

////////////////////////////////////////////////////////////////////////////////////////////////////
//////////////////////////////////////////////INTERFACE//////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////////

(
input  logic clk                        ,
input        rst                        ,
input  logic [NUM_REQ-1:0]  in_req_vec,
input  logic [NUM_REQ_W-1:0] arbitrary_requester_raw,
input  logic [NUM_REQ_W-1:0] another_arbitrary_requester_raw  
);
////////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////CLK////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////////

default clocking @(posedge clk); endclocking


////////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////ENV////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////////

logic [NUM_REQ_W-1:0] ranks_raw [NUM_REQ-1:0];
logic [NUM_REQ_W-1:0] ranks [NUM_REQ-1:0];
logic [NUM_REQ-1:0]    o_grant_vec_raw;
logic [NUM_REQ_W-1:0] chosen_priority;
logic [NUM_REQ_W-1:0] arbitrary_requester;
logic [NUM_REQ_W-1:0] another_arbitrary_requester;
logic [NUM_REQ-1:0] o_grant_vec_ref;

always_comb begin
        chosen_priority = NUM_REQ;
        ranks_raw = ranks;
        int idx;
        for (idx=0; idx < NUM_REQ; idx++) begin
                if (in_req_vec[idx] && ranks_raw[idx] < chosen_priority) begin
                        chosen_priority = ranks_raw[idx];
        
                end
        end
        
        o_grant_vec_raw = '0;
        for (idx=0; idx < NUM_REQ; idx++) begin
                if (ranks_raw[idx] == chosen_priority) begin
                        o_grant_vec_raw[idx] = 1'b1;
                        ranks_raw[idx] = NUM_REQ-1;
                end else if (ranks_raw[idx] > chosen_priority) begin
                        ranks_raw[idx] = ranks_raw[idx] - 3'b1;
                end
        end
        
end
logic chosen;
assign o_grant_vec_ref = o_grant_vec_raw;
always @(posedge clk or posedge rst) begin

        if (rst) begin
               int jdx;
                for (jdx=0; jdx < NUM_REQ; jdx++) begin
                        ranks[jdx] <= jdx;
                end
                chosen <= 1'b0;
        end
        else begin 
                if (~chosen) begin
                        if ((arbitrary_requester_raw == another_arbitrary_requester_raw) 
                                || arbitrary_requester_raw >= NUM_REQ || another_arbitrary_requester_raw >= NUM_REQ) begin
                                arbitrary_requester <= 3'b0;
                                another_arbitrary_requester <= 3'b1;
                                end 
                        else begin
                                arbitrary_requester <= arbitrary_requester_raw;
                                another_arbitrary_requester <= another_arbitrary_requester_raw;
                        end
                        chosen <= 1'b1;
                end
                
                ranks <= ranks_raw;
        end


end


property prop;
   @(posedge clk) disable iff (rst)  chosen & o_grant_vec_ref[arbitrary_requester] 
        |-> (~in_req_vec[another_arbitrary_requester] || (ranks[arbitrary_requester] < ranks[another_arbitrary_requester]));
endproperty





                               ////////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////////////////////////////////////////////

endmodule //fv_env


