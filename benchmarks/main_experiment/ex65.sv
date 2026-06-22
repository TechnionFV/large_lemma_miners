module ex65 #(parameter WIDTH = 32) (
    input  logic clk,
    input   rst
);

    typedef enum logic [1:0] {LOOP_BEGIN, LOOP, DONE} state_t;
    state_t state;

    logic signed [WIDTH-1:0] x, y;


    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            x <= 1;
            y <= 0;
            state <= LOOP_BEGIN;
        end else begin
            case (state)
                LOOP_BEGIN: begin
                    y <= 100 - x;
                    x <= x+1;
                    state <= LOOP;
                end
                LOOP: begin
                    if (x <= 100) begin
                        y <= 100 - x;
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
        @(posedge clk) disable iff (rst) (y >= 0);
    endproperty

   
endmodule
