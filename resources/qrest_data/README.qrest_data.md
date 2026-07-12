# qREST_Data项目

**版本**: v1.0.1
**最后更新**: 2026-04-16

本项目是qREST(Quick Response Evaluation for Safety Tagging)的一个子项目，主要负责数据管理。主要定义了两个协议：数据存储协议和数据传输协议。并提供一些简单的工具用于做处理和转换。

## 1. 数据协议

### 1.1 数据存储协议

数据存储协议定义了qREST数据文件的结构和格式规范，见[数据存储协议](doc/qREST_DataStorage.md)。

### 1.2 数据传输协议

数据传输协议定义了qREST数据在不同系统之间传输的格式和规范，见[数据传输协议](doc/qREST_DataTransfer.md)。

## 2. 读写工具

### 2.1 qrest文件生成和读取

为了方便生成测试及样例数据，编写了两个小工具用于生成和读取qrest数据文件：

#### qREST数据生成 (data_generator)

用于生成符合数据存储协议的qrest数据文件，使用方式如下：

```bash
data_generator <metadata.json> <data.txt> <output.qrest>
```

其中：
- `<metadata.json>`：包含数据元信息的JSON文件。
- `<data.txt>`：包含实际数据内容的文本文件。
- `<output.qrest>`：生成的qrest数据文件。

#### qREST数据读取 (data_loader)

用于读取和解析qrest数据文件，使用方式如下：

```bash
data_loader <input.qrest> <metadata.json> <data.txt> 
```

其中：
- `<input.qrest>`：要读取的qrest数据文件。
- `<data.txt>`：导出的数据内容文本文件。
- `<metadata.json>`：导出的数据元信息JSON文件。

### 2.2 qrest数据接口 (qrest_data)

提供了一个C语言接口的动态库，用于使用其他语言解析或生成qrest数据格式的字节流。接口定义见[数据接口](doc/qrest_data_lib/interface.md)。