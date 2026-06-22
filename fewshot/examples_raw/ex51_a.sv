// adapted from: data/benchmarks/code2inv/51.c



module ex_51_59 #(parameter WIDTH = 32) (
    input logic clk,
    input  rst,
    input  [WIDTH-1:0] d_raw,
    input logic unknown_loop,  
    input logic unknown_branch
);

    typedef enum logic [1:0] {IDLE, LOOP, DONE} state_t;
    state_t state;

    logic [WIDTH-1:0] c,d;


    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            c <= 0;
            d <= d_raw;
            state <= IDLE;
        end else begin
            case (state)
                IDLE: begin
                    c <= 0;
                    state <= LOOP;
                end
                LOOP: begin
                    if (unknown_loop) begin
                        if (unknown_branch) begin
                            if (c == d - 1)
                                c <= c + 2;
                        end else begin
                            if (c == d)
                                c <= 1;
                        end
                    end else begin
                        if (c != 0)
                        state <= DONE;
                    end
                end
                DONE: begin
                end
            endcase
        end
    end


    property prop;
     @(posedge clk) disable iff (rst) (state != DONE || c != d);
    endproperty


endmodule
