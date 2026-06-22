module gulwani_cegar2 #(parameter WIDTH = 128) (
    input  logic clk,
    input        rst,
    input  logic unknown_branch_1,
    input  logic unknown_branch_2,
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
                    if (n < 1300) begin
                        if (unknown_branch_1) begin
                            m <= x;
                            if (c < (32'hFFFFFFFF / 2 -1)) begin
                                x <= x + 2;
                                c <= c + 1;
                            end
                        end
                        if (unknown_branch_2) begin
                            n <= n + 1;
                        end
                    end else begin
                        state <= DONE;
                    end
                end
                DONE: ;
            endcase
        end
    end

    property prop;
        @(posedge clk) disable iff (rst) (x < n |-> c < 777);
    endproperty
   

    
endmodule
