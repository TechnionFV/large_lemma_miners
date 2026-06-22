module brs1 #(parameter WIDTH = 16) (
    input  logic                    clk,
    input                           rst
);

    typedef enum logic [1:0] {LOOP, DONE} state_t;
    state_t state;

    integer j;
    logic [WIDTH-1:0] i;
    logic [WIDTH-1:0] a[19];
    logic [WIDTH-1:0] sum;


     always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            i     <= 0;
            sum   <= 0;
            state <= LOOP;
            for (j = 0; j < 19; j++) begin
                a[j] = 0;
            end
        end else begin
            case (state)
                LOOP: begin
                    if (i < 19) begin
                        i     <= i+1;
                        if (i % 1 == 0) begin
                          a[i] <= 1;
                          sum <= sum + 1;
                        end
                    end
                    else begin
                        state <= DONE;
                    end
                end
            endcase
        end
    end

    
    property prop;
        @(posedge clk) disable iff (rst) sum <= 19;
    endproperty

   

endmodule
