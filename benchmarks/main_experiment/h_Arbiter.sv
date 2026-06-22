//dified by: Rajdeep Mukherjee <rajdeep.mukherjee@cs.ox.ac.ik>


//typedef enum {A, B, C, X} selection;
//typedef enum {IDLE, READY, BUSY} controller_state;
//typedef enum {NO_REQ, REQ, HAVE_TOKEN} client_state;

module main(clk,rst);
input clk;
input rst;
wire ackA, ackB, ackC, pass_tokenA, pass_tokenB, pass_tokenC;

parameter A =0;
parameter B =1;
parameter C =2;
parameter X =3;

parameter IDLE = 0;
parameter READY = 1;
parameter BUSY = 2;

parameter NO_REQ = 0;
parameter REQ = 1;
parameter HAVE_TOKEN = 2;

wire [1:0] sel;
wire active;

assign active = pass_tokenA || pass_tokenB || pass_tokenC;

controller controllerA(clk, reqA, rst, ackA, sel, pass_tokenA, A);
controller controllerB(clk, reqB, rst, ackB, sel, pass_tokenB, B);
controller controllerC(clk, reqC, rst, ackC, sel, pass_tokenC, C);
arbiter arbiter(clk, sel, rst, active);

client clientA(clk, reqA, rst, ackA);
client clientB(clk, reqB, rst, ackB);
client clientC(clk, reqC, rst, ackC);

property prop;
    @(posedge clk) disable iff (rst) ( ~ (ackA == 1 && ackB == 1 || ackB == 1 && ackC == 1 || ackC == 1 && ackA ==1));
endproperty



endmodule

module controller(clk, req, rst, ack, sel, pass_token, id);
input clk, req, rst;

parameter A =0;
parameter B =1;
parameter C =2;
parameter X =3;

parameter IDLE = 0;
parameter READY = 1;
parameter BUSY = 2;

parameter NO_REQ = 0;
parameter REQ = 1;
parameter HAVE_TOKEN = 2;

input wire [1:0] sel, id;
output reg ack, pass_token;
reg [1:0] state;

wire is_selected;
assign is_selected = (sel == id);

always @(posedge clk) begin
  if (rst) begin
      state = IDLE;
      ack = 0;
      pass_token = 1;
  end
  else begin
  case(state)
    IDLE:
      if (is_selected)
        if (req)
          begin
          state = READY;
          pass_token = 0; /* dropping off this line causes a safety bug */
          end
        else
          pass_token = 1;
      else
        pass_token = 0;
    READY:
      begin
      state = BUSY;
      ack = 1;
      end
    BUSY:
      if (!req)
        begin
        state = IDLE;
        ack = 0;
        pass_token = 1;
        end
  endcase
end
end
endmodule

module arbiter(clk, sel, rst, active);
input clk, active, rst;


parameter A =0;
parameter B =1;
parameter C =2;
parameter X =3;

parameter IDLE = 0;
parameter READY = 1;
parameter BUSY = 2;

parameter NO_REQ = 0;
parameter REQ = 1;
parameter HAVE_TOKEN = 2;
output wire [1:0] sel;
reg [1:0] state;


assign sel = active ? state: X;

always @(posedge clk) begin
  if (rst) begin
    state = A;
  end
  else begin
  if (active)
    case(state) 
      A:
        state = B;
      B:
        state = C;
      C:
        state = A;
    endcase
end
end
endmodule

module client(clk, req, rst, ack);
input clk, ack, rst;
output req;

parameter A =0;
parameter B =1;
parameter C =2;
parameter X =3;

parameter IDLE = 0;
parameter READY = 1;
parameter BUSY = 2;

parameter NO_REQ = 0;
parameter REQ = 1;
parameter HAVE_TOKEN = 2;
reg req;
reg [1:0] state;

// RM: This can be nondeterministically set to 0 or 1
wire rand_choice = 1'b0;


always @(posedge clk) begin
  if (rst) begin
    req = 0;
    state = NO_REQ;
  end
  else begin
  case(state)
    NO_REQ:
      if (rand_choice)
        begin
        req = 1;
        state = REQ;
        end
    REQ:
      if (ack)
        state = HAVE_TOKEN;
    HAVE_TOKEN:
      if (rand_choice)
        begin
        req = 0;
        state = NO_REQ;
        end
  endcase
  end
end
endmodule
