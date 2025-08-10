#!/usr/bin/env python3
import subprocess
import json
import os
import re
import requests
from ruamel.yaml import YAML
import sys
import io

# 定义 ANSI 颜色代码
COLOR_RESET = "\033[0m"
COLOR_GREEN = "\033[92m"  # 成功
COLOR_YELLOW = "\033[93m" # 警告
COLOR_RED = "\033[91m"    # 错误
COLOR_CYAN = "\033[96m"   # 信息/标题
COLOR_BLUE = "\033[94m"   # 正在进行的操作

# 全局变量，用于判断使用哪种容器工具
is_podman_available = False
is_legacy_docker_compose_available = False

# 全局变量，API 的域名
# TODO: 请在此处填写你的 API 域名，例如 "https://api.example.com"。
DIGEST_API_BASE_URL = ""

def run_command(command, cwd=None, tool_override=None, stream_output=False):
    """
    辅助函数：运行 shell 命令。
    Args:
        command (list): 要执行的命令列表，例如 ["docker", "compose", "ls"].
        cwd (str, optional): 命令执行的工作目录。默认为 None (当前目录)。
        tool_override (str, optional): 强制使用 'podman' 或 'docker'。
        stream_output (bool, optional): 是否实时打印输出。这对于 docker pull 的进度条至关重要。
                                        默认为 False，即捕获所有输出。
    Returns:
        tuple: (str, list) - (命令的标准输出, 实际执行的命令列表)，如果命令执行失败则返回 (None, actual_command)。
    """
    if not tool_override:
        if is_podman_available:
            tool_override = "podman"
        elif is_legacy_docker_compose_available:
            tool_override = "docker-compose"
        else:
            tool_override = "docker"

    actual_command = []
    
    # 特殊处理 compose 命令
    if command[0] == "compose":
        if tool_override == "podman":
            # 对于 podman-compose, 不需要 'compose' 子命令
            actual_command = ["podman-compose"] + command[1:]
        elif is_legacy_docker_compose_available:
            # 使用旧版 docker-compose，整个命令是 "docker-compose"
            actual_command = ["docker-compose"] + command[1:]
        else:
            # 使用新版 docker compose
            actual_command = ["docker", "compose"] + command[1:]
    else:
        if tool_override == "podman":
            actual_command = ["podman"] + command
        else:
            actual_command = ["docker"] + command

    print(f"{COLOR_BLUE}正在运行 '{' '.join(actual_command)}'...{COLOR_RESET}")

    if stream_output:
        try:
            # 修复：直接将子进程的stdout和stderr连接到父进程的stdout和stderr
            # 这是为了正确处理像 `docker pull` 这样的命令，
            # 它们会使用回车符 `\r` 来更新同一行的进度条。
            process = subprocess.Popen(
                actual_command,
                cwd=cwd,
                stdout=sys.stdout,
                stderr=sys.stderr,
                text=True,
                encoding='utf-8'
            )

            process.wait() # 等待子进程结束
            
            if process.returncode != 0:
                print(f"{COLOR_RED}命令执行失败，返回码: {process.returncode}{COLOR_RESET}")
                return None, actual_command
            
            # 由于输出已直接打印到屏幕，这里捕获的输出将是空的
            # 但对于进度条命令，我们只需要关注其返回码
            return "Command executed successfully with streaming output.", actual_command
            
        except FileNotFoundError:
            print(f"{COLOR_RED}错误: 命令 '{actual_command[0]}' 未找到。请确保该工具已安装并添加到 PATH。{COLOR_RESET}")
            return None, actual_command
    else:
        try:
            # 对于非流式输出命令，使用 run 更简单
            result = subprocess.run(
                actual_command,
                cwd=cwd,
                capture_output=True,
                text=True,
                check=True,
                encoding='utf-8' # 显式设置编码以处理可能的非 ASCII 输出
            )
            return result.stdout.strip(), actual_command
        except subprocess.CalledProcessError as e:
            print(f"{COLOR_RED}命令执行失败: {e.cmd}{COLOR_RESET}")
            print(f"{COLOR_RED}标准输出: {e.stdout}{COLOR_RESET}")
            print(f"{COLOR_RED}标准错误: {e.stderr}{COLOR_RESET}")
            return None, actual_command
        except FileNotFoundError:
            # FileNotFoundError只在 actual_command[0] 未找到时触发
            print(f"{COLOR_RED}错误: 命令 '{actual_command[0]}' 未找到。请确保该工具已安装并添加到 PATH。{COLOR_RESET}")
            return None, actual_command

def check_tools_availability():
    """
    检查系统是存在 Podman、新版 Docker Compose 还是旧版 Docker Compose。
    """
    global is_podman_available, is_legacy_docker_compose_available
    print(f"{COLOR_CYAN}正在检测可用的容器工具...{COLOR_RESET}")
    
    # 优先检测 Podman 和 Podman-Compose
    # 注意：这里使用非流式输出，因为 --version 通常只有一行输出
    podman_exists, _ = run_command(["--version"], tool_override="podman")
    if podman_exists is not None:
        podman_compose_exists, _ = run_command(["--version"], tool_override="podman-compose")
        if podman_compose_exists is not None:
            is_podman_available = True
            print(f"{COLOR_GREEN}检测到 Podman 和 Podman-Compose。将使用 Podman 逻辑。{COLOR_RESET}")
            return
        else:
            print(f"{COLOR_RED}错误: 检测到 Podman 但未找到 podman-compose。请安装 podman-compose。{COLOR_RESET}")
            sys.exit(1)
    
    # 其次检测新版 Docker Compose
    docker_exists, _ = run_command(["--version"], tool_override="docker")
    if docker_exists is not None:
        docker_compose_exists, _ = run_command(["compose", "--version"], tool_override="docker")
        if docker_compose_exists is not None:
            is_podman_available = False # 显式设置为 False
            is_legacy_docker_compose_available = False
            print(f"{COLOR_GREEN}未检测到 Podman，但检测到 Docker 和新版 Docker Compose。将使用 Docker 逻辑。{COLOR_RESET}")
            return
            
    # 最后检测旧版 Docker Compose
    # 注意: 这里命令是 "docker-compose"
    docker_compose_legacy_exists, _ = run_command(["--version"], tool_override="docker-compose")
    if docker_compose_legacy_exists is not None:
        is_podman_available = False
        is_legacy_docker_compose_available = True
        print(f"{COLOR_GREEN}未检测到 Podman 或新版 Docker Compose，但检测到旧版 docker-compose。将使用旧版 Docker Compose 逻辑。{COLOR_RESET}")
        return
        
    print(f"{COLOR_RED}错误: 未找到任何可用的容器工具 (Podman/Podman-Compose、新版或旧版 Docker Compose)。请安装其中一套工具。{COLOR_RESET}")
    sys.exit(1)

def get_compose_projects():
    """
    根据可用的工具，获取正在运行的 Docker Compose 或 Podman Compose 项目的配置文件路径。
    Returns:
        list: 包含所有 Compose 文件完整路径的列表。
    """
    compose_files = set() # 使用集合来自动去重
    
    if is_podman_available:
        print(f"{COLOR_CYAN}正在获取 Podman Compose 项目列表...{COLOR_RESET}")
        # 首先获取所有带有 compose 标签的容器 ID
        ids_output, _ = run_command(["ps", "-a", "--filter", "label=io.podman.compose.project", "--format", "{{.ID}}"], tool_override="podman")

        if not ids_output:
            print(f"{COLOR_YELLOW}未找到正在运行的 Podman Compose 项目。{COLOR_RESET}")
            return []

        container_ids = ids_output.split('\n')
        
        for container_id in container_ids:
            # 获取项目的工作目录和配置文件名
            workdir_output, _ = run_command(["inspect", "-f", "{{ index .Config.Labels \"com.docker.compose.project.working_dir\" }}", container_id], tool_override="podman")
            config_file_output, _ = run_command(["inspect", "-f", "{{ index .Config.Labels \"com.docker.compose.project.config_files\" }}", container_id], tool_override="podman")

            if workdir_output and workdir_output != "<no value>" and config_file_output and config_file_output != "<no value>":
                compose_file_path = os.path.join(workdir_output, config_file_output)
                if os.path.exists(compose_file_path):
                    compose_files.add(compose_file_path)
                else:
                    print(f"{COLOR_YELLOW}警告: 找到 Compose 项目但配置文件 '{compose_file_path}' 不存在。{COLOR_RESET}")
            else:
                print(f"{COLOR_YELLOW}警告: 容器 '{container_id}' 缺少 Compose 相关的标签，跳过。{COLOR_RESET}")
        
    else: # 使用 Docker (新版或旧版)
        if is_legacy_docker_compose_available:
            print(f"{COLOR_CYAN}正在获取旧版 Docker Compose 项目列表...{COLOR_RESET}")
            output, _ = run_command(["ps", "--format", "json"], tool_override="docker-compose")
        else:
            print(f"{COLOR_CYAN}正在获取新版 Docker Compose 项目列表...{COLOR_RESET}")
            output, _ = run_command(["compose", "ls", "--format", "json"], tool_override="docker")
        
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
              tag 默认为 '' (空字符串表示latest)，digest 默认为 None，registry 默认为 None。
    """
    registry = None
    user = "library"
    repo = image_full_name
    tag = "" # 默认标签为空字符串，表示latest
    digest = None
    
    # 1. 提取 digest (e.g., @sha256:...)
    digest_match = re.search(r"(@sha256:[0-9a-f]{64})$", image_full_name)
    if digest_match:
        digest = digest_match.group(1)
        image_str_no_digest = image_full_name[:digest_match.start()]
    else:
        image_str_no_digest = image_full_name

    # 2. 提取 tag (e.g., :tag)
    tag_match = re.search(r":([^/]+)$", image_str_no_digest)
    if tag_match:
        tag = tag_match.group(1) # 直接使用提取到的标签字符串
        image_str_no_tag_no_digest = image_str_no_digest[:tag_match.start()]
    else:
        tag = "" # No explicit tag, implies 'latest'
        image_str_no_tag_no_digest = image_str_no_digest

    # 3. 解析 registry 和 user/repo
    # 镜像名格式通常为 [registry_host[:port]/][user/]repo
    parts = image_str_no_tag_no_digest.split('/', 1) # 只在第一个 '/' 处分割

    # 检查第一个部分是否是 registry (包含 '.' 或 ':' 且不是 'localhost')
    if len(parts) > 1 and ('.' in parts[0] or ':' in parts[0]) and parts[0] != "localhost":
        registry = parts[0]
        repo_path = parts[1] # 剩下的部分是 user/repo 或 repo
    else:
        registry = None
        repo_path = image_str_no_tag_no_digest # 整个字符串就是 user/repo 或 repo

    # 从 repo_path 中解析 user/repo
    if '/' in repo_path:
        user_repo_parts = repo_path.split('/', 1)
        user = user_repo_parts[0]
        repo = user_repo_parts[1]
    else:
        user = "library" # Default user for official images (e.g., 'nginx')
        repo = repo_path

    return {
        'registry': registry,
        'user': user,
        'repo': repo,
        'tag': tag,
        'digest': digest,
        'raw': image_full_name # 原始完整字符串
    }

def get_printable_image_name(registry, user, repo, tag):
    """
    辅助函数：根据用户、仓库、标签构建用于打印的镜像名称。
    在日志中不显示 registry。
    """
    image_base_name_parts = []
    # 不显示 registry 部分
    if user != "library":
        image_base_name_parts.append(user)
        image_base_name_parts.append("/") # 添加斜杠
    image_base_name_parts.append(repo)
    
    image_base_name = "".join(image_base_name_parts)

    printable_image_name = image_base_name
    # 只有当 tag 非空时才显示标签
    if tag: # 如果 tag 是具体的值 (例如 'v1.0')
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
    # 统一 URL 构造，tag 为空字符串时，URL 会以 / 结尾，服务器会处理为 latest
    # 注意: 此脚本的 API 接口设计为只使用 user/repo/tag，不包含 registry。
    url = f"{DIGEST_API_BASE_URL}/{user}/{repo}/{tag}"

    # 构建要打印的镜像名称，使用辅助函数
    # 传入 None 给 registry，因为它不用于打印
    printable_image_name = get_printable_image_name(None, user, repo, tag) 

    print(f"{COLOR_BLUE}正在从 {url} 获取 {printable_image_name} 的最新 digest...{COLOR_RESET}")
    try:
        response = requests.get(url, timeout=10)
        
        # 1. 检查响应状态码
        response.raise_for_status()

        # 2. 检查 Content-Type，确保是纯文本
        content_type = response.headers.get('Content-Type', '').split(';')[0].strip()
        if content_type != 'text/plain':
            print(f"{COLOR_YELLOW}警告: 从 {url} 获取到的响应类型不是 'text/plain'，而是 '{content_type}'。{COLOR_RESET}")
            return None

        # 3. 解析并检查 digest 格式
        digest = response.text.strip()
        if re.match(r"^sha256:[0-9a-f]{64}$", digest):
            print(f"{COLOR_GREEN}获取到最新 digest: {digest}{COLOR_RESET}")
            return digest
        else:
            print(f"{COLOR_YELLOW}警告: 从 {url} 获取到无效的 digest 格式: '{digest}'。{COLOR_RESET}")
            return None
    except requests.exceptions.RequestException as e:
        # 错误信息也使用统一的打印名称
        print(f"{COLOR_RED}获取 {printable_image_name} 的 digest 失败: {e}{COLOR_RESET}")
        return None

def update_docker_compose_file(compose_file_path, service_update_info, yaml_parser):
    """
    更新 docker-compose.yml 文件，将镜像替换为带最新 digest 的格式。
    使用 ruamel.yaml 保留注释和格式。
    Args:
        compose_file_path (str): docker-compose.yml 文件的路径。
        service_update_info (dict): 包含 {service_name: {original_image_info, new_digest}} 的字典。
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
        for service_name, service_config in data['services'].items():
            if service_name not in service_update_info:
                continue # 跳过不在此次更新列表中的服务

            info = service_update_info[service_name]
            original_image_raw = info['original_image_info']['raw']
            new_digest = info['new_digest']
            
            # 使用新函数构建带有 digest 的镜像字符串
            new_image_full_string = build_image_string_with_digest(info['original_image_info'], new_digest)

            if 'image' not in service_config or service_config['image'] == new_image_full_string:
                # 这里的 display_image_name_for_log 应该只包含 user/repo[:tag] 部分，不带 registry
                display_image_name_for_log = get_printable_image_name(None, info['original_image_info']['user'], info['original_image_info']['repo'], info['original_image_info']['tag'])
                print(f"服务 '{service_name}' 的镜像 '{display_image_name_for_log}' {COLOR_GREEN}已是最新 digest，无需更新。{COLOR_RESET}")
            else:
                service_config['image'] = new_image_full_string
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

def main():
    """主函数，协调整个镜像更新过程。"""
    
    # 检查 API URL 是否已配置
    if not DIGEST_API_BASE_URL:
        print(f"{COLOR_RED}错误: DIGEST_API_BASE_URL 未配置。请在脚本开头设置 API 域名。{COLOR_RESET}")
        sys.exit(1)

    check_tools_availability()

    yaml = YAML()
    yaml.preserve_quotes = True # 保留字符串的引号
    yaml.indent(mapping=2, sequence=4, offset=2) # 标准 YAML 缩进

    compose_files = get_compose_projects()
    if not compose_files:
        print(f"{COLOR_YELLOW}没有可处理的 Compose 项目。{COLOR_RESET}")
        return

    print(f"{COLOR_CYAN}找到 {len(compose_files)} 个 Compose 项目。{COLOR_RESET}")

    for compose_file_path in compose_files:
        project_dir = os.path.dirname(compose_file_path)
        compose_file_name = os.path.basename(compose_file_path)
        
        print(f"\n{COLOR_CYAN}--- 处理项目目录: {project_dir} ---{COLOR_RESET}")

        # 切换到项目目录
        try:
            os.chdir(project_dir)
            print(f"{COLOR_BLUE}已切换到目录: {os.getcwd()}{COLOR_RESET}")
        except OSError as e:
            print(f"{COLOR_RED}无法切换到目录 '{project_dir}': {e}，跳过此项目。{COLOR_RESET}")
            continue

        # 步骤 2.1: 从 compose 文件中直接获取容器镜像信息
        print(f"{COLOR_BLUE}正在从 {compose_file_name} 文件中获取容器镜像信息...{COLOR_RESET}")
        try:
            with open(compose_file_name, 'r', encoding='utf-8') as f:
                compose_config = yaml.load(f)
        except Exception as e:
            print(f"{COLOR_RED}读取或解析 Compose 文件 '{compose_file_name}' 失败: {e}，跳过此项目。{COLOR_RESET}")
            continue

        # 存储 { (目标用户, 目标仓库名, 目标标签): 最新 digest }，避免重复 API 调用
        target_image_api_keys_to_digest = {} 
        # 存储 { service_name: { 'original_image_info': {...}, 'new_digest': None } }
        services_to_update = {}

        if 'services' in compose_config:
            for service_name, service_details in compose_config['services'].items():
                original_image_raw = service_details.get('image')
                if not original_image_raw:
                    print(f"{COLOR_YELLOW}服务 '{service_name}' 未指定 'image'，跳过。{COLOR_RESET}")
                    continue

                # 直接从原始 image 字符串解析出目标信息
                original_image_info = parse_image_string(original_image_raw)
                
                # API 请求的目标 user/repo/tag 直接来自原始 image 字段解析出的信息
                # 忽略原始 image中的 digest，因为我们要获取的是最新 digest
                api_user = original_image_info['user']
                api_repo = original_image_info['repo']
                api_tag = original_image_info['tag'] # 使用原始 image 中的 tag 作为 API 查询的目标

                api_key = (api_user, api_repo, api_tag)
                
                # 记录需要获取 digest 的镜像
                if api_key not in target_image_api_keys_to_digest:
                    target_image_api_keys_to_digest[api_key] = None # 占位符，稍后填充

                services_to_update[service_name] = {
                    'original_image_info': original_image_info,
                    'new_digest': None # 稍后填充
                }

        if not services_to_update:
            print(f"{COLOR_YELLOW}此项目中没有发现任何需要更新的 'image' 定义的服务，跳过更新。{COLOR_RESET}")
            continue

        # 步骤 2.2: 为每个独特的 (user, repo, tag) 组合获取最新 digest
        for api_key in target_image_api_keys_to_digest.keys():
            api_user, api_repo, api_tag = api_key
            
            latest_digest = get_latest_digest(api_user, api_repo, api_tag)
            if latest_digest:
                target_image_api_keys_to_digest[api_key] = latest_digest
            else:
                # 使用辅助函数构建用于错误消息的打印名称
                # 注意：这里传入 None 给 registry，因为错误日志中不显示 registry
                printable_image_name_for_error = get_printable_image_name(None, api_user, api_repo, api_tag)
                print(f"{COLOR_YELLOW}未能获取 {printable_image_name_for_error} 的最新 digest。{COLOR_RESET}")

        # 将获取到的 digest 填充到 services_to_update 字典中
        for service_name, info in services_to_update.items():
            # 这里的 api_key 应该基于 original_image_info 的 user/repo/tag
            api_key = (info['original_image_info']['user'], info['original_image_info']['repo'], info['original_image_info']['tag'])
            info['new_digest'] = target_image_api_keys_to_digest.get(api_key)

        # 过滤掉没有成功获取到 digest 的服务
        services_with_valid_digest = {
            s_name: s_info for s_name, s_info in services_to_update.items() 
            if s_info['new_digest'] is not None
        }

        if not services_with_valid_digest:
            print(f"{COLOR_YELLOW}没有成功获取任何镜像的最新 digest，跳过更新 docker-compose.yml。{COLOR_RESET}")
            continue

        # 步骤 2.3: 更新 docker-compose.yml
        file_updated, update_status = update_docker_compose_file(compose_file_path, services_with_valid_digest, yaml)
        
        if file_updated:
            print(f"\n{COLOR_CYAN}--- 正在执行更新步骤: 先 'pull' 最新镜像，再 'up' ---{COLOR_RESET}")
            
            # --- 新增: 回滚机制开始 ---
            backup_file_path = compose_file_path + ".bak"
            
            try:
                # 备份原始文件
                print(f"{COLOR_BLUE}备份原始文件 '{compose_file_path}' 到 '{backup_file_path}'...{COLOR_RESET}")
                # 使用 shutil.copyfile 是一个更健壮的方式，但为了不增加新的库依赖，
                # 这里我们直接使用Python的文件读写来复制内容。
                with open(compose_file_path, 'r', encoding='utf-8') as f_in, open(backup_file_path, 'w', encoding='utf-8') as f_out:
                    f_out.write(f_in.read())

                pull_success = True
                
                # 步骤 2.4a: 为每个需要更新的服务单独执行 pull 命令
                for service_name, s_info in services_with_valid_digest.items():
                    # 使用新函数构建带有 digest 的镜像字符串
                    new_image_full_string = build_image_string_with_digest(s_info['original_image_info'], s_info['new_digest'])
                    
                    # 执行 pull 命令，并启用实时输出
                    pull_output, _ = run_command(["pull", new_image_full_string], stream_output=True)

                    if pull_output is None:
                        print(f"{COLOR_RED}镜像 '{new_image_full_string}' pull 失败。{COLOR_RESET}")
                        pull_success = False
                        break # 任何一个镜像拉取失败，就停止此项目的更新
                
                if pull_success:
                    print(f"{COLOR_GREEN}所有镜像 pull 命令执行完成。{COLOR_RESET}")
                    
                    # 步骤 2.4b: 运行 compose up -d
                    # 显式指定 compose 文件，以支持非默认文件名的项目
                    up_command = ["compose", "-f", compose_file_name, "up", "-d"]
                    up_output, _ = run_command(up_command)
                    
                    if up_output is not None:
                        print(f"{COLOR_GREEN}Compose up 命令执行完成。{COLOR_RESET}")
                        print(up_output) # 这里的输出通常是 Compose 自身的日志，不额外着色
                    else:
                        print(f"{COLOR_RED}Compose up 命令执行失败。{COLOR_RESET}")
                else:
                    print(f"{COLOR_YELLOW}由于 pull 命令失败，正在回滚文件...{COLOR_RESET}")
                    # 回滚操作
                    os.remove(compose_file_path) # 删除已修改的文件
                    os.rename(backup_file_path, compose_file_path) # 恢复备份
                    print(f"{COLOR_GREEN}文件已成功回滚到原始状态。{COLOR_RESET}")

            except Exception as e:
                print(f"{COLOR_RED}在执行拉取或部署过程中发生意外错误: {e}{COLOR_RESET}")
                if os.path.exists(backup_file_path):
                    print(f"{COLOR_YELLOW}正在尝试回滚文件 '{compose_file_path}'...{COLOR_RESET}")
                    # 确保原始文件存在，如果不存在则直接重命名备份文件
                    if os.path.exists(compose_file_path):
                        os.remove(compose_file_path)
                    os.rename(backup_file_path, compose_file_path)
                    print(f"{COLOR_GREEN}文件已成功回滚到原始状态。{COLOR_RESET}")
                else:
                    print(f"{COLOR_RED}回滚失败，备份文件不存在。{COLOR_RESET}")
            finally:
                # 清理备份文件
                if os.path.exists(backup_file_path):
                    print(f"{COLOR_BLUE}清理备份文件 '{backup_file_path}'...{COLOR_RESET}")
                    os.remove(backup_file_path)
            # --- 回滚机制结束 ---
        else:
            if update_status == "no_change":
                print(f"{COLOR_YELLOW}文件 '{compose_file_path}' 无需更新，跳过拉取和重新部署。{COLOR_RESET}")
            elif update_status == "error":
                print(f"{COLOR_RED}文件 '{compose_file_path}' 更新失败，跳过拉取和重新部署。{COLOR_RESET}")

    print(f"\n{COLOR_CYAN}所有 Compose 项目处理完毕。{COLOR_RESET}")

if __name__ == "__main__":
    main()
