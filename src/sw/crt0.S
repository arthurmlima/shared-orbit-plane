    .section .text.start
    .globl _start
_start:
    li   sp, STACK_TOP
    call main
    li   t0, 0x60000000      # done flag
    sw   zero, 0(t0)
1:  j 1b
