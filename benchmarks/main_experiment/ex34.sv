

module ex34 #(parameter WIDTH = 32) (
    input  logic clk,
    input  rst,
    input  signed [WIDTH-1:0] n_raw
);

    typedef enum logic [1:0] {IDLE, LOOP, DONE} state_t;
    state_t state;

    logic signed [WIDTH-1:0] x;
    logic signed [WIDTH-1:0] n;


    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            state <= IDLE;
            x <= 0;
            n <= n_raw;
        end else begin
            case (state)
                IDLE: begin
                    x <= n;
                    state <= LOOP;
                end
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
        @(posedge clk) disable iff (rst) (state == DONE |-> (n < 0 || x == 0));
    endproperty

    
endmodule
