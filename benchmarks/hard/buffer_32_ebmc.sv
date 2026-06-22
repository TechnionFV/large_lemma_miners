module main #(
    parameter SIZE = 32,
    parameter LOGSIZE = 5
) (
    clock,
    alloc_raw,
    free_raw,
    free_addr_raw
);
  input clock;
  input alloc_raw;
  input free_raw;
  input [(LOGSIZE-1):0] free_addr_raw;

  reg    [0:(SIZE - 1)]   busy  ;
  reg [LOGSIZE:0] count;
  reg alloc, free;
  reg     [(LOGSIZE-1):0] free_addr;
  integer           i;
  wire              nack;
  wire    [(LOGSIZE-1):0] alloc_addr_raw;
  wire    [(LOGSIZE-1):0] alloc_addr;

  initial begin
    for (i = 0; i < SIZE; i = i + 1) busy[i] = 0;
    count = 0;
    alloc = 0;
    free = 0;
    free_addr = 0;
  end

  assign nack = alloc & (count == SIZE);
  
  // Generate alloc_addr assignment
  generate
    genvar j;
    wire [LOGSIZE-1:0] alloc_addr_array [0:SIZE-1];
    
    for (j = 0; j < SIZE; j = j + 1) begin : gen_alloc_addr
      if (j == 0) begin
        assign alloc_addr_array[j] = ~busy[j] ? j : {LOGSIZE{1'bx}};
      end else begin
        assign alloc_addr_array[j] = ~busy[j] ? j : alloc_addr_array[j-1];
      end
    end
    
    assign alloc_addr = alloc_addr_array[SIZE-1];
  endgenerate

  always @(posedge clock) begin
    alloc = alloc_raw;
    free = free_raw;
    free_addr = free_addr_raw < SIZE ? free_addr_raw : SIZE - 1;
  end
  
  always @(posedge clock) begin
    count = count + (alloc & ~nack) - (free & busy[free_addr]);
    if (free) busy[free_addr] = 0;
    if (alloc & ~nack) busy[alloc_addr] = 1;
  end


  property prop;
    (count <= SIZE);
  endproperty

endmodule  // buffer_alloc