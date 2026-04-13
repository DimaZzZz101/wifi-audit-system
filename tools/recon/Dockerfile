# Долгоживущий инструментальный контейнер для сканирования Wi-Fi сетей.
# airodump-ng - сбор AP/STA данных + pcap захват.
# tshark - парсинг pcap (IE/tagged params из beacon frames).
# Запускается с network_mode: host, cap_add: [NET_ADMIN, NET_RAW].
FROM kalilinux/kali-rolling

RUN apt-get update && apt-get install -y --no-install-recommends \
    aircrack-ng \
    tshark \
    iw \
    python3 \
    reaver \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY recon_scanner.py recon_parser.py /app/

ENTRYPOINT ["python3", "/app/recon_scanner.py"]
