module gulwani_cegar1 #(parameter WIDTH = 64) (
    input  logic clk,
    input        rst,
    input  unknown_loop,
    input  [WIDTH-1:0] x_raw,
    input  [WIDTH-1:0] y_raw
);

    typedef enum logic [2:0] {COND, LOOP, DONE} state_t;
    state_t state;
    logic   cond;

    logic signed [WIDTH-1:0] x, y;

    logic signed [WIDTH-1:0] x_init;
    logic signed [WIDTH-1:0] y_init;
    assign cond = (x >= 0 && x <= 200 && y >= 0 && y <= 270);
   
    assign cond_raw =  (x_init >= 0 && x_init <= 200 && y_init >= 0 && y_init <= 270);
   
    assign assumptions_hold = (x_init >= 0 && x_init <= 200 && y_init >= 0 && y_init <= 270);
    
    always_ff @(posedge clk) begin
        if (rst) begin
            x_init = x_raw;
            y_init = y_raw;
            x = x_raw;
            y = y_raw;
   
            state = COND;
        end else begin
            case (state)
                COND: if (cond)
                        state = LOOP;
                      else 
                        state = DONE;
                LOOP:
                    if (unknown_loop) begin
                        x = x + 42;
                        y = y + 42;
                    end else begin
                        state = DONE;
                    end
            endcase
        end
    end

    property prop;
        @(posedge clk) disable iff (rst) ((assumptions_hold && x == 156) |-> y <= 500); 
    endproperty

   
endmodule
