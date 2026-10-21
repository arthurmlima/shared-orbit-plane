OPT ?= -O0
CROSS_COMPILE ?= riscv64-unknown-elf-
CC = $(CROSS_COMPILE)gcc
OBJCOPY = $(CROSS_COMPILE)objcopy
CFLAGS = -march=rv32im -mabi=ilp32 $(OPT) -ffreestanding -nostdlib -nostartfiles -Wall
# crypt_ppu links the halo-only PPU helper variant of the runtime library.
LIB_SOURCE ?= $(if $(filter crypt_ppu,$(APP)),mpriscv_halo.c,mpriscv.c)
LDFLAGS = -Wl,--build-id=none
RAM_BYTES ?= 8192
APP ?= sobel_app
all: $(APP)$(SUFFIX).hex
$(APP)$(SUFFIX).elf: crt0.S $(LIB_SOURCE) $(APP).c link.ld
	$(CC) $(CFLAGS) $(LDFLAGS) -DSTACK_TOP=$(RAM_BYTES) -T link.ld -o $@ crt0.S $(LIB_SOURCE) $(APP).c -lgcc
$(APP)$(SUFFIX).hex: $(APP)$(SUFFIX).elf
	$(OBJCOPY) -O binary $< $(basename $@).bin
	python3 -c "import sys,struct;d=open('$(basename $@).bin','rb').read();d+=b'\0'*(-len(d)%4);open('$@','w').write('\n'.join('%08x'%w for w in struct.unpack('<%dI'%(len(d)//4),d))+'\n')"
clean:
	rm -f *.elf *.bin *.hex
