module gulwani_cegar2 #(parameter WIDTH = 32) (
    input  logic clk,
    input        rst,
    input  logic unknown_branch, 
    input  [WIDTH-1:0] n_raw
);

    typedef enum logic [1:0] {LOOP, DONE} state_t;
    state_t state;

    logic unsigned [WIDTH-1:0] x, m, n, c;


    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            x <= 0;
            m <= 0;
            n <= n_raw;
            c <= 0;
            state <= LOOP;
        end else begin
            case (state)
                LOOP: begin
                    if (x < 800) begin
                        if (unknown_branch) begin
                            m <= x;
                            if (n < 32'hFFFFFFFE) begin
                                n <= n + 2;
                                c <= c + 1;
                            end
                        end
                        x <= x + 1;
                    end else begin
                        state <= DONE;
                    end
                end
                DONE: ;
            endcase
        end
    end

    property prop;
        @(posedge clk) disable iff (rst) ((x > n) |-> c < 400);
    endproperty

    

endmodule
