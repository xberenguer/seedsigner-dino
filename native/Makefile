CC ?= cc
CFLAGS ?= -O3
CFLAGS += -std=c99 -Wall -Wextra -Werror -fno-strict-aliasing
LDLIBS += -ldl

.PHONY: all clean test
all: dino-native

dino-native: dino_frontend.c libretro.h
	$(CC) $(CPPFLAGS) $(CFLAGS) $(LDFLAGS) -o $@ dino_frontend.c $(LDLIBS)

test: dino-native
	./dino-native --self-test
	python3 tests/test_frontend.py

clean:
	rm -f dino-native tests/mock_core.so
