/* Standalone linker layout for the GPL open GBA BIOS. No Nintendo BIOS input. */
OUTPUT_ARCH(arm)
ENTRY(_start)
SECTIONS {
 . = 0;
 .text : { KEEP(*(.init)) *(.text*) *(.rodata*) }
 .data : { *(.data*) }
 .bss (NOLOAD) : { *(.bss*) *(COMMON) }
 /DISCARD/ : { *(.comment) *(.note*) *(.ARM.attributes) *(.ARM.exidx*) *(.ARM.extab*) }
 ASSERT(. <= 0x4000, "Open BIOS exceeds 16 KiB")
}
