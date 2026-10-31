# Windows 开发与使用

目标：Windows 11 x64，Edge / Chrome。ARM64 Windows 与真实 GPU、摄像头、麦克风仍需独立验收。

## 首次安装

登录有权限的 GitHub 账号，克隆 **源码仓库**（名称不带 `-showcase`）。展示仓库只有介绍，不能运行。

```powershell
git clone https://github.com/oniszczukthommy-wq/film-shot-agent.git
cd film-shot-agent
# 先安装 Python 3.12 x64，并启用 Python Launcher（py）
powershell -NoProfile -ExecutionPolicy Bypass -File .\Windows.ps1 Setup
powershell -NoProfile -ExecutionPolicy Bypass -File .\Windows.ps1 Test
```

脚本只对这一次执行放行，不修改系统执行策略。安装命令失败会停止；既有 `.env` 不会被覆盖。

## 日常启动

双击 `Start-Windows.cmd`，或运行：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Windows.ps1 Start
```

在浏览器打开 http://127.0.0.1:8000/ 。终端按 Ctrl+C 停止。

需安装 Node.js 22 以运行附带前端测试（服务器本身只需要 Python）。Setup 通过 uv.lock 安装锁定依赖。编辑 `.env` 配置模型、TMDB 和搜索服务。预置镜头索引可用；原影片文件需自行下载，剪辑前先安装 FFmpeg。原 scripts/fetch_demo.sh 可在 WSL2 中运行，下载的媒体放回 data/library/raw/。

## 继续开发与迁移

- 在 Windows 用 VS Code 等编辑器打开源码目录，Python 解释器选择 `.venv\Scripts\python.exe`。
- 用 Git 同步源码；虚拟环境、node_modules、Mac 的二进制工具都要重新安装，不能直接复制。
- 迁移前停止旧服务，单独备份整个 `data/`、用户工程、上传素材与相关数据库附属文件。新机器恢复后保留原备份，再核对项目数量和附件。
- 密钥只在新机器本机填写；不要提交 `.env`、个人数据或模型权重。
- 后续更新执行 `git pull --ff-only`，重新 Setup 与 Test。若已有本机改动，先保存提交再更新。

## 验证边界

`.github/workflows/windows.yml` 在 Windows runner 上执行同一安装与测试入口。
自动测试不调用付费模型，不代表真实模型质量、GPU 加速或硬件输入已经验收。具体结果看仓库 Actions；首次运行失败时不得视为已支持。
