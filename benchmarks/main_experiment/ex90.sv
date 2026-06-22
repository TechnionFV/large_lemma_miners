module ex90 #(parameter WIDTH = 32) (
    input  logic clk,
    input x_raw,
    input  rst,
    input  logic unknown_branch
);

    typedef enum logic [1:0] {LOOP, DONE} state_t;
    state_t state;

    logic signed [WIDTH-1:0] x, y;
    logic lock;

    assign lock_out = lock;

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            x <= x_raw;
            y <= x_raw + 1;  
            lock <= 0;
            state <= LOOP;
        end else begin
            case (state)
                LOOP: begin
                    if (x != y) begin
                        if (unknown_branch) begin
                            lock <= 1;
                            x <= y;
                        end else begin
                            lock <= 0;
                            x <= y;
                            y <= y + 1;
                        end
                    end else begin
                        state <= DONE;
                    end
                end
                DONE: begin end
            endcase
        end
    end

    property prop;
        @(posedge clk) disable iff (rst) (state == DONE |-> lock == 1);
    endproperty


endmodule
