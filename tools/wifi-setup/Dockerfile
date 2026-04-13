# Короткоживущий tool для настройки Wi-Fi адаптера.
# Возможности: info (расширенный), режим monitor/managed, канал, txpower, MAC.
# Запускается с network_mode: host, cap_add: [NET_ADMIN].
FROM alpine:3.19

RUN apk add --no-cache iw iproute2 python3 eudev

WORKDIR /app
COPY wifi_setup.py .

ENTRYPOINT ["python3", "/app/wifi_setup.py"]
