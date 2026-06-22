module gulwani_cegar2 #(parameter WIDTH = 32) (
    input  logic clk,
    input        rst,
    input  logic unknown_branch, 
    input  [WIDTH-1:0] n_raw
);

    typedef enum logic [1:0] {LOOP, DONE} state_t;
    state_t state;

    logic [WIDTH-1:0] x, m, n;


    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            x <= 0;
            m <= 0;
            n <= n_raw;
            state <= LOOP;
        end else begin
            case (state)
                LOOP: begin
                    if (x < n) begin
                        if (unknown_branch)
                            m <= x;
                        x <= x + 1;
                    end else begin
                        if (n > 0)
                            state <= DONE;
                    end
                end
                DONE: ;
            endcase
        end
    end

    property prop;
        @(posedge clk) disable iff (rst) (state != DONE || (m < n));
    endproperty


   

endmodule
