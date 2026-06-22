module gulwani_cegar1 #(parameter WIDTH = 32) (
    input  logic clk,
    input        rst,
    input  unknown_loop,
    input  [WIDTH-1:0] x_raw,
    input  [WIDTH-1:0] y_raw
);

    typedef enum logic [2:0] {COND, LOOP, DONE} state_t;
    state_t state;
    logic   cond;

    logic [WIDTH-1:0] x, y;

    logic [WIDTH-1:0] x_init;
    logic [WIDTH-1:0] y_init;
    assign cond = (x >= 0 && x <= 5 && y >= 0 && y <= 5);
    assign assumptions_hold = (x_init >= 0 && x_init <= 5 && y_init >= 0 && y_init <= 5);
    
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
                        x = x + 3;
                        y = y + 3;
                    end else begin
                        state = DONE;
                    end
            endcase
        end
    end

    property prop;
        @(posedge clk) disable iff (rst) ((assumptions_hold && y == 0 && x <= 10) |-> x < 10); 
    endproperty
    assert property(prop);

   

endmodule
