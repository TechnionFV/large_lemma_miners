module brs1 #(parameter WIDTH = 8, parameter n = 16) (
    input  logic                    clk,
    input                           rst
);
    parameter N = 5*n;
    typedef enum logic [1:0] {LOOP, DONE} state_t;
    state_t state;

    integer j;
    logic [WIDTH-1:0] i;
    logic [WIDTH-1:0] a[N];
    logic [WIDTH-1:0] sum;


     always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            i     <= 0;
            sum   <= 0;
            state <= LOOP;
            for (j = 0; j < N; j++) begin
                a[j] = 0;
            end
        end else begin
            case (state)
                LOOP: begin
                    if (i < N) begin
                        i     = i+1;
                        if (i % 5 == 0) begin
                          a[i] = 1;
                        sum = sum + 1;
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
        @(posedge clk) disable iff (rst) (state != DONE) || (sum == n); //((sum % 5) == 0);
    endproperty

    
endmodule
