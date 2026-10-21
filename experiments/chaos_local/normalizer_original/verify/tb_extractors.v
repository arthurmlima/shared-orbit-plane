`timescale 1ns/1ps
module tb_extractors;
    reg clk=0;
    always #5 clk=~clk;
    reg [31:0] a=0, b=0;
    wire [7:0] y0,y1,y2,y3;
    ext_bench4 dut(.clk(clk), .a_in(a), .b_in(b), .y0(y0), .y1(y1), .y2(y2), .y3(y3));
    reg [31:0] va,vb;
    reg [7:0] e0,e1,e2,e3;
    integer fd, fields, count;
    initial begin
        fd=$fopen("vectors.txt","r");
        if(fd==0) $fatal(1,"Cannot open vectors.txt");
        count=0;
        while(!$feof(fd)) begin
            fields=$fscanf(fd,"%h %h %h %h %h %h\n",va,vb,e0,e1,e2,e3);
            if(fields!=6) $fatal(1,"Malformed vector at index %0d",count);
            @(negedge clk); a=va; b=vb;
            @(posedge clk); @(posedge clk); #1;
            if(y0!==e0 || y1!==e1 || y2!==e2 || y3!==e3)
                $fatal(1,"Mismatch vector=%0d a=%08x b=%08x actual=%02x,%02x,%02x,%02x expected=%02x,%02x,%02x,%02x",count,va,vb,y0,y1,y2,y3,e0,e1,e2,e3);
            count=count+1;
        end
        $fclose(fd);
        if(count!=300234) $fatal(1,"Wrong vector count=%0d",count);
        $display("PASS vectors=%0d extractors=4 byte_checks=%0d mismatches=0",count,count*4);
        $finish;
    end
endmodule
