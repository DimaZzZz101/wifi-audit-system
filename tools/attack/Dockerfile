# Unified attack container: all Wi-Fi auditing tools in a single image.
# Runs with --network host, NET_ADMIN + NET_RAW capabilities.

FROM kalilinux/kali-rolling AS hcxdumptool-builder

ENV DEBIAN_FRONTEND=noninteractive
ARG DEB_RETRIES=5
ARG HCXDUMPTOOL_TAG=6.2.9

RUN set -eux; \
    echo 'deb http://http.kali.org/kali kali-rolling main contrib non-free non-free-firmware' > /etc/apt/sources.list; \
    apt-get update -o Acquire::Retries=${DEB_RETRIES}; \
    apt-get install -y --no-install-recommends \
        ca-certificates git make gcc pkg-config \
        libcurl4-openssl-dev libssl-dev zlib1g-dev; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN set -eux; \
    git clone --depth 1 --branch "${HCXDUMPTOOL_TAG}" https://github.com/ZerBea/hcxdumptool.git; \
    cd hcxdumptool; \
    make; \
    install -Dm755 hcxdumptool /out/usr/local/bin/hcxdumptool; \
    if [ -f hcxpioff ]; then install -Dm755 hcxpioff /out/usr/local/bin/hcxpioff; fi


FROM kalilinux/kali-rolling

ENV DEBIAN_FRONTEND=noninteractive
ARG DEB_RETRIES=5

RUN set -eux; \
    echo 'deb http://http.kali.org/kali kali-rolling main contrib non-free non-free-firmware' > /etc/apt/sources.list; \
    apt-get update -o Acquire::Retries=${DEB_RETRIES}; \
    apt-get install -y --no-install-recommends \
        python3 python3-pip python3-setuptools \
        libpcap0.8 libsqlite3-0 libnl-3-200 libnl-genl-3-200 libcurl4 \
        wireless-tools net-tools iw iproute2 ethtool usbutils pciutils rfkill kmod \
        tshark macchanger sqlite3 ca-certificates \
        aircrack-ng reaver bully hcxtools \
        procps hostapd-mana mdk4 tcpdump; \
    rm -rf /var/lib/apt/lists/*

COPY --from=hcxdumptool-builder /out/ /

RUN set -eux; \
    hcxdumptool -v || true; \
    find /usr/local -name "*.la" -delete || true; \
    find /usr/local -name "*.a" -delete || true; \
    rm -rf /usr/local/share/man /usr/local/share/doc /usr/local/include || true; \
    apt-get clean || true; rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

ENV PATH="/usr/local/sbin:/usr/local/bin:${PATH}"

WORKDIR /app
COPY attack_runner.py /app/
COPY _log_util.py /app/
COPY handlers/ /app/handlers/

ENTRYPOINT ["python3", "/app/attack_runner.py"]
