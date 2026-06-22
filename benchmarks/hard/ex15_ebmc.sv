// Source: data/benchmarks/code2inv/15.c

module ex15 #(parameter WIDTH = 32) (
    input logic clk,
    input rst,
    input [WIDTH-1:0] n_init,
    input logic unknown, 
    output logic assert_trigger
);

    typedef enum logic [1:0] {IDLE, LOOP, DONE} state_t;
    state_t state;

    logic [WIDTH-1:0] x, m;
    logic [WIDTH-1:0] n;

    
    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            x <= 0;
            m <= 0;
            n <= n_init;
            state <= IDLE;
        end else begin
            case (state)
                IDLE: begin
                    x <= 0;
                    m <= 0;
                    state <= LOOP;
                end
                LOOP: begin
                    if (x < n) begin
                        if (unknown)
                            m <= x;
                        x <= x + 1;
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
     @(posedge clk) disable iff (rst) (state != DONE || n <= 0 || m < n);
    endproperty


   

endmodule

