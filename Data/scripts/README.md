# 本机校验与导出

验证脚本依赖 Python + Pillow；当前本机已提供可用运行时。

```powershell
& 'C:\Users\Lenovo\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' 'C:\Users\Lenovo\Desktop\HarnessIR_Manual\Data\scripts\validate_dataset.py'
```

`validate_dataset.py` 读取输入/GT，不改图片，仅重写根目录 verification_report.json。`export_harness.py` 只使用标准库，从相对路径队列重导出本机绝对路径官方格式manifest，不加入GT。照片数据和模型环境分别管理，本目录不安装或运行HarnessIR。
