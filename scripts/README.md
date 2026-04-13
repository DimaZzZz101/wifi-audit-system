# Скрипты

## wifi-rename-link.sh

Создание **udev-правила** для переименования Wi-Fi интерфейса **по ID_PATH** (физическое устройство), не по MAC. Устойчиво к смене MAC-адреса.

**Важно:** правило содержит `KERNEL!="*mon"` - интерфейсы в режиме monitor (`wifi0mon`) **не переименовываются**, иначе wifi_setup не сможет переключать managed<->monitor.

**Использование** (первый аргумент - текущее имя интерфейса из `ip link` или `iwconfig`):

```bash
sudo ./wifi-rename-link.sh wlx00c0cab6938b wifi0
sudo ./wifi-rename-link.sh wlx00c0cab4ae2d wifi1
```

Скрипт автоматически:
- удаляет старые правила (70-wifiaudit, 10-wifi-*.link)
- создаёт udev-правило (85-wifiaudit-*)
- применяет изменения (udevadm control, trigger, ip link up/down)

При необходимости: `sudo systemctl restart NetworkManager`.
