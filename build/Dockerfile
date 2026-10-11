FROM --platform=linux/amd64 debian:bookworm-slim@sha256:a4672c0cb26fbdde88e38fa2dfb6c681942306680e41e4378b28770b6e79ee91
# Signed Debian repository metadata + immutable dated snapshot. Do not substitute
# a floating apt mirror: its compiler/binutils/mtools output can change.
RUN test "$(uname -m)" = x86_64 && rm -f /etc/apt/sources.list.d/debian.sources && \
    printf 'deb [check-valid-until=no] http://snapshot.debian.org/archive/debian/20260901T000000Z bookworm main\n' > /etc/apt/sources.list && \
    apt-get -o Acquire::Check-Valid-Until=false update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    python3 make gcc libc6-dev binutils gcc-arm-none-eabi \
      binutils-arm-none-eabi libnewlib-dev mtools dosfstools qemu-user \
      gnupg ca-certificates xz-utils && \
    rm -rf /var/lib/apt/lists/*
RUN apt-get -o Acquire::Check-Valid-Until=false update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends file && \
    rm -rf /var/lib/apt/lists/*
ENV TZ=UTC LC_ALL=C SOURCE_DATE_EPOCH=1672531200 PYTHONDONTWRITEBYTECODE=1
WORKDIR /work
CMD ["bash", "scripts/build_in_container.sh"]
