#!/usr/bin/env python3
import subprocess
import json
import os
import re
import shutil
import sys
from ruamel.yaml import YAML
from enum import Enum


# 定义一个枚举类来管理 ANSI 颜色代码
class COLORS(str, Enum):
    """
    用于在控制台输出中着色的 ANSI 颜色代码。
    """

    RESET = "\033[0m"
    GREEN = "\033[92m"  # 成功
    YELLOW = "\033[93m"  # 警告
    RED = "\033[91m"  # 错误
    CYAN = "\033[96m"  # 信息/标题
    BLUE = "\033[94m"  # 正在进行的操作


# ---
# 全局配置类和实例
# ---
class AppConfig:
    """封装应用程序配置的容器。"""

    def __init__(self):
        self.container_tool = None
        self.mirrors = {}


# 在模块级别创建一个全局配置实例
Config = AppConfig()


def load_config():
    """
    从 config.json 文件加载配置，并将其存储到配置实例中。
    如果文件不存在，将创建一个空的模板文件。
    """
    # 获取脚本所在的目录，而不是当前工作目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_file = os.path.join(script_dir, "config.json")

    # 定义配置模板内容，包含镜像源配置示例（数组格式，支持自动fallback）
    template_content = {
        "mirrors": {
            "docker.io": [
                "docker.1ms.run",
            ],
        }
    }

    print(f"{COLORS.CYAN}正在加载配置文件 '{config_file}'...{COLORS.RESET}")

    if not os.path.exists(config_file):
        print(
            f"{COLORS.YELLOW}警告: 配置文件 '{config_file}' 不存在。正在为您创建一个模板文件...{COLORS.RESET}"
        )
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                file_content = json.dumps(
                    template_content, indent=4, ensure_ascii=False
                )
                f.write(file_content)

            print(
                f"{COLORS.GREEN}模板文件已创建。您可以在配置文件中定义镜像源。{COLORS.RESET}"
            )
        except Exception as e:
            print(f"{COLORS.RED}错误: 创建模板文件失败: {e}{COLORS.RESET}")
            sys.exit(1)

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 加载镜像源配置
        Config.mirrors = data.get("mirrors", {})
        if Config.mirrors:
            print(
                f"{COLORS.GREEN}加载到 {len(Config.mirrors)} 个镜像源配置。{COLORS.RESET}"
            )
        else:
            print(f"{COLORS.YELLOW}未配置镜像源，将使用默认源。{COLORS.RESET}")
    except json.JSONDecodeError as e:
        print(
            f"{COLORS.RED}错误: 解析配置文件 '{config_file}' 失败: {e}。请检查 JSON 格式是否正确。{COLORS.RESET}"
        )
        sys.exit(1)
    except Exception as e:
        print(
            f"{COLORS.RED}错误: 读取配置文件 '{config_file}' 时发生错误: {e}{COLORS.RESET}"
        )
        sys.exit(1)

    print(f"{COLORS.GREEN}配置加载成功。{COLORS.RESET}")


def run_docker(command, cwd=None, capture_output=False):
    """
    辅助函数：根据配置中的容器工具来运行 shell 命令。
    此函数统一使用 subprocess.Popen，并始终关闭输入流。
    Args:
        command (list): 要执行的命令列表。
                          例如：对于 'docker pull'，输入 ['pull', 'nginx:latest']
                          对于 'docker compose up'，输入 ['compose', 'up', '-d']
        cwd (str, optional): 命令执行的工作目录。默认为 None (当前目录)。
        capture_output (bool, optional): 是否捕获输出并返回。如果为 False，则将输出流式传输到控制台。
                                         默认为 False。
    Returns:
        tuple: (str, list) - (命令的标准输出, 实际执行的命令列表)，如果命令执行失败则返回 (None, actual_command)。
    """
    actual_command = []

    # 根据配置中的 CONTAINER_TOOL 的值来决定使用哪个容器工具
    if command[0] == "compose":
        if Config.container_tool == "podman":
            actual_command = ["podman-compose"] + command[1:]
        elif Config.container_tool == "docker-legacy":
            actual_command = ["docker-compose"] + command
        else:  # 'docker'
            actual_command = ["docker", "compose"] + command[1:]
    else:  # 'pull', 'ps', 'inspect', etc.
        if Config.container_tool == "podman":
            actual_command = ["podman"] + command
        else:  # 'docker' or 'docker-legacy'
            actual_command = ["docker"] + command

    print(f"{COLORS.BLUE}正在运行 '{' '.join(actual_command)}'...{COLORS.RESET}")

    try:
        if capture_output:
            process = subprocess.Popen(
                actual_command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            stdout, stderr = process.communicate()
        else:
            process = subprocess.Popen(
                actual_command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=sys.stdout,
                stderr=sys.stderr,
                text=True,
                encoding="utf-8",
            )
            process.wait()
            stdout, stderr = "Command executed successfully with streaming output.", ""

        if process.returncode != 0:
            if capture_output:
                print(
                    f"{COLORS.RED}命令执行失败，返回码: {process.returncode}{COLORS.RESET}"
                )
                print(f"{COLORS.RED}标准输出: {stdout}{COLORS.RESET}")
                print(f"{COLORS.RED}标准错误: {stderr}{COLORS.RESET}")
            else:
                print(
                    f"{COLORS.RED}命令执行失败，返回码: {process.returncode}{COLORS.RESET}"
                )
            return None, actual_command

        return stdout.strip(), actual_command

    except FileNotFoundError:
        print(
            f"{COLORS.RED}错误: 命令 '{actual_command[0]}' 未找到。请确保该工具已安装并添加到 PATH。{COLORS.RESET}"
        )
        return None, actual_command


def check_docker_availability():
    """
    检查系统是存在 Podman、新版 Docker Compose 还是旧版 Docker Compose。
    并将结果设置到配置对象中。
    """
    print(f"{COLORS.CYAN}正在检测可用的容器工具...{COLORS.RESET}")

    # 优先检测 Podman 和 Podman-Compose
    if shutil.which("podman") and shutil.which("podman-compose"):
        Config.container_tool = "podman"
        print(
            f"{COLORS.GREEN}检测到 Podman 和 Podman-Compose。将使用 'podman' 逻辑。{COLORS.RESET}"
        )
        return

    # 其次检测 Docker 和新版/旧版 Docker Compose
    if shutil.which("docker"):
        try:
            # 尝试运行 "docker compose version" 来判断是否是新版
            run_docker(["compose", "version"], capture_output=True)
            Config.container_tool = "docker"
            print(
                f"{COLORS.GREEN}检测到 Docker 和新版 Docker Compose。将使用 'docker' 逻辑。{COLORS.RESET}"
            )
            return
        except Exception:
            pass

        # 如果新版 compose 不存在，则检查旧版
        if shutil.which("docker-compose"):
            Config.container_tool = "docker-legacy"
            print(
                f"{COLORS.GREEN}检测到 Docker 和旧版 docker-compose。将使用 'docker-legacy' 逻辑。{COLORS.RESET}"
            )
            return

    # 如果以上所有检查都失败
    print(
        f"{COLORS.RED}错误: 未找到任何可用的容器工具 (Podman/Podman-Compose、新版或旧版 Docker Compose)。请安装其中一套工具。{COLORS.RESET}"
    )
    sys.exit(1)


def check_skopeo_availability():
    """
    检查系统是否安装了 Skopeo 工具。
    Skopeo 用于获取镜像的元数据，包括 digest 信息。
    """
    print(f"{COLORS.CYAN}正在检测 Skopeo 工具...{COLORS.RESET}")

    if shutil.which("skopeo"):
        print(
            f"{COLORS.GREEN}检测到 Skopeo 工具。将使用 Skopeo 获取镜像 digest。{COLORS.RESET}"
        )
        return True
    else:
        print(f"{COLORS.RED}错误: 未找到 Skopeo 工具。{COLORS.RESET}")
        print(
            f"{COLORS.YELLOW}Skopeo 是获取镜像 digest 所必需的工具。请安装 Skopeo 后再运行此脚本。{COLORS.RESET}"
        )
        print(f"{COLORS.YELLOW}安装方法: {COLORS.RESET}")
        print(
            f"{COLORS.YELLOW}  - Windows: 可通过 Chocolatey 安装: choco install skopeo{COLORS.RESET}"
        )
        print(
            f"{COLORS.YELLOW}  - Linux: 可通过包管理器安装，例如: sudo apt install skopeo{COLORS.RESET}"
        )
        print(
            f"{COLORS.YELLOW}  - macOS: 可通过 Homebrew 安装: brew install skopeo{COLORS.RESET}"
        )
        sys.exit(1)


def get_compose_projects():
    """
    根据可用的工具，获取正在运行的 Docker Compose 或 Podman Compose 项目的配置文件路径。
    Returns:
        list: 包含所有 Compose 文件完整路径的列表。
    """
    compose_files = set()

    if Config.container_tool == "podman":
        print(f"{COLORS.CYAN}正在获取 Podman Compose 项目列表...{COLORS.RESET}")
        # podman ps -a --filter label=io.podman.compose.project --format json
        output, _ = run_docker(
            [
                "ps",
                "-a",
                "--filter",
                "label=io.podman.compose.project",
                "--format",
                "json",
            ],
            capture_output=True,
        )

        if not output:
            print(
                f"{COLORS.YELLOW}未找到正在运行的 Podman Compose 项目。{COLORS.RESET}"
            )
            return []

        try:
            containers_data = json.loads(output)
        except json.JSONDecodeError as e:
            print(f"{COLORS.RED}解析 Podman ps 输出失败: {e}{COLORS.RESET}")
            return []

        for container in containers_data:
            labels = container.get("Labels", {})
            workdir = labels.get("com.docker.compose.project.working_dir")
            config_files_str = labels.get("com.docker.compose.project.config_files")

            if workdir and config_files_str:
                for config_file in config_files_str.split(","):
                    compose_file_path = os.path.join(workdir, config_file)
                    if os.path.exists(compose_file_path):
                        compose_files.add(compose_file_path)
                    else:
                        print(
                            f"{COLORS.YELLOW}警告: 找到 Compose 项目但配置文件 '{compose_file_path}' 不存在。{COLORS.RESET}"
                        )
            else:
                print(
                    f"{COLORS.YELLOW}警告: 容器 '{container['ID']}' 缺少 Compose 相关的标签，跳过。{COLORS.RESET}"
                )

    else:
        # Docker 环境下的项目发现
        if Config.container_tool == "docker-legacy":
            print(f"{COLORS.CYAN}正在获取旧版 Docker Compose 项目列表...{COLORS.RESET}")
            output, _ = run_docker(["ps", "--format", "json"], capture_output=True)
        else:  # 'docker'
            print(f"{COLORS.CYAN}正在获取新版 Docker Compose 项目列表...{COLORS.RESET}")
            output, _ = run_docker(
                ["compose", "ls", "--format", "json"], capture_output=True
            )

        if not output:
            print(
                f"{COLORS.YELLOW}未找到正在运行的 Docker Compose 项目或命令执行失败。{COLORS.RESET}"
            )
            return []

        try:
            projects_data = json.loads(output)
        except json.JSONDecodeError as e:
            print(f"{COLORS.RED}解析 Docker Compose ls 输出失败: {e}{COLORS.RESET}")
            return []

        for project in projects_data:
            config_files_str = project.get("ConfigFiles")
            if config_files_str:
                for config_file in config_files_str.split(","):
                    compose_files.add(config_file.strip())

    return list(compose_files)


def parse_image_string(image_full_name):
    """
    解析镜像字符串，提取镜像源、用户、仓库名、标签和 digest。
    Args:
        image_full_name (str): 完整的镜像字符串
    Returns:
        dict: 包含 'registry', 'user', 'repo', 'tag', 'digest', 'raw', 'repopath' 的字典。
    """
    registry = None
    user = None
    repo = image_full_name
    tag = ""
    digest = None

    # 1. 优先匹配 digest
    digest_match = re.search(r"(@sha256:[0-9a-f]{64})$", image_full_name)
    if digest_match:
        digest = digest_match.group(0)[1:]
        image_str = image_full_name[: digest_match.start()]
    else:
        image_str = image_full_name

    # 2. 其次匹配 tag
    tag_match = re.search(r":([^/]+)$", image_str)
    if tag_match:
        tag = tag_match.group(1)
        image_str_no_tag = image_str[: tag_match.start()]
    else:
        image_str_no_tag = image_str

    # 3. 最后匹配 registry 和 user/repo
    parts = image_str_no_tag.split("/", 1)

    # 检查第一个部分是否是 registry
    # 规则：
    # 1. 包含 '.' 或 ':' 的是 registry
    # 2. localhost 也是 registry
    if len(parts) > 1 and (
        "." in parts[0] or ":" in parts[0] or parts[0] == "localhost"
    ):
        registry = parts[0]
        repopath = parts[1]
    else:
        registry = None
        repopath = image_str_no_tag

    # 从 repopath 中分离出 user 和 repo
    if "/" in repopath:
        user_repo_parts = repopath.split("/", 1)
        user = user_repo_parts[0]
        repo = user_repo_parts[1]
    else:
        user = None
        repo = repopath

    return {
        "registry": registry,
        "user": user,
        "repo": repo,
        "tag": tag,
        "digest": digest,
        "raw": image_full_name,
        "repopath": repopath,
    }


def get_printable_image_name(user, repo, tag):
    """
    辅助函数：根据镜像信息构建用于打印的名称。
    在日志中不显示 registry。
    """
    image_base_name_parts = []
    if user:
        image_base_name_parts.append(user)
        image_base_name_parts.append("/")
    image_base_name_parts.append(repo)

    image_base_name = "".join(image_base_name_parts)

    printable_image_name = image_base_name
    if tag:
        printable_image_name += f":{tag}"

    return printable_image_name


def build_image_string_with_digest(image_info, new_digest):
    """
    辅助函数：根据镜像信息和新的 digest 构建完整的镜像字符串。
    Args:
        image_info (dict): 从 parse_image_string 返回的镜像信息字典。
        new_digest (str): 要添加的最新 digest 字符串。
    Returns:
        str: 带有新 digest 的完整镜像字符串。
    """
    new_image_full_string_parts = []
    if image_info["registry"]:
        new_image_full_string_parts.append(image_info["registry"])
        new_image_full_string_parts.append("/")

    new_image_full_string_parts.append(image_info["repopath"])

    if image_info["tag"]:
        new_image_full_string_parts.append(f":{image_info['tag']}")

    new_image_full_string_parts.append(f"@{new_digest}")

    return "".join(new_image_full_string_parts)


def get_latest_digest(repopath, tag):
    """
    使用 Skopeo 获取特定镜像标签的最新 digest。
    支持镜像源数组格式和自动 fallback 功能。
    Args:
    repopath (str): 镜像的仓库路径，包含可选的用户前缀，例如 'nginx' 或 'myuser/myimage'。
    tag (str): 镜像的标签。如果为 '' (空字符串)，表示 'latest'。
    arch (str, optional): 镜像的架构，例如 'amd64' 或 'arm64'。
    os (str, optional): 镜像的操作系统，例如 'linux' 或 'windows'。
    Returns:
    str: 镜像的最新 digest 字符串 (例如 'sha256:...'), 如果获取失败则返回 None。
    """
    # 解析 repopath 得到镜像信息
    image_info = parse_image_string(repopath)
    printable_image_name = get_printable_image_name(
        image_info["user"], image_info["repo"], tag
    )

    # 构建镜像引用，支持镜像源配置
    registry = image_info["registry"] or "docker.io"
    image_tag = tag if tag else "latest"

    # 获取镜像源列表
    mirror_list = Config.mirrors.get(registry, [])

    # 添加默认源作为最后一个选项
    if not mirror_list:
        mirror_list = [None]  # None 表示使用默认源
    elif mirror_list[-1] is not None:
        mirror_list.append(None)  # 添加默认源作为最后一个选项

    print(
        f"{COLORS.BLUE}正在使用 Skopeo 获取 {printable_image_name} 的最新 digest...{COLORS.RESET}"
    )

    # 尝试每个镜像源
    for i, mirror_url in enumerate(mirror_list):
        if mirror_url:
            print(
                f"{COLORS.BLUE}尝试镜像源 ({i + 1}/{len(mirror_list)}): {registry} -> {mirror_url}{COLORS.RESET}"
            )
            # 构建使用镜像源的镜像引用
            if registry == "docker.io" and not image_info["user"]:
                # 对于 docker.io 的官方镜像，使用镜像源的完整路径
                image_reference = (
                    f"docker://{mirror_url}/{image_info['repo']}:{image_tag}"
                )
            else:
                # 对于其他镜像，替换 registry 为镜像源
                repo_path = image_info["repopath"]
                if registry:
                    repo_path = repo_path.replace(f"{registry}/", "")
                image_reference = f"docker://{mirror_url}/{repo_path}:{image_tag}"
        else:
            print(
                f"{COLORS.BLUE}尝试默认源 ({i + 1}/{len(mirror_list)}): {registry}{COLORS.RESET}"
            )
            # 使用默认源
            image_reference = f"docker://{repopath}:{image_tag}"

        try:
            # 构建 skopeo inspect 命令
            # 只使用独立的 skopeo 命令
            skopeo_command = ["skopeo", "inspect"]

            skopeo_command.append(image_reference)

            # 直接使用 subprocess 执行 skopeo 命令，避免 run_command 自动添加 podman 前缀
            print(
                f"{COLORS.BLUE}正在运行 '{' '.join(skopeo_command)}'...{COLORS.RESET}"
            )
            try:
                process = subprocess.Popen(
                    skopeo_command,
                    cwd=None,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                )
                stdout, stderr = process.communicate()

                if process.returncode != 0:
                    print(
                        f"{COLORS.RED}命令执行失败，返回码: {process.returncode}{COLORS.RESET}"
                    )
                    print(f"{COLORS.RED}标准错误: {stderr}{COLORS.RESET}")
                    print(f"{COLORS.YELLOW}镜像源失败，尝试下一个...{COLORS.RESET}")
                    continue

                result = stdout.strip()

                if not result:
                    print(f"{COLORS.YELLOW}镜像源失败，尝试下一个...{COLORS.RESET}")
                    continue
            except FileNotFoundError:
                print(
                    f"{COLORS.RED}错误: 命令 '{skopeo_command[0]}' 未找到。请确保该工具已安装并添加到 PATH。{COLORS.RESET}"
                )
                print(f"{COLORS.YELLOW}镜像源失败，尝试下一个...{COLORS.RESET}")
                continue

            # 解析 JSON 输出获取 digest
            try:
                # 尝试直接解析 JSON 输出
                manifest_data = json.loads(result)
            except json.JSONDecodeError:
                # 如果直接解析失败，尝试提取 JSON 部分
                # 查找 JSON 开始和结束的位置
                json_start = result.find("{")
                json_end = result.rfind("}") + 1
                if json_start != -1 and json_end != 0:
                    json_output = result[json_start:json_end]
                    manifest_data = json.loads(json_output)
                else:
                    print(f"{COLORS.YELLOW}无法解析 skopeo 输出。{COLORS.RESET}")
                    continue

            # 尝试获取 digest，检查不同大小写形式
            digest = manifest_data.get("Digest") or manifest_data.get("digest")

            if digest and re.match(r"^sha256:[0-9a-f]{64}$", digest):
                print(f"{COLORS.GREEN}获取到最新 digest: {digest}{COLORS.RESET}")
                return digest
            else:
                print(
                    f"{COLORS.YELLOW}从 Skopeo 输出中没有找到有效 digest，尝试下一个镜像源...{COLORS.RESET}"
                )
                continue
        except Exception as e:
            printable_image_name_for_error = get_printable_image_name(
                image_info["user"], image_info["repo"], tag
            )
            print(
                f"{COLORS.YELLOW}使用此镜像源获取 {printable_image_name_for_error} 的 digest 失败: {e}，尝试下一个...{COLORS.RESET}"
            )
            continue

    # 所有镜像源都失败
    print(f"{COLORS.RED}所有镜像源都失败，无法获取 digest。{COLORS.RESET}")
    return None


def update_docker_compose_file(compose_file_path, services_to_update, yaml_parser):
    """
    更新 docker-compose.yml 文件，将镜像替换为带最新 digest 的格式。
    使用 ruamel.yaml 保留注释和格式。
    Args:
        compose_file_path (str): docker-compose.yml 文件的路径。
        services_to_update (dict): 包含 {service_name: {original_image_info, new_digest}} 的字典。
        yaml_parser (ruamel.yaml.YAML): 用于加载和保存 YAML 的解析器实例。
    Returns:
        tuple: (bool, str) - (是否成功更新文件, 状态消息: "updated", "no_change", "error")
    """
    print(f"{COLORS.BLUE}正在检查并更新文件: {compose_file_path}{COLORS.RESET}")
    try:
        with open(compose_file_path, "r", encoding="utf-8") as f:
            data = yaml_parser.load(f)

        if not data or "services" not in data:
            print(
                f"{COLORS.YELLOW}警告: '{compose_file_path}' 文件内容无效或不包含 'services' 部分。{COLORS.RESET}"
            )
            return False, "error"

        updated = False
        for service_name, info in services_to_update.items():
            original_image_raw = info["original_image_info"]["raw"]
            new_digest = info["new_digest"]

            new_image_full_string = build_image_string_with_digest(
                info["original_image_info"], new_digest
            )

            if (
                "image" in data["services"][service_name]
                and data["services"][service_name]["image"] == new_image_full_string
            ):
                # 不再打印本地镜像已是最新版本的信息
                pass
            else:
                data["services"][service_name]["image"] = new_image_full_string
                print(
                    f"更新服务 '{service_name}' 的镜像: '{original_image_raw}' -> {COLORS.GREEN}'{new_image_full_string}'{COLORS.RESET}"
                )
                updated = True

        if updated:
            with open(compose_file_path, "w", encoding="utf-8") as f:
                yaml_parser.dump(data, f)
            print(f"文件 '{compose_file_path}' {COLORS.GREEN}更新成功。{COLORS.RESET}")
            return True, "updated"
        else:
            return False, "no_change"

    except Exception as e:
        print(f"{COLORS.RED}更新文件 '{compose_file_path}' 失败: {e}{COLORS.RESET}")
        return False, "error"


def prune_old_images():
    """
    修剪悬空镜像（即没有标签且未被任何容器使用的镜像）。
    """
    print(f"\n{COLORS.CYAN}--- 正在修剪旧版本镜像...{COLORS.RESET}")
    run_docker(["image", "prune", "-af"])
    print(f"{COLORS.GREEN}旧版本镜像修剪完成。{COLORS.RESET}")


def get_services_to_update(compose_file_path, yaml_parser):
    """
    从 Compose 文件中获取需要更新的服务列表。
    Args:
        compose_file_path (str): Compose 文件的路径。
        yaml_parser (ruamel.yaml.YAML): YAML 解析器实例。
        arch (str, optional): 镜像的架构，例如 'amd64' 或 'arm64'。
        os (str, optional): 镜像的操作系统，例如 'linux' 或 'windows'。
    Returns:
        dict: 包含 {service_name: {original_image_info, new_digest}} 的字典。
    """
    services_to_update = {}

    print(
        f"{COLORS.BLUE}正在从 {os.path.basename(compose_file_path)} 文件中获取容器镜像信息...{COLORS.RESET}"
    )
    try:
        with open(compose_file_path, "r", encoding="utf-8") as f:
            compose_config = yaml_parser.load(f)
    except Exception as e:
        print(
            f"{COLORS.RED}读取或解析 Compose 文件 '{compose_file_path}' 失败: {e}，跳过此项目。{COLORS.RESET}"
        )
        return services_to_update

    if "services" in compose_config:
        for service_name, service_details in compose_config["services"].items():
            original_image_raw = service_details.get("image")
            if not original_image_raw:
                print(
                    f"{COLORS.YELLOW}服务 '{service_name}' 未指定 'image'，跳过。{COLORS.RESET}"
                )
                continue

            original_image_info = parse_image_string(original_image_raw)

            # 检查是否是 localhost 或 127.0.0.1 下的镜像，如果是则跳过
            registry = original_image_info.get("registry")
            if registry and (registry == "localhost" or registry == "127.0.0.1"):
                print(
                    f"{COLORS.YELLOW}服务 '{service_name}' 使用的是本地镜像 ({registry})，跳过。{COLORS.RESET}"
                )
                continue

            # 获取 yml 文件中现有的 digest
            yml_digest = original_image_info.get("digest")
            print(f"{COLORS.GREEN}获取到本地 digest: {yml_digest}{COLORS.RESET}")

            # 检查远程最新 digest
            api_tag = (
                original_image_info["tag"] if original_image_info["tag"] else "latest"
            )
            latest_digest = get_latest_digest(original_image_info["repopath"], api_tag)

            if not latest_digest:
                print(
                    f"{COLORS.YELLOW}警告: 无法获取服务 '{service_name}' 的最新 digest，跳过此服务。{COLORS.RESET}"
                )
                continue

            if yml_digest != latest_digest:
                print(
                    f"{COLORS.YELLOW}服务 '{service_name}' 的镜像需要更新。{COLORS.RESET}"
                )
                services_to_update[service_name] = {
                    "original_image_info": original_image_info,
                    "new_digest": latest_digest,
                }
            else:
                print(
                    f"{COLORS.GREEN}服务 '{service_name}' 的镜像已是最新版本。{COLORS.RESET}"
                )

    return services_to_update


def perform_deployment(compose_file_path, services_to_update, yaml_parser):
    """
    执行容器部署的完整流程，包括拉取、停止、更新文件和启动。
    Args:
        compose_file_path (str): Compose 文件的路径。
        services_to_update (dict): 需要更新的服务字典。
        yaml_parser (ruamel.yaml.YAML): YAML 解析器实例。
    """
    backup_file_path = compose_file_path + ".bak"

    print(
        f"\n{COLORS.CYAN}--- 正在执行部署步骤: 'pull' -> 'down' -> 'yml' 更新 -> 'up' ---{COLORS.RESET}"
    )

    # 1. 预先拉取所有需要更新的镜像
    pull_success = True
    for service_name, s_info in services_to_update.items():
        new_image_full_string = build_image_string_with_digest(
            s_info["original_image_info"], s_info["new_digest"]
        )

        pull_output, _ = run_docker(["pull", new_image_full_string])

        if pull_output is None:
            print(
                f"{COLORS.RED}镜像 '{new_image_full_string}' pull 失败，{COLORS.YELLOW}终止部署。{COLORS.RESET}"
            )
            pull_success = False
            break

    if not pull_success:
        return

    print(f"{COLORS.GREEN}所有新镜像 pull 命令执行完成。{COLORS.RESET}")

    # 2. 备份文件并执行 down & update
    try:
        # 备份原始文件以防万一
        print(
            f"{COLORS.BLUE}备份原始文件 '{compose_file_path}' 到 '{backup_file_path}'...{COLORS.RESET}"
        )
        shutil.copyfile(compose_file_path, backup_file_path)

        # a. 执行 down 命令
        down_command = ["compose", "down", "--remove-orphans"]
        print(f"{COLORS.CYAN}正在停止并移除旧容器...{COLORS.RESET}")
        down_output, _ = run_docker(down_command)
        if down_output is None:
            raise RuntimeError("Compose down failed")
        print(f"{COLORS.GREEN}旧容器已移除。{COLORS.RESET}")

        # b. 修改 yml 文件
        file_updated, update_status = update_docker_compose_file(
            compose_file_path, services_to_update, yaml_parser
        )

        if not file_updated:
            if update_status == "no_change":
                print(
                    f"{COLORS.YELLOW}文件 '{compose_file_path}' 无需更新，部署将继续。{COLORS.RESET}"
                )
            else:  # update_status == "error"
                raise RuntimeError("Failed to update compose file.")

    except Exception as e:
        print(f"{COLORS.RED}在执行部署过程中发生致命错误：{e}{COLORS.RESET}")
        if os.path.exists(backup_file_path):
            print(
                f"{COLORS.YELLOW}正在尝试回滚文件 '{compose_file_path}' 以恢复服务...{COLORS.RESET}"
            )
            try:
                if os.path.exists(compose_file_path):
                    os.remove(compose_file_path)
                shutil.move(backup_file_path, compose_file_path)
                print(f"{COLORS.GREEN}文件已成功回滚到原始状态。{COLORS.RESET}")

            except OSError as rollback_e:
                print(f"{COLORS.RED}回滚文件时发生错误: {rollback_e}{COLORS.RESET}")
                print(
                    f"{COLORS.RED}请手动恢复文件 '{backup_file_path}' 到 '{compose_file_path}'。{COLORS.RESET}"
                )
        else:
            print(f"{COLORS.RED}回滚失败，备份文件不存在。{COLORS.RESET}")

    # 3. 重新启动容器
    print(f"{COLORS.BLUE}正在尝试重新启动容器...{COLORS.RESET}")
    up_command = ["compose", "up", "-d"]
    up_output, _ = run_docker(up_command)

    if up_output is not None:
        print(f"{COLORS.GREEN}Compose up 命令执行完成。{COLORS.RESET}")
    else:
        print(f"{COLORS.RED}Compose up 命令执行失败。{COLORS.RESET}")

    # 4. 清理备份文件
    if os.path.exists(backup_file_path):
        print(f"{COLORS.BLUE}清理备份文件 '{backup_file_path}'...{COLORS.RESET}")
        try:
            os.remove(backup_file_path)
        except OSError as cleanup_e:
            print(f"{COLORS.RED}清理备份文件失败: {cleanup_e}{COLORS.RESET}")


def main():
    """主函数，协调整个镜像更新过程。"""
    load_config()

    check_docker_availability()
    check_skopeo_availability()

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    compose_files = get_compose_projects()
    if not compose_files:
        print(f"{COLORS.YELLOW}没有可处理的 Compose 项目。{COLORS.RESET}")
        return

    print(f"{COLORS.CYAN}找到 {len(compose_files)} 个 Compose 项目。{COLORS.RESET}")

    for compose_file_path in compose_files:
        project_dir = os.path.dirname(compose_file_path)

        print(f"\n{COLORS.CYAN}--- 处理项目目录: {project_dir} ---{COLORS.RESET}")

        try:
            os.chdir(project_dir)
            print(f"{COLORS.BLUE}已切换到目录: {os.getcwd()}{COLORS.RESET}")
        except OSError as e:
            print(
                f"{COLORS.RED}无法切换到目录 '{project_dir}': {e}，跳过此项目。{COLORS.RESET}"
            )
            continue

        services_to_update = get_services_to_update(compose_file_path, yaml)

        if not services_to_update:
            print(f"{COLORS.GREEN}所有镜像都已是最新版本，无需执行部署。{COLORS.RESET}")
            continue

        perform_deployment(compose_file_path, services_to_update, yaml)

    prune_old_images()

    print(f"\n{COLORS.CYAN}所有 Compose 项目处理完毕。{COLORS.RESET}")


if __name__ == "__main__":
    main()
