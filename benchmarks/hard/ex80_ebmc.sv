module inv_80 #(parameter WIDTH = 32) (
    input  logic clk,
    input   rst,
    input  unknown_loop,  // nondeterministic loop condition
    input  signed [WIDTH-1:0] x_raw,
    input   signed [WIDTH-1:0] y_raw
);

    typedef enum logic [1:0] {IDLE, LOOP, DONE} state_t;
    state_t state;

    logic signed [WIDTH-1:0] i, x, y;


   
    logic assumptions_hold;
    assign assumptions_hold = (x >= 0) && (y >= 0) && (x >= y);

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            i <= 0;
            x <= x_raw;
            y <= y_raw;
            state <= IDLE;
        end else begin
            case (state)
                IDLE: begin
                    if (assumptions_hold)
                        state <= LOOP;
                end
                LOOP: begin
                    if (unknown_loop) begin
                        if (i < y)
                            i <= i + 1;
                    end else begin
                        state <= DONE;
                    end
                end
                DONE: begin
                end
            endcase
        end
    end

    property prop;
        @(posedge clk) disable iff (rst) ( state != DONE || i <= x);
    endproperty


   

endmodule
