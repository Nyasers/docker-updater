#!/usr/bin/env python3
import subprocess
import json
import os
import re
import requests
import shutil
import sys
from ruamel.yaml import YAML

# 定义 ANSI 颜色代码，用于在控制台打印带颜色的信息
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[92m"  # 成功
COLOR_YELLOW = "\033[93m" # 警告
COLOR_RED = "\033[91m"    # 错误
COLOR_CYAN = "\033[96m"   # 信息/标题
COLOR_BLUE = "\033[94m"   # 正在进行的操作

# 全局变量，用于存储检测到的容器工具名称。
# 例如：'podman'、'docker'、'docker-legacy'
CONTAINER_TOOL = None

# TODO: 请在此处填写你的 API 域名，例如 "https://api.example.com"。
# 这个 API 用于根据镜像名和标签获取其最新的 digest 值。
DIGEST_API_BASE_URL = ""

def run_command(command, cwd=None, capture_output=False):
    """
    辅助函数：根据全局变量自动选择正确的容器工具来运行 shell 命令。
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

    # 根据全局变量 CONTAINER_TOOL 的值来决定使用哪个容器工具
    if CONTAINER_TOOL == "podman":
        if command[0] == "compose":
            actual_command = ["podman-compose"] + command[1:]
        else:
            actual_command = ["podman"] + command
    elif CONTAINER_TOOL == "docker-legacy":
        actual_command = ["docker-compose"] + command
    else:  # 'docker'
        if command[0] == "compose":
            actual_command = ["docker", "compose"] + command[1:]
        else:
            actual_command = ["docker"] + command

    print(f"{COLOR_BLUE}正在运行 '{' '.join(actual_command)}'...{COLOR_RESET}")

    try:
        if capture_output:
            process = subprocess.Popen(
                actual_command,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding='utf-8'
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
                encoding='utf-8'
            )
            process.wait()
            stdout, stderr = "Command executed successfully with streaming output.", ""

        if process.returncode != 0:
            if capture_output:
                print(f"{COLOR_RED}命令执行失败，返回码: {process.returncode}{COLOR_RESET}")
                print(f"{COLOR_RED}标准输出: {stdout}{COLOR_RESET}")
                print(f"{COLOR_RED}标准错误: {stderr}{COLOR_RESET}")
            else:
                print(f"{COLOR_RED}命令执行失败，返回码: {process.returncode}{COLOR_RESET}")
            return None, actual_command

        return stdout.strip(), actual_command

    except FileNotFoundError:
        print(f"{COLOR_RED}错误: 命令 '{actual_command[0]}' 未找到。请确保该工具已安装并添加到 PATH。{COLOR_RESET}")
        return None, actual_command


def check_tools_availability():
    """
    检查系统是存在 Podman、新版 Docker Compose 还是旧版 Docker Compose。
    并将结果设置到全局变量 CONTAINER_TOOL 中。
    """
    global CONTAINER_TOOL
    print(f"{COLOR_CYAN}正在检测可用的容器工具...{COLOR_RESET}")

    # 优先检测 Podman 和 Podman-Compose
    if shutil.which("podman") and shutil.which("podman-compose"):
        CONTAINER_TOOL = "podman"
        print(f"{COLOR_GREEN}检测到 Podman 和 Podman-Compose。将使用 'podman' 逻辑。{COLOR_RESET}")
        return

    # 其次检测 Docker 和新版/旧版 Docker Compose
    if shutil.which("docker"):
        try:
            # 尝试运行 "docker compose version" 来判断是否是新版
            run_command(["compose", "version"], capture_output=True)
            CONTAINER_TOOL = "docker"
            print(f"{COLOR_GREEN}检测到 Docker 和新版 Docker Compose。将使用 'docker' 逻辑。{COLOR_RESET}")
            return
        except Exception:
            pass

        # 如果新版 compose 不存在，则检查旧版
        if shutil.which("docker-compose"):
            CONTAINER_TOOL = "docker-legacy"
            print(f"{COLOR_GREEN}检测到 Docker 和旧版 docker-compose。将使用 'docker-legacy' 逻辑。{COLOR_RESET}")
            return

    # 如果以上所有检查都失败
    print(f"{COLOR_RED}错误: 未找到任何可用的容器工具 (Podman/Podman-Compose、新版或旧版 Docker Compose)。请安装其中一套工具。{COLOR_RESET}")
    sys.exit(1)

def get_compose_projects():
    """
    根据可用的工具，获取正在运行的 Docker Compose 或 Podman Compose 项目的配置文件路径。
    Returns:
        list: 包含所有 Compose 文件完整路径的列表。
    """
    compose_files = set()

    if CONTAINER_TOOL == "podman":
        print(f"{COLOR_CYAN}正在获取 Podman Compose 项目列表...{COLOR_RESET}")
        ids_output, _ = run_command(["ps", "-a", "--filter", "label=io.podman.compose.project", "--format", "{{.ID}}"], capture_output=True)

        if not ids_output:
            print(f"{COLOR_YELLOW}未找到正在运行的 Podman Compose 项目。{COLOR_RESET}")
            return []

        container_ids = ids_output.split('\n')

        for container_id in container_ids:
            # 检查是否有与 Compose 相关的标签
            workdir_output, _ = run_command(["inspect", "-f", "{{ index .Config.Labels \"com.docker.compose.project.working_dir\" }}", container_id], capture_output=True)
            config_file_output, _ = run_command(["inspect", "-f", "{{ index .Config.Labels \"com.docker.compose.project.config_files\" }}", container_id], capture_output=True)

            if workdir_output and workdir_output != "<no value>" and config_file_output and config_file_output != "<no value>":
                compose_file_path = os.path.join(workdir_output, config_file_output)
                if os.path.exists(compose_file_path):
                    compose_files.add(compose_file_path)
                else:
                    print(f"{COLOR_YELLOW}警告: 找到 Compose 项目但配置文件 '{compose_file_path}' 不存在。{COLOR_RESET}")
            else:
                print(f"{COLOR_YELLOW}警告: 容器 '{container_id}' 缺少 Compose 相关的标签，跳过。{COLOR_RESET}")

    else:
        # Docker 环境下的项目发现
        if CONTAINER_TOOL == "docker-legacy":
            print(f"{COLOR_CYAN}正在获取旧版 Docker Compose 项目列表...{COLOR_RESET}")
            output, _ = run_command(["ps", "--format", "json"], capture_output=True)
        else: # 'docker'
            print(f"{COLOR_CYAN}正在获取新版 Docker Compose 项目列表...{COLOR_RESET}")
            output, _ = run_command(["compose", "ls", "--format", "json"], capture_output=True)

        if not output:
            print(f"{COLOR_YELLOW}未找到正在运行的 Docker Compose 项目或命令执行失败。{COLOR_RESET}")
            return []

        try:
            projects_data = json.loads(output)
        except json.JSONDecodeError as e:
            print(f"{COLOR_RED}解析 Docker Compose ls 输出失败: {e}{COLOR_RESET}")
            return []

        for project in projects_data:
            config_files_str = project.get("ConfigFiles")
            if config_files_str:
                for config_file in config_files_str.split(','):
                    compose_files.add(config_file.strip())

    return list(compose_files)

def parse_image_string(image_full_name):
    """
    解析镜像字符串，提取镜像源、用户、仓库名、标签和 digest。
    Args:
        image_full_name (str): 完整的镜像字符串，例如 'nginx:latest', 'myuser/myimage', 'myregistry.com/myuser/myimage:tag', 'myuser/myimage@sha256:abc'
    Returns:
        dict: 包含 'registry', 'user', 'repo', 'tag', 'digest', 'raw' 的字典。
    """
    registry = None
    user = "library"
    repo = image_full_name
    tag = ""
    digest = None

    # 优先匹配 digest
    digest_match = re.search(r"(@sha256:[0-9a-f]{64})$", image_full_name)
    if digest_match:
        digest = digest_match.group(1)
        image_str_no_digest = image_full_name[:digest_match.start()]
    else:
        image_str_no_digest = image_full_name

    # 其次匹配 tag
    tag_match = re.search(r":([^/]+)$", image_str_no_digest)
    if tag_match:
        tag = tag_match.group(1)
        image_str_no_tag_no_digest = image_str_no_digest[:tag_match.start()]
    else:
        tag = ""
        image_str_no_tag_no_digest = image_str_no_digest

    # 最后匹配 registry 和 user
    parts = image_str_no_tag_no_digest.split('/', 1)

    # 检查第一个部分是否是 registry，通常包含 '.' 或 ':'
    if len(parts) > 1 and ('.' in parts[0] or ':' in parts[0]) and parts[0] != "localhost":
        registry = parts[0]
        repo_path = parts[1]
    else:
        registry = None
        repo_path = image_str_no_tag_no_digest

    if '/' in repo_path:
        user_repo_parts = repo_path.split('/', 1)
        user = user_repo_parts[0]
        repo = user_repo_parts[1]
    else:
        # 对于如 'nginx' 这样的官方镜像，user 默认为 'library'
        user = "library"
        repo = repo_path

    return {
        'registry': registry,
        'user': user,
        'repo': repo,
        'tag': tag,
        'digest': digest,
        'raw': image_full_name
    }

def get_printable_image_name(registry, user, repo, tag):
    """
    辅助函数：根据镜像信息构建用于打印的名称。
    在日志中不显示 registry。
    """
    image_base_name_parts = []
    if user != "library":
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
    if image_info['registry']:
        new_image_full_string_parts.append(image_info['registry'])
        new_image_full_string_parts.append("/")

    if image_info['user'] != "library":
        new_image_full_string_parts.append(image_info['user'])
        new_image_full_string_parts.append("/")

    new_image_full_string_parts.append(image_info['repo'])

    if image_info['tag']:
        new_image_full_string_parts.append(f":{image_info['tag']}")

    new_image_full_string_parts.append(f"@{new_digest}")

    return "".join(new_image_full_string_parts)

def get_latest_digest(user, repo, tag):
    """
    从你配置的 API 获取特定镜像标签的最新 digest。
    Args:
    user (str): 镜像的用户或组织名。
    repo (str): 镜像的仓库名。
    tag (str): 镜像的标签。如果为 '' (空字符串)，表示 'latest'。
    Returns:
    str: 镜像的最新 digest 字符串 (例如 'sha256:...'), 如果获取失败则返回 None。
    """
    url = f"{DIGEST_API_BASE_URL}/{user}/{repo}/{tag}"

    printable_image_name = get_printable_image_name(None, user, repo, tag)

    print(f"{COLOR_BLUE}正在从 {url} 获取 {printable_image_name} 的最新 digest...{COLOR_RESET}")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()

        # 检查返回类型是否为纯文本
        content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
        if content_type != 'text/plain':
            print(f"{COLOR_YELLOW}警告: 从 {url} 获取到的响应类型不是 'text/plain'，而是 '{content_type}'。{COLOR_RESET}")
            return None

        digest = response.text.strip()
        if re.match(r"^sha256:[0-9a-f]{64}$", digest):
            print(f"{COLOR_GREEN}获取到最新 digest: {digest}{COLOR_RESET}")
            return digest
        else:
            print(f"{COLOR_YELLOW}警告: 从 {url} 获取到无效的 digest 格式: '{digest}'。{COLOR_RESET}")
            return None
    except requests.exceptions.RequestException as e:
        printable_image_name_for_error = get_printable_image_name(None, user, repo, tag)
        print(f"{COLOR_RED}获取 {printable_image_name_for_error} 的 digest 失败: {e}{COLOR_RESET}")
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
    print(f"{COLOR_BLUE}正在检查并更新文件: {compose_file_path}{COLOR_RESET}")
    try:
        with open(compose_file_path, 'r', encoding='utf-8') as f:
            data = yaml_parser.load(f)

        if not data or 'services' not in data:
            print(f"{COLOR_YELLOW}警告: '{compose_file_path}' 文件内容无效或不包含 'services' 部分。{COLOR_RESET}")
            return False, "error"

        updated = False
        for service_name, info in services_to_update.items():
            original_image_raw = info['original_image_info']['raw']
            new_digest = info['new_digest']

            new_image_full_string = build_image_string_with_digest(info['original_image_info'], new_digest)

            if 'image' in data['services'][service_name] and data['services'][service_name]['image'] == new_image_full_string:
                display_image_name_for_log = get_printable_image_name(None, info['original_image_info']['user'], info['original_image_info']['repo'], info['original_image_info']['tag'])
                print(f"服务 '{service_name}' 的镜像 '{display_image_name_for_log}' {COLOR_GREEN}已是最新 digest，无需更新。{COLOR_RESET}")
            else:
                data['services'][service_name]['image'] = new_image_full_string
                print(f"更新服务 '{service_name}' 的镜像: '{original_image_raw}' -> {COLOR_GREEN}'{new_image_full_string}'{COLOR_RESET}")
                updated = True

        if updated:
            with open(compose_file_path, 'w', encoding='utf-8') as f:
                yaml_parser.dump(data, f)
            print(f"文件 '{compose_file_path}' {COLOR_GREEN}更新成功。{COLOR_RESET}")
            return True, "updated"
        else:
            return False, "no_change"

    except Exception as e:
        print(f"{COLOR_RED}更新文件 '{compose_file_path}' 失败: {e}{COLOR_RESET}")
        return False, "error"

def prune_old_images():
    """
    修剪悬空镜像（即没有标签且未被任何容器使用的镜像）。
    """
    print(f"\n{COLOR_CYAN}--- 正在修剪旧版本镜像...{COLOR_RESET}")
    # run_command 会根据全局变量自动选择 podman 或 docker
    run_command(["image", "prune", "-a", "--force"])
    print(f"{COLOR_GREEN}旧版本镜像修剪完成。{COLOR_RESET}")

def main():
    """主函数，协调整个镜像更新过程。"""

    if not DIGEST_API_BASE_URL:
        print(f"{COLOR_RED}错误: DIGEST_API_BASE_URL 未配置。请在脚本开头设置 API 域名。{COLOR_RESET}")
        sys.exit(1)

    check_tools_availability()

    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)

    compose_files = get_compose_projects()
    if not compose_files:
        print(f"{COLOR_YELLOW}没有可处理的 Compose 项目。{COLOR_RESET}")
        return

    print(f"{COLOR_CYAN}找到 {len(compose_files)} 个 Compose 项目。{COLOR_RESET}")

    for compose_file_path in compose_files:
        project_dir = os.path.dirname(compose_file_path)
        compose_file_name = os.path.basename(compose_file_path)
        backup_file_path = compose_file_path + ".bak"

        print(f"\n{COLOR_CYAN}--- 处理项目目录: {project_dir} ---{COLOR_RESET}")

        # 检查上次运行是否残留备份文件，并尝试恢复
        if os.path.exists(backup_file_path):
            print(f"{COLOR_YELLOW}警告：检测到上次运行可能回滚失败。正在尝试从备份恢复文件。{COLOR_RESET}")
            try:
                if os.path.exists(compose_file_path):
                    os.remove(compose_file_path)
                shutil.move(backup_file_path, compose_file_path)
                print(f"{COLOR_GREEN}文件已成功从备份恢复。{COLOR_RESET}")
            except OSError as e:
                print(f"{COLOR_RED}错误：恢复文件失败: {e}{COLOR_RESET}")
                print(f"{COLOR_RED}请手动恢复文件 '{backup_file_path}' 到 '{compose_file_path}'。{COLOR_RESET}")
                continue

        try:
            try:
                os.chdir(project_dir)
                print(f"{COLOR_BLUE}已切换到目录: {os.getcwd()}{COLOR_RESET}")
            except OSError as e:
                print(f"{COLOR_RED}无法切换到目录 '{project_dir}': {e}，跳过此项目。{COLOR_RESET}")
                continue

            print(f"{COLOR_BLUE}正在从 {compose_file_name} 文件中获取容器镜像信息...{COLOR_RESET}")
            try:
                with open(compose_file_name, 'r', encoding='utf-8') as f:
                    compose_config = yaml.load(f)
            except Exception as e:
                print(f"{COLOR_RED}读取或解析 Compose 文件 '{compose_file_name}' 失败: {e}，跳过此项目。{COLOR_RESET}")
                continue

            target_image_api_keys_to_digest = {}
            services_to_update = {}

            if 'services' in compose_config:
                for service_name, service_details in compose_config['services'].items():
                    original_image_raw = service_details.get('image')
                    if not original_image_raw:
                        print(f"{COLOR_YELLOW}服务 '{service_name}' 未指定 'image'，跳过。{COLOR_RESET}")
                        continue

                    original_image_info = parse_image_string(original_image_raw)

                    api_key = (original_image_info['user'], original_image_info['repo'], original_image_info['tag'])

                    if api_key not in target_image_api_keys_to_digest:
                        target_image_api_keys_to_digest[api_key] = None

                    services_to_update[service_name] = {
                        'original_image_info': original_image_info,
                        'new_digest': None
                    }

            if not services_to_update:
                print(f"{COLOR_YELLOW}此项目中没有发现任何需要更新的 'image' 定义的服务，跳过更新。{COLOR_RESET}")
                continue

            # 批量从 API 获取 digest
            for api_key in target_image_api_keys_to_digest.keys():
                api_user, api_repo, api_tag = api_key
                latest_digest = get_latest_digest(api_user, api_repo, api_tag)
                if latest_digest:
                    target_image_api_keys_to_digest[api_key] = latest_digest
                else:
                    printable_image_name_for_error = get_printable_image_name(None, api_user, api_repo, api_tag)
                    print(f"{COLOR_YELLOW}未能获取 {printable_image_name_for_error} 的最新 digest。{COLOR_RESET}")

            # 根据获取到的 digest 信息更新服务列表
            for service_name, info in services_to_update.items():
                api_key = (info['original_image_info']['user'], info['original_image_info']['repo'], info['original_image_info']['tag'])
                info['new_digest'] = target_image_api_keys_to_digest.get(api_key)

            # 过滤掉没有成功获取 digest 的服务
            services_with_valid_digest = {
                s_name: s_info for s_name, s_info in services_to_update.items()
                if s_info['new_digest'] is not None
            }

            if not services_with_valid_digest:
                print(f"{COLOR_YELLOW}没有成功获取任何镜像的最新 digest，跳过更新 docker-compose.yml。{COLOR_RESET}")
                continue

            file_updated, update_status = update_docker_compose_file(compose_file_path, services_with_valid_digest, yaml)

            if file_updated:
                print(f"\n{COLOR_CYAN}--- 正在执行更新步骤: 先 'pull' 最新镜像，再 'up' ---{COLOR_RESET}")
                try:
                    # 备份原始文件以防万一
                    print(f"{COLOR_BLUE}备份原始文件 '{compose_file_path}' 到 '{backup_file_path}'...{COLOR_RESET}")
                    shutil.copyfile(compose_file_path, backup_file_path)

                    pull_success = True
                    for service_name, s_info in services_with_valid_digest.items():
                        new_image_full_string = build_image_string_with_digest(s_info['original_image_info'], s_info['new_digest'])
                        # pull 镜像
                        pull_output, _ = run_command(["pull", new_image_full_string])

                        if pull_output is None:
                            print(f"{COLOR_RED}镜像 '{new_image_full_string}' pull 失败。{COLOR_RESET}")
                            pull_success = False
                            break

                    if pull_success:
                        print(f"{COLOR_GREEN}所有镜像 pull 命令执行完成。{COLOR_RESET}")
                        # 启动 Compose 项目
                        up_command = ["compose", "up", "-d"]
                        up_output, _ = run_command(up_command)

                        if up_output is not None:
                            print(f"{COLOR_GREEN}Compose up 命令执行完成。{COLOR_RESET}")
                            print(up_output)
                            # 清理旧镜像
                            prune_old_images()
                        else:
                            print(f"{COLOR_RED}Compose up 命令执行失败。{COLOR_RESET}")
                    else:
                        print(f"{COLOR_YELLOW}由于 pull 命令失败，正在回滚文件...{COLOR_RESET}")
                        try:
                            # 失败后回滚文件
                            if os.path.exists(compose_file_path):
                                os.remove(compose_file_path)
                            shutil.move(backup_file_path, compose_file_path)
                            print(f"{COLOR_GREEN}文件已成功回滚到原始状态。{COLOR_RESET}")
                        except OSError as rollback_e:
                            print(f"{COLOR_RED}回滚文件时发生错误: {rollback_e}{COLOR_RESET}")
                            print(f"{COLOR_RED}请手动恢复文件 '{backup_file_path}' 到 '{compose_file_path}'。{COLOR_RESET}")
                except Exception as e:
                    print(f"{COLOR_RED}在执行拉取或部署过程中发生意外错误: {e}{COLOR_RESET}")
                    if os.path.exists(backup_file_path):
                        print(f"{COLOR_YELLOW}正在尝试回滚文件 '{compose_file_path}'...{COLOR_RESET}")
                        try:
                            if os.path.exists(compose_file_path):
                                os.remove(compose_file_path)
                            shutil.move(backup_file_path, compose_file_path)
                            print(f"{COLOR_GREEN}文件已成功回滚到原始状态。{COLOR_RESET}")
                        except OSError as rollback_e:
                            print(f"{COLOR_RED}回滚文件时发生错误: {rollback_e}{COLOR_RESET}")
                            print(f"{COLOR_RED}请手动恢复文件 '{backup_file_path}' 到 '{compose_file_path}'。{COLOR_RESET}")
                    else:
                        print(f"{COLOR_RED}回滚失败，备份文件不存在。{COLOR_RESET}")
            else:
                if update_status == "no_change":
                    print(f"{COLOR_YELLOW}文件 '{compose_file_path}' 无需更新，跳过拉取和重新部署。{COLOR_RESET}")
                elif update_status == "error":
                    print(f"{COLOR_RED}文件 '{compose_file_path}' 更新失败，跳过拉取和重新部署。{COLOR_RESET}")

        finally:
            if os.path.exists(backup_file_path):
                print(f"{COLOR_BLUE}清理备份文件 '{backup_file_path}'...{COLOR_RESET}")
                try:
                    os.remove(backup_file_path)
                except OSError as cleanup_e:
                    print(f"{COLOR_RED}清理备份文件失败: {cleanup_e}{COLOR_RESET}")


    print(f"\n{COLOR_CYAN}所有 Compose 项目处理完毕。{COLOR_RESET}")

if __name__ == "__main__":
    main()
