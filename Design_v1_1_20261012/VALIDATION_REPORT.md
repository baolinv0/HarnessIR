# v1.1 本地工具方案包验证

2026-10-12。交付是更新设计与协议资料，模型/worker尚未部署。

文件验证通过：18份Schema、18份合法协议夹具、7个Prompt模板、25个官方快照哈希、15个文档相对链接。通用错误夹具10项均拒绝。新增本地工具错误夹具10项均拒绝；缓存绑定与相同合同检查4项、源图/权重/类别/参数/backend/precision/adapter等变化的缓存失效检查10项通过。合成坐标和标签关联检查通过。

CPU profile为队列1、batch1、线程2、每任务进程退出；registry标明未部署。不把这些配置检查当作真实资源测试。

验证范围不包含：真实模型部署、用户Windows读写、安装脚本执行、ChatGPT图像编辑、Worker/Scheduler应用实现、真实照片效果、GPU迁移。新版预算为初始保护值，不能保证7.9GB机器能运行所有SDK。

复查：

```powershell
python -m pip install -r scripts/requirements-validation.txt
python scripts/validate_package.py
python scripts/validate_local_tools_design.py
```

源码编译、PACKAGE_MANIFEST文件哈希和ZIP CRC在最终打包时另外检查。官方快照保持MIT许可证；上游模型环境资料为核验链接，尚未成为本机SDK锁。
