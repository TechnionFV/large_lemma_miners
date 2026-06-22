module gulwani_fig1a #(parameter WIDTH = 1024) (
    input  logic clk,
    input        rst,
    input  logic signed [WIDTH-1:0] y_raw
);

    typedef enum logic {LOOP, DONE} state_t;
    state_t state;

    logic signed [WIDTH-1:0] x, y, y_init;
    logic signed [WIDTH-1:0] c;

    always_ff @(posedge clk) begin
        if (rst) begin
            x      = -19;
            y      = -19;
            y_init = -19;
            c      = 0;

            state = LOOP;
         
        end else begin
            case (state)
                LOOP: begin
                    if (x < 0) begin
                        x <= x + y;
                        y <= y + 1;
                        c <= c + 1;
                    end else begin
                        state <= DONE;
                    end
                end
                DONE: ; 
            endcase
        end
    end

    property prop;
        @(posedge clk) disable iff (rst) (state == DONE |-> y > 0);
    endproperty


endmodule
