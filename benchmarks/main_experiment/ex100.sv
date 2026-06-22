module counter_match #(parameter WIDTH = 32) (
    input  logic                    clk,
    input                           rst,
    input signed [WIDTH-1:0] n_raw
);

    typedef enum logic [1:0] {LOOP, DONE} state_t;
    state_t state;

    logic signed [WIDTH-1:0] x, y, n;

    // Vorbedingung (Assumption) als Signal kodiert
    logic n_nonneg;
    assign n_nonneg = (n >= 0);

    /* Ablauf-FSM */
    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            n     <= n_raw;
            x     <= n_raw;
            y     <= 0;
            state <= LOOP;
        end else begin
            case (state)
                LOOP: if (x > 0) begin
                          y <= y + 1;
                          x <= x - 1;
                      end else
                          state <= DONE;
                DONE: ; // bleibt im Endzustand
            endcase
        end
    end

    property prop;
        @(posedge clk) disable iff (rst) (state != DONE || n < 0 || y == n);
    endproperty

    
endmodule
