# Makefile for usr_pte_query kernel module
obj-m := usr_pte_query.o

# Default: use current kernel's build directory
KDIR ?= /lib/modules/$(shell uname -r)/build

# Check if KDIR exists, otherwise try to use an alternative
ifeq ($(wildcard $(KDIR)/Makefile),)
    # Fallback: look for kernel source in common locations
    ALT_KDIRS := /root/openeuler/kernel /home/zt/kernel /kernel
    KDIR_FOUND := $(foreach d,$(ALT_KDIRS),$(if $(wildcard $(d)/Makefile),$(d)))
    ifneq ($(KDIR_FOUND),)
        $(info KDIR not found, using fallback: $(KDIR_FOUND))
        KDIR := $(KDIR_FOUND)
    else
        $(info ================================================================)
        $(info ERROR: Kernel build directory not found!)
        $(info)
        $(info Tried: $(KDIR))
        $(info)
        $(info Please either:)
        $(info   1. Install kernel-devel package:)
        $(info      CentOS/RHEL: sudo yum install kernel-devel
        $(info      Ubuntu/Debian: sudo apt install linux-headers-$$(uname -r)
        $(info)
        $(info   2. Or specify KDIR explicitly:)
        $(info      make KDIR=/path/to/your/kernel/source
        $(info)
        $(info   3. Or create a symlink to your kernel source)
        $(info ================================================================)
        $(error)
    endif
endif

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean

.PHONY: all clean
