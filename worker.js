// Worker 脚本的入口点，监听 fetch 事件
export default {
  async fetch(request, env, ctx) {
    return handleRequest(request);
  }
}

/**
 * 解析请求的 URL 路径，提取 user, repo 和 tag。
 * @param {string} pathname 请求的 URL 路径名
 * @returns {{user: string, repo: string, tag: string}} 包含 user, repo 和 tag 的对象
 * @throws {Error} 如果路径格式不符合要求则抛出错误
 */
function parseRequestPath(pathname) {
  // 过滤掉空字符串，得到路径段
  const path = pathname.split('/').filter(p => p !== '');

  // 检查是否有路径段
  if (path.length === 0) {
    throw new Error('Usage: /<repo>[:<tag>] or /<user>/<repo>[:<tag>] - Requires at least 1 segment.');
  }

  // 找到最后一个冒号的位置
  const lastPathSegment = path[path.length - 1];
  const colonIndex = lastPathSegment.lastIndexOf(':');

  // 分离 tag 和 repo 部分，tag 可选，默认 latest
  const tag = colonIndex !== -1 ? lastPathSegment.slice(colonIndex + 1) : 'latest';
  const repoPart = colonIndex !== -1 ? lastPathSegment.slice(0, colonIndex) : lastPathSegment;

  // 处理 user 和 repo
  let user, repo;
  if (path.length === 1) {
    // 官方镜像格式: /<repo>[:<tag>]
    user = 'library';
    repo = repoPart;
  } else {
    // 完整格式: /<user>/<repo>[:<tag>] 或更复杂的路径
    user = path[0];
    repo = repoPart;
  }

  return { user, repo, tag };
}

/**
 * 从 Docker Hub 获取镜像的 token，用于后续的 manifest 请求
 * @param {string} user 镜像的用户名
 * @param {string} repo 镜像的仓库名
 * @returns {Promise<string>} 返回 Docker Hub 提供的 token
 * @throws {Error} 如果请求失败则抛出错误
 */
async function fetchDockerToken(user, repo) {
  const url = `https://auth.docker.io/token?service=registry.docker.io&scope=repository:${user}/${repo}:pull`;
  const response = await fetch(url).catch(e => { throw e });
  const data = await response.json().catch(e => { throw e });
  return data.token;
}

/**
 * 从 Docker Hub API 获取指定镜像的 manifest
 * @param {string} user 镜像的用户名
 * @param {string} repo 镜像的仓库名
 * @param {string} tag 镜像的标签
 * @param {{architecture?: string, os?: string}} platform 目标平台信息
 * @returns {Promise<object>} 返回镜像的 manifest
 * @throws {Error} 如果 API 请求或响应失败则抛出错误
 */
async function fetchDockerManifests(user, repo, tag, platform = {}) {
  const url = `https://registry-1.docker.io/v2/${user}/${repo}/manifests/${tag}`;
  const token = await fetchDockerToken(user, repo).catch(e => { throw e });

  // 创建获取 manifest list 的请求
  const listRequest = new Request(url, {
    method: 'GET',
    headers: { 'Accept': 'application/vnd.docker.distribution.manifest.list.v2+json', 'Authorization': `Bearer ${token}` }
  });

  const listResponse = await fetch(listRequest).catch(e => { throw e });
  const listData = await listResponse.json().catch(e => { throw e });

  // 检查是否是 manifest list
  let res = listData.manifests || [];
  if (res) {
    if (platform.architecture) {
      res = res.filter(item => item.platform.architecture === platform.architecture);
    }
    if (platform.os) {
      res = res.filter(item => item.platform.os === platform.os);
    }
  }
  if (res.length > 0) {
    return res;
  } else {
    throw new Error(`No manifest found.`);
  }
}

/**
 * 主处理函数，负责处理传入的请求
 * 支持的格式: /<user>/<repo>[:<tag>] 或 /<repo>[:<tag>] (官方镜像，tag 可选，默认 latest)
 * @param {Request} request 传入的请求对象
 * @returns {Response} 返回一个响应对象
 */
async function handleRequest(request) {
  try {
    const url = new URL(request.url);

    // 使用 parseRequestPath 解析路径，获取 user, repo 和 tag
    const parsedPath = parseRequestPath(url.pathname);
    const { user, repo, tag } = parsedPath;

    // 获取查询参数
    const search = url.searchParams;
    // 创建 platform 对象
    const platform = {
      architecture: search.get('architecture') || search.get('arch') || undefined,
      os: search.get('os') || undefined
    };

    // 获取 manifest，传递查询参数
    const manifests = await fetchDockerManifests(user, repo, tag, platform);

    // 返回 manifest 结果
    return new Response(JSON.stringify({status: 200, manifests}), {
      status: 200,
      headers: {
        'Content-Type': 'application/json',
      }
    });
  } catch (error) {
    const message = error.message;
    let status = message.startsWith('Usage:') ? 400 : 404;
    return new Response(JSON.stringify({ status, message }), { status: status, headers: { 'Content-Type': 'application/json' } });
  }
}
