// adapted from: data/benchmarks/code2inv/51.c



module loop_c_behavior #(parameter WIDTH = 32) (
    input logic clk,
    input  rst,
    input logic unknown_loop,  
    input logic unknown_branch
);

    typedef enum logic [1:0] {IDLE, LOOP, DONE} state_t;
    state_t state;

    logic [WIDTH-1:0] c,d;

    assign c_out = c;

    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            c <= 0;
            d <= 4;
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
                            if (c != d)
                                c <= c + 1;
                        end else begin
                            if (c == d)
                                c <= 1;
                        end
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
     @(posedge clk) disable iff (rst) (c <= d);
    endproperty

    
   
endmodule
