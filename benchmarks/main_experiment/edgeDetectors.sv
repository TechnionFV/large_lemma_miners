//https://circuitcove.com/design-examples-edge-detectors/

module RisingEdgeDetector (
  input  logic clk,
  input  rst,
  input  logic signal,
  output logic _edge
);

  logic signalPrev;

  always_ff @(posedge clk) begin
    if (rst) begin
      signalPrev <= 0;
      _edge <= 0;
    end
    else begin
    signalPrev <= signal;
    _edge       <= (signal && !signalPrev);
  end
  end

endmodule

module FallingEdgeDetector (
  input  logic clk,
  input  rst,
  input  logic signal,
  output logic _edge
);

  logic signalPrev;

  always_ff @(posedge clk) begin
   if (rst) begin
      signalPrev <= 0;
      _edge <= 0;
    end
    else begin
    signalPrev <= signal;
    _edge       <= (!signal && signalPrev);
  end
  end

endmodule

module BothEdgeDetector (
  input  logic clk,
  input  rst,
  input  logic signal,
  output logic _edge
);

  logic signalPrev;

  always_ff @(posedge clk) begin
   if (rst) begin
      signalPrev <= 0;
      _edge <= 0;
    end
    else begin
    signalPrev <= signal;
    _edge       <= signal ^ signalPrev; 
  end
  end

endmodule

module main (
  input  logic clk,
  input rst,
  input  logic signal
);

  logic rising_edge, falling_edge, both_edges;

  // Instantiate RisingEdgeDetector
  RisingEdgeDetector red (
    .clk(clk),
    .rst(rst),
    .signal(signal),
    ._edge(rising_edge)
  );

  // Instantiate FallingEdgeDetector
  FallingEdgeDetector fed (
    .clk(clk),
    .rst(rst),
    .signal(signal),
    ._edge(falling_edge)
  );

  // Instantiate BothEdgeDetector
  BothEdgeDetector bed (
    .clk(clk),
    .rst(rst),
    .signal(signal),
    ._edge(both_edges)
  );

  property prop;
    @(posedge clk) disable iff (rst) (rising_edge || falling_edge) |-> both_edges;
  endproperty
 
  
  endmodule