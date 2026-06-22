

module ex34 #(parameter WIDTH = 32) (
    input  logic clk,
    input  rst
);

    typedef enum logic [1:0] {LOOP, DONE} state_t;
    state_t state;

    logic signed [WIDTH-1:0] x;

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= LOOP;
            x <= 100;
        end else begin
            case (state)
                LOOP: begin
                    if (x > 0)
                        x <= x - 1;
                    else
                        state <= DONE;
                end
                DONE: begin
                end
            endcase
        end
    end

    property prop;
        @(posedge clk) disable iff (rst) (state == DONE |->  x == 0);
    endproperty

    

endmodule
