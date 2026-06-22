

module simple_cam
#(
   parameter USE_BIT_VECTOR       = 0,
   parameter SUPPORT_MULTI_PUSH   = 1,
   parameter DUT_MASTER           = 1'b1, //1-Active Master,0-Active Slave, o.w. - Monitor
   parameter NUM_OF_ENTRIES       = 8,
   parameter NUM_OF_MATCHES       = USE_BIT_VECTOR?1:NUM_OF_ENTRIES,
   parameter ID_WIDTH             = NUM_OF_ENTRIES==1 ? 1 : $clog2(NUM_OF_ENTRIES),
   parameter NUM_OF_POPS          = 1,
   parameter NUM_OF_POPS_WIDTH    = NUM_OF_POPS==1 ? 1 : $clog2(NUM_OF_POPS+1)

)
(
   input                         clk,
   input                         rst,
   input                         push_raw,
   input [NUM_OF_POPS_WIDTH-1:0] push_num_of_pops,
   input [ID_WIDTH-1:0]          push_id,
   input                         lookup,
   input [ID_WIDTH-1:0]          lookup_id,
   input                         pop,
   input [ID_WIDTH-1:0]          pop_id
);

   ////////////////////////////////////////////////////////////
   default clocking @(posedge clk); endclocking
   genvar gi;

   reg   [NUM_OF_ENTRIES-1:0]                        cam_valid              ;
   wire  [NUM_OF_ENTRIES-1:0]                        cam_valid_ns           ;
   
   wire  [NUM_OF_MATCHES-1:0]                        push_match             ;
   wire  [NUM_OF_MATCHES-1:0]                        lookup_match           ;
   wire  [NUM_OF_MATCHES-1:0]                        pop_match              ;
   
   reg   [NUM_OF_ENTRIES-1:0][NUM_OF_POPS_WIDTH-1:0] entity_cnt             ;
   logic [NUM_OF_ENTRIES-1:0][NUM_OF_POPS_WIDTH-1:0] entity_cnt_ns          ;
   logic [NUM_OF_ENTRIES-1:0]                        push_ptr               ;
   logic [NUM_OF_ENTRIES-1:0]                        pop_evict              ;
   
   logic [ID_WIDTH-1:0]                              first_valid_id         ;
   logic [ID_WIDTH-1:0]                              pop_index              ;
   logic [NUM_OF_ENTRIES-1:0]                        first_valid_id_one_hot ;
   logic                                             push                   ;
   int i, j, k, l;    
   
   assign push = push_raw & (|push_match || ~&cam_valid);

   always_comb begin                                                                    
      first_valid_id_one_hot = '0;                                                                     
      for (i = 0; i < NUM_OF_ENTRIES; i++) begin
         if (~|first_valid_id_one_hot && cam_valid[i])  begin
               first_valid_id_one_hot[i] = 1; 
         end
      end
   end
  
   reg  [NUM_OF_ENTRIES-1:0][ID_WIDTH-1:0] cam;
   wire [NUM_OF_ENTRIES-1:0][ID_WIDTH-1:0] cam_ns;
   always_comb begin                                                                    
      push_ptr = '0;
      pop_evict = '0;                                                                     
      for (j = 0; j < NUM_OF_ENTRIES; j++) begin
         if (~|push_ptr && ~cam_valid[j]) push_ptr[j] = 1; 
         if (~|pop_evict && pop_match[j]) pop_evict[j] = 1; 
      end
   end


   
   always_comb begin                                                       
      pop_index = '0;                                                         
      for (k = NUM_OF_ENTRIES; k > 0; k--) if (pop_evict[k-1]) pop_index = k-1; 
   end


   always_comb begin
      first_valid_id = '0;
      for (l = 0; l < NUM_OF_ENTRIES; l++) if (first_valid_id_one_hot[l]) first_valid_id = cam[l];
   end

   for (gi=0; gi<NUM_OF_ENTRIES; gi++) begin: CAM_IMP
      assign push_match  [gi]  = cam_valid[gi] & (push_id  ==cam[gi][ID_WIDTH-1:0]);
      assign lookup_match[gi]  = cam_valid[gi] & (lookup_id==cam[gi][ID_WIDTH-1:0]);
      assign pop_match   [gi]  = cam_valid[gi] & (pop_id   ==cam[gi][ID_WIDTH-1:0]);
      assign cam_ns      [gi]  = push & push_ptr[gi] ? push_id : cam[gi];
      
      if (SUPPORT_MULTI_PUSH) begin: MULTI_PUSH
         assign cam_valid_ns [gi] = push & (|push_match?push_match[gi]:push_ptr[gi]) | cam_valid[gi] & ~(pop & pop_evict[gi] & (entity_cnt[gi]=='h1));
         assign entity_cnt_ns[gi] =  entity_cnt[gi]+(push&(|push_match?push_match[gi]:push_ptr[gi])?push_num_of_pops:'0) -{{NUM_OF_POPS_WIDTH-1{1'b0}}, pop&pop_evict[gi]};
      end else begin: SINGLE_PUSH
         assign cam_valid_ns [gi] = push & push_ptr[gi] | cam_valid[gi] & ~(pop & pop_evict[gi]);
      end
   end

   always @(posedge clk) cam <= cam_ns;

   always @(posedge clk) cam_valid  <= rst ? {NUM_OF_ENTRIES{1'b0}} : cam_valid_ns ;
   always @(posedge clk) begin
   int m;
   if (rst) begin
      for (m = 0; m < NUM_OF_ENTRIES; m++) begin
            entity_cnt[m] <= {NUM_OF_POPS_WIDTH{1'b0}};
      end
   end else begin
      entity_cnt <= entity_cnt_ns;
   end
   end


    logic chosen;
    logic chosen_push;
    logic [ID_WIDTH-1:0] chosen_push_id;
    logic chosen_not_popped;

    
    always_ff @(posedge clk) begin
        if (rst) begin
            chosen <= 1'b0;

        end else
        if (~chosen & chosen_push & push) begin
            chosen <= 1'b1;
            chosen_push_id <= push_id;
            chosen_not_popped <= (pop_id != push_id);

        end else begin
            chosen_not_popped <= chosen_not_popped & (pop_id != chosen_push_id);
        end

    end



    property prop;
        disable iff (rst) (chosen & chosen_not_popped & (lookup_id == chosen_push_id) |-> |lookup_match);
    endproperty

 

   
endmodule // simple_cam

