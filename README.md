# docker-updater

## 简介

`docker-updater` 是一个 Python 脚本，旨在自动化 Docker 和 Podman Compose 项目的容器镜像更新流程。它使用 Skopeo 工具直接获取最新的镜像 SHA256 digest，然后智能地更新 `docker-compose.yml` 文件，并自动重新部署容器，确保你的容器镜像始终使用最新版本。

## 主要特点

- **跨平台兼容性**：自动检测并兼容 Podman Compose、新版 Docker Compose 和旧版 `docker-compose`。

- **自动化更新**：使用 Skopeo 工具直接获取最新镜像 digest，无需手动查询。

- **镜像源配置**：支持配置镜像源，加速镜像获取过程，并支持自动 fallback 功能。

- **智能 YAML 处理**：使用 `ruamel.yaml` 库，在更新 `image` 字段时保留文件中原有的注释和格式。

- **完整部署流程**：自动执行 `pull` → `down` → 更新配置文件 → `up` 的完整部署流程。

- **非侵入式**：仅更新配置文件中指定了 `image` 的服务，跳过本地镜像。

- **彩色日志输出**：通过 ANSI 颜色代码提供清晰的日志，方便快速识别成功、警告和错误信息。

- **自动清理**：完成更新后，自动修剪旧版本镜像，释放磁盘空间。

## 先决条件

在运行此脚本之前，请确保你的系统已安装以下任一套工具：

1. **Podman** 和 **podman-compose**

2. **Docker** 和新版 `docker compose` 插件

3. **旧版 `docker-compose`**

此外，你还需要安装：

- **Skopeo**：用于获取镜像的 SHA256 digest
  - Windows: `choco install skopeo`
  - Linux: `sudo apt install skopeo` (或其他包管理器)
  - macOS: `brew install skopeo`

- **Python 库**：

```
pip3 install ruamel.yaml
```

## 配置

脚本首次运行时会自动创建 `config.json` 配置文件，你可以根据需要修改它。配置文件格式如下：

```json
{
  "mirrors": {
    "docker.io": ["docker.1ms.run"]
  }
}
```

- **`mirrors`**：镜像源配置，用于加速镜像获取
  - 键：原始镜像仓库地址（如 `docker.io`）
  - 值：镜像源地址数组，脚本会按顺序尝试使用这些镜像源，最后会尝试原始仓库

## 使用方法

1. 确保已安装所有先决条件。

2. 赋予脚本执行权限（Linux/macOS）：

```
chmod +x docker-updater.py
```

3. 直接运行脚本。脚本会自动查找并更新所有正在运行的 Compose 项目：

```
# Linux/macOS
./docker-updater.py

# Windows
python docker-updater.py
```

## 工作流程

1. **加载配置**：读取 `config.json` 文件中的镜像源配置。

2. **检测工具**：检测系统上可用的容器工具（Podman 或 Docker）。

3. **检测 Skopeo**：确保 Skopeo 工具已安装。

4. **获取项目**：自动发现所有正在运行的 Compose 项目。

5. **处理项目**：对每个项目执行以下操作：
   - 分析 `docker-compose.yml` 文件中的服务和镜像
   - 使用 Skopeo 获取每个镜像的最新 digest
   - 比较本地 digest 和远程最新 digest
   - 对需要更新的镜像执行完整部署流程

6. **清理**：修剪旧版本镜像，释放磁盘空间。

## 注意事项

- 脚本会自动跳过 `localhost` 或 `127.0.0.1` 下的本地镜像。
- 脚本在更新过程中会创建备份文件，以防更新失败时可以回滚。
- 若所有镜像源都失败，脚本会尝试使用原始镜像仓库。

## 贡献

欢迎提交 PR 或提出 Issue 来改进这个脚本。
