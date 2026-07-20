# atkdl16-cli

面向正点原子 **DL16** 逻辑分析仪的非官方命令行工具与 Python 协议实现。它不依赖原厂 GUI，已经在真实 DL16 上验证 PWM、普通/Buffer/RLE 采集、多通道、边沿触发、长时间 Stream、导出和持久会话。

> 当前只以 DL16 为目标；不承诺兼容 DL32 或其他型号。协议来自对 Linux 原厂程序的净室分析和硬件实测。

## 安装

要求 Linux、Python 3.10+ 和 libusb：

```bash
python3 -m pip install '.[usb]'
atkdl16 --dry-run list
atkdl16 list
atkdl16 info
```

需要 CAN、LIN、JTAG、1-Wire 等扩展协议解码时，安装 sigrok 解码库：

```bash
sudo apt install sigrok-cli
atkdl16 capture sigrok --list
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

普通 Stream、Buffer 和 Buffer+RLE 使用同一个入口。阈值默认 1.2 V，触发位置默认 0%，无需重复填写：

```bash
# Stream，多通道
atkdl16 capture run --channels 7,15 \
  --sample-rate 20000000 --set-time 10 \
  --output-dir capture

# Buffer + 上升沿触发
atkdl16 capture run --buffer --channels 7,15 \
  --sample-rate 250000000 --set-time 1 \
  --trigger rising --trigger-channel 7 --trigger-position 50 \
  --output-dir triggered

# Buffer 硬件 RLE
atkdl16 capture run --buffer --rle --channels 7,15 \
  --sample-rate 250000000 --set-time 525 \
  --output-dir capture-rle
```

`--sample-index` 通常不必填写，CLI 会自动选择。DL16 已验证采样率为 1、2、4、5、10、20、40、50、100、200、250、500 MHz。Stream 限制为：20 MHz 最多 16 通道、50 MHz 最多 6 通道、100 MHz 最多 3 通道；Buffer 在 500 MHz 下仍可用 16 通道。采集默认拒绝覆盖已有的 `manifest.json`、`wire.bin` 或通道文件；确认替换时使用 `--force`。

单通道触发支持 `rising`、`high`、`falling`、`low` 和 `either`。多通道逻辑与使用：

```bash
atkdl16 capture run --buffer --channels 7,15 \
  --sample-rate 250000000 --set-time 1 \
  --trigger-states 7=high,15=low --trigger-position 50 \
  --trigger-timeout 10 --output-dir triggered
```

触发默认最多等待首个样本 30 秒，避免条件永远不满足时无限挂起。

### 增量 Stream

数据在接收时直接写盘，不把整个采集保存在 Python 内存中：

```bash
# 有限时长
atkdl16 capture stream --channels 7,15 --sample-rate 20000000 \
  --duration 30 --threshold 1.2 --output-dir long-capture

# 不给 duration：运行至 Ctrl-C 或 40 位深度上限；Ctrl-C 会保留各通道对齐的数据
atkdl16 capture stream --channels 7,15 --sample-rate 20000000 \
  --output-dir until-interrupt
```

DL16 不支持原厂手册中仅供 DL32 使用的滚动显示模式；这里实现的是 DL16 Stream 的增量、可中断落盘。

### 持久会话

独立 CLI 进程会重新初始化 USB/FPGA。需要连续设置两个 PWM，再采集回环信号时，应使用一个 JSONL 会话：

```json
{"op":"pwm_start","channel":0,"frequency_hz":1000000,"duty_percent":75}
{"op":"pwm_start","channel":1,"frequency_hz":2000000,"duty_percent":25}
{"op":"capture","channels":[7,15],"sample_rate_hz":250000000,"duration_ms":1,"buffer":true,"output_dir":"capture"}
{"op":"quit"}
```

```bash
atkdl16 session --commands commands.jsonl
# 或通过 stdin/stdout 与自己的程序保持长连接
atkdl16 session
```

每条响应也是一行 JSON。会话支持 `pwm_start`、`pwm_stop`、`stream`、`capture`、`stop` 和 `quit`；`capture` 还接受 `rle`、`trigger`、`trigger_channel`、`trigger_states`、`trigger_position_percent`、`trigger_timeout_seconds` 与 `overwrite`。也可直接使用 `atkdl16_cli.session.Dl16Session` Python API。

### 频率与占空比测量

```bash
atkdl16 capture measure --input-dir capture --channel 7
atkdl16 capture measure --input-dir capture --channel 15
```

测量使用完整上升沿周期，并输出中位/最小/最大频率、占空比、周期样本数、上升/下降沿数及有效周期数。实现按字节扫描内存映射文件，周期统计使用直方图，不会为每个边沿保存 Python 对象。

### 毛刺过滤

过滤不超过指定采样周期数的短脉冲，并写入新的派生采集目录，不修改源数据：

```bash
atkdl16 capture filter --input-dir capture --output-dir filtered \
  --max-samples 2 --channels 7,15
```

### 数据搜索

搜索条件与简单触发一致，可组合多个通道并限制样本范围和结果数量：

```bash
atkdl16 capture search --input-dir capture \
  --conditions 7=rising,15=high --start-sample 0 --limit 100
```

输出包含样本序号和纳秒时间；大文件按字节位掩码扫描，不展开为逐样本 Python 列表。

### 扩展协议解码

原生 UART/I2C/SPI 之外可调用 sigrok 的成熟协议库：

```bash
atkdl16 capture sigrok --show can
atkdl16 capture sigrok --input-dir capture --decoder uart \
  --channel rx=7 --option baudrate=115200 --option format=hex
```

`--channel` 和 `--option` 均可重复。CLI 会临时生成 VCD、运行解码器并清理中间文件；`--output` 可保存文本结果。

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
  channel-07.bin
  channel-15.bin      每字节 8 个样本，时间顺序为 LSB-first
```

## 验证状态

- PWM0/PWM1：1 Hz～20 MHz；频率、占空比和连续稳定性矩阵。
- 触发：上升沿/下降沿在 50% 位置硬件实测。
- 多通道：4/8/16 通道普通 Buffer 与 RLE 压力采集。
- RLE：4/8/16 通道压力采集；当前 CH7/CH15 双通道 131,250,000 样本/通道再次通过。
- Stream：真实设备 20 MHz 双通道 Ctrl-C 后保留 52,230,528 个对齐样本/通道；当前 100 MHz 持久会话测得 CH7 1 MHz/75%，CH15 2 MHz/24%。
- 有限采集也按通道增量落盘；32.8 MB 双通道 RLE 实测峰值 RSS 从约 98 MB 降至约 20 MB。
- 自动测试：193 项，覆盖协议构造、USB 传输、全部简单触发、触发超时、采集、RLE、目录保护、测量、毛刺过滤、数据搜索、sigrok 桥接、导出、会话和三种原生协议解码。

运行测试：

```bash
python3 -m pip install '.[test]'
pytest -q
```

协议字段和逆向证据见 [`docs/protocol/protocol.md`](docs/protocol/protocol.md) 与 [`docs/protocol/evidence-summary.md`](docs/protocol/evidence-summary.md)。

## Codex Skill

仓库内的 `skills/dl16-cli` 由 Git 跟踪。克隆后在仓库根目录执行：

```bash
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
ln -sfn "$(pwd)/skills/dl16-cli" "${CODEX_HOME:-$HOME/.codex}/skills/dl16-cli"
```

## 已知边界

- 只验证 DL16，不实现其他型号适配。
- 采样 index 7 在三次全新硬件尝试中都没有返回 type-1 数据，因此自动表故意不使用它。
- 原生 UART/I2C/SPI 解码器不包含原厂 GUI 的显示层；其他协议通过系统 sigrok 库扩展，原厂私有/自定义解码脚本不能直接复用。
