# atkdl16-cli

面向正点原子 **DL16** 逻辑分析仪的非官方命令行工具与 Python 协议实现。它不依赖原厂 GUI，已经在真实 DL16 上验证 PWM、普通/Buffer/RLE 采集、多通道、边沿触发、长时间 Stream、导出和持久会话。

> 当前只以 DL16 为目标；不承诺兼容 DL32 或其他型号。协议来自对 Linux 原厂程序的净室分析和硬件实测。

## 安装

要求 Linux、Python 3.10+ 和 libusb：

```bash
python3 -m pip install '.[usb]'
atkdl16 --dry-run list
atkdl16 list
```

无 USB 权限时安装仓库中的 udev 规则，然后重新插拔设备：

```bash
sudo install -m 0644 udev/99-atk-dl16.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
```

后端不会调用已确认会破坏 DL16 链路的 `SET_CONFIGURATION`。CLI 可恢复“设备先插入、程序后启动”的 FFCC 链路，无需为每次采集手工热插拔。

## 常用命令

### PWM

PWM0/PWM1 支持原厂范围 1 Hz～20 MHz，占空比为 0～100：

```bash
atkdl16 pwm start --channel 0 --freq 1000000 --duty 75
atkdl16 pwm stop --channel 0
```

### 一次采集

普通 Stream、Buffer 和 Buffer+RLE 使用同一个入口：

```bash
# Stream，多通道
atkdl16 capture run --channels 6,7 \
  --sample-rate 20000000 --set-time 10 \
  --trigger-position 0 --threshold 1.2 --output-dir capture

# Buffer + 上升沿触发
atkdl16 capture run --buffer --channels 6,7 \
  --sample-rate 250000000 --set-time 1 \
  --trigger rising --trigger-channel 6 --trigger-position 50 \
  --threshold 1.2 --output-dir triggered

# Buffer 硬件 RLE
atkdl16 capture run --buffer --rle --channels 0,1,2,3,4,5,6,7 \
  --sample-rate 250000000 --set-time 525 \
  --trigger-position 0 --threshold 1.2 --output-dir capture-rle
```

`--sample-index` 通常不必填写，CLI 会自动选择。DL16 已验证采样率为 1、2、4、5、10、20、40、50、100、200、250、500 MHz。Stream 限制为：20 MHz 最多 16 通道、50 MHz 最多 6 通道、100 MHz 最多 3 通道；Buffer 在 500 MHz 下仍可用 16 通道。

### 增量 Stream

数据在接收时直接写盘，不把整个采集保存在 Python 内存中：

```bash
# 有限时长
atkdl16 capture stream --channels 6,7 --sample-rate 20000000 \
  --duration 30 --threshold 1.2 --output-dir long-capture

# 不给 duration：运行至 Ctrl-C 或 40 位深度上限；Ctrl-C 会保留各通道对齐的数据
atkdl16 capture stream --channels 6,7 --sample-rate 20000000 \
  --output-dir until-interrupt
```

DL16 不支持原厂手册中仅供 DL32 使用的滚动显示模式；这里实现的是 DL16 Stream 的增量、可中断落盘。

### 持久会话

独立 CLI 进程会重新初始化 USB/FPGA。需要连续设置两个 PWM，再采集回环信号时，应使用一个 JSONL 会话：

```json
{"op":"pwm_start","channel":0,"frequency_hz":1000000,"duty_percent":75}
{"op":"pwm_start","channel":1,"frequency_hz":2000000,"duty_percent":25}
{"op":"stream","channels":[6,7],"sample_rate_hz":100000000,"duration_seconds":0.01,"threshold":1.2,"output_dir":"capture"}
{"op":"quit"}
```

```bash
atkdl16 session --commands commands.jsonl
# 或通过 stdin/stdout 与自己的程序保持长连接
atkdl16 session
```

每条响应也是一行 JSON。也可直接使用 `atkdl16_cli.session.Dl16Session` Python API。

### 导出

```bash
atkdl16 capture export --input-dir capture --format csv   --output capture.csv
atkdl16 capture export --input-dir capture --format edges --output edges.csv
atkdl16 capture export --input-dir capture --format vcd   --output capture.vcd
```

- `csv`：每个采样点一行。
- `edges`：只写电平变化，适合长时间低频信号。
- `vcd`：1 ns 时间尺度，可由 GTKWave 等工具读取。

导出器按通道使用内存映射并逐行写出，不复制整个采集。

### UART / I2C / SPI 离线解码

```bash
atkdl16 capture uart --input-dir capture --channel 6 --baud 115200 \
  --data-bits 8 --parity none --stop-bits 1 --output uart.json

atkdl16 capture i2c --input-dir capture --scl 0 --sda 1 --output i2c.json

atkdl16 capture spi --input-dir capture --clock 2 --mosi 3 --miso 4 --cs 5 \
  --mode 0 --bits-per-word 8 --bit-order msb --output spi.json
```

解码结果同时输出到 stdout；`--output` 可选。UART 支持 5～9 数据位、无/奇/偶校验、1/2 停止位和反相；SPI 支持模式 0～3、MSB/LSB 和可选 MOSI/MISO/CS。

## 采集目录格式

```text
capture/
  manifest.json       采样率、深度、通道、触发和模式元数据
  wire.bin            无损保存的 DL16 接收包
  channel-06.bin      每字节 8 个样本，时间顺序为 LSB-first
  channel-07.bin
```

## 验证状态

- PWM0/PWM1：1 Hz～20 MHz；频率、占空比和连续稳定性矩阵。
- 触发：上升沿/下降沿在 50% 位置硬件实测。
- 多通道：4/8/16 通道普通 Buffer 与 RLE 压力采集。
- RLE：4/8/16 通道各展开约 131.25 MB，CH6/CH7 PWM 解码正确。
- Stream：真实设备 20 MHz 双通道 Ctrl-C 后保留 52,230,528 个对齐样本/通道；100 MHz 双通道持久会话准确测得 1 MHz/75% 和 2 MHz/约 25% 回环。
- 自动测试：协议构造、USB 传输、采集、RLE、导出、会话和三种协议解码。

运行测试：

```bash
python3 -m pip install '.[test]'
pytest -q
```

协议字段和逆向证据见 [`docs/protocol/protocol.md`](docs/protocol/protocol.md) 与 [`docs/protocol/evidence-summary.md`](docs/protocol/evidence-summary.md)。

## 已知边界

- 只验证 DL16，不实现其他型号适配。
- 采样 index 7 在三次全新硬件尝试中都没有返回 type-1 数据，因此自动表故意不使用它。
- UART/I2C/SPI 是离线逻辑层解码器，不包含原厂 GUI 的所有高级显示和协议插件。
- 固件写入具有变砖风险，不属于常规采集工作流；不要在未确认固件、目标和传输模式时使用相关实验命令。
