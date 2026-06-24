# Диагностика датчика температуры и влажности

## Текущее состояние

- SKLAD API работает на `http://127.0.0.1:8120`.
- Датчик в API создан как `sensor_device.id = 1`.
- USB-устройство определяется как CH340: `/dev/serial/by-id/usb-1a86_USB_Serial-if00-port0`.
- Пользователь `tassay` входит в группу `dialout`.
- Мост умеет:
  - читать текстовые строки;
  - делать Arduino-style DTR/RTS reset;
  - отправлять команды с `lf`, `cr`, `crlf`;
  - печатать raw hex/text;
  - опрашивать Modbus RTU read-only запросами.

## Что показала диагностика

- При обычном чтении текстовых строк датчик молчит.
- При Arduino-style reset датчик не печатает осмысленный текст.
- При командах `?`, `READ`, `read`, `GET`, `DHT` осмысленного ответа нет.
- При baud `19200`, `38400`, `57600`, `115200` приходят повторяющиеся байты вроде `ff`, `fd`, `f9`, `2e`; это похоже на неверный baud/parity, шум линии, инвертированный сигнал или неподходящий интерфейс, а не на нормальные измерения.
- Безопасный Modbus RTU scan не нашел валидных ответов.

## Нужен ли Arduino IDE

Arduino IDE не нужна для простого чтения данных из уже прошитого контроллера: это делает `scripts/sklad_serial_sensor_bridge.py`.

Arduino IDE или `arduino-cli` нужны, если:

- на плату надо загрузить скетч;
- неизвестно, какая прошивка сейчас на контроллере;
- у коллеги работало потому, что у него была открыта конкретная прошивка/Serial Monitor с конкретными настройками;
- надо узнать, какой baud и какие строки печатает скетч.

## Что нужно уточнить у коллеги

1. Модель датчика и платы: Arduino Nano/Uno/ESP/USB-RS485/другое.
2. Какой baud был выбран в Serial Monitor.
3. Какой line ending был выбран: No line ending, Newline, Carriage return, Both NL & CR.
4. Печатал ли датчик данные сам или надо было отправить команду.
5. Какая команда отправлялась, если она была.
6. Есть ли скетч `.ino`, который был загружен в плату.
7. Фото подключения проводов: питание, GND, TX/RX или A/B для RS485.

## Команды

Запуск API:

```bash
scripts/start_sklad_api.sh
```

Диагностика датчика:

```bash
scripts/diagnose_sklad_sensor.sh
```

Raw sniff как Serial Monitor:

```bash
scripts/sklad_serial_sensor_bridge.py \
  --port /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --baud 9600 \
  --device-id 1 \
  --sniff-raw \
  --sniff-seconds 8 \
  --arduino-reset \
  --warmup-seconds 2
```

Если известна команда:

```bash
scripts/sklad_serial_sensor_bridge.py \
  --port /dev/serial/by-id/usb-1a86_USB_Serial-if00-port0 \
  --baud 9600 \
  --device-id 1 \
  --sniff-raw \
  --sniff-seconds 8 \
  --arduino-reset \
  --warmup-seconds 2 \
  --write-command READ \
  --line-ending lf
```
