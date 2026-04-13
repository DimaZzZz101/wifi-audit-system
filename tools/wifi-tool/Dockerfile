# Короткоживущий tool для сбора информации о Wi-Fi интерфейсах (iw dev).
# Запускается с network_mode: host и минимальными capabilities.
FROM alpine:3.19

RUN apk add --no-cache iw python3

WORKDIR /app
COPY wifi_info.py .

ENTRYPOINT ["python3", "/app/wifi_info.py"]
