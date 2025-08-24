# docker-updater

## 简介

`docker-updater` 是一个 Python 脚本，旨在自动化 Docker 和 Podman Compose 项目的容器镜像更新流程。它通过调用一个可配置的 API 来获取最新的镜像 SHA256 digest，然后智能地更新 `docker-compose.yml` 文件，并自动重新部署容器，确保你的“latest”标签真正指向最新版本。

## 主要特点

* **跨平台兼容性**：自动检测并兼容 Podman Compose、新版 Docker Compose 和旧版 `docker-compose`。

* **自动化更新**：从外部 API 获取最新镜像 digest，无需手动查询。

* **智能 YAML 处理**：使用 `ruamel.yaml` 库，在更新 `image` 字段时保留文件中原有的注释和格式。

* **自动部署**：更新文件后，自动运行 `docker compose up -d` 命令来重新部署服务。

* **非侵入式**：仅更新配置文件中指定了 `image` 的服务。

* **彩色日志输出**：通过 ANSI 颜色代码提供清晰的日志，方便快速识别成功、警告和错误信息。

## 先决条件

在运行此脚本之前，请确保你的系统已安装以下任一套工具：

1. **Podman** 和 **podman-compose**

2. **Docker** 和新版 `docker compose` 插件

3. **旧版 `docker-compose`**

此外，你还需要安装以下 Python 库。

```
pip3 install requests ruamel.yaml
```

## 配置

在使用脚本之前，你必须配置 API 域名。打开脚本文件，找到[以下行](https://github.com/Nyasers/docker-updater/blob/main/docker-updater.py#L23-L25)并填写你的 API 域名：

```
# TODO: 请在此处填写你的 API 域名，例如 "https://api.example.com"。
# 这个 API 用于根据镜像名和标签获取其最新的 digest 值。
DIGEST_API_BASE_URL = ""
```

这个 API 应该能够根据镜像名称和标签返回其最新的 SHA256 digest。

## Cloudflare Workers 配置

此项目附带一个 `worker.js` 脚本，用于在 Cloudflare Workers 上搭建镜像 digest 的查询 API。

1. 请将 `worker.js` 部署到你的 Cloudflare Workers。

2. 部署成功后，你将获得一个 Workers 域名，例如 `https://api.example.com`。

3. 将此域名完整地填入上方 Python 脚本的 `DIGEST_API_BASE_URL` 变量中。

## API 接口说明

脚本会向以下格式的 URL 发送 GET 请求来获取镜像 digest：
`[DIGEST_API_BASE_URL]/{user}/{repo}/{tag}`

* **`{user}`**: 镜像的用户或组织名。

* **`{repo}`**: 镜像的仓库名。

* **`{tag}`**: 镜像的标签，如果为空，则默认为 `latest`。

例如，对于镜像 `nginx:latest`，脚本会请求 `https://api.example.com/library/nginx/latest`。
对于镜像 `myuser/myimage:v1.0`，脚本会请求 `https://api.example.com/myuser/myimage/v1.0`。

API 预期返回一个纯文本响应，内容为镜像的最新 SHA256 digest，例如：`sha256:abcdef123456...`。

## 使用方法

1. 配置 `DIGEST_API_BASE_URL`。

2. 赋予脚本执行权限：

```
chmod +x docker-updater.py
```

3. 直接运行脚本。脚本会自动查找并更新所有正在运行的 Compose 项目：

```
./docker-updater.py
```

## 贡献

欢迎提交 PR 或提出 Issue 来改进这个脚本。
