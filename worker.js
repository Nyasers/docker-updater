// Worker 脚本的入口点，监听 fetch 事件
export default {
  async fetch(request, env, ctx) {
    return handleRequest(request);
  }
}

/**
 * 解析请求的 URL 路径，提取 user, repo 和 tag。
 * 此函数主要用于解析至少包含 user/repo 的路径结构。
 * @param {string} pathname 请求的 URL 路径名
 * @returns {{user: string, repo: string, tag: string}} 包含 user, repo 和 tag 的对象
 * @throws {Error} 如果路径段少于 2 个则抛出错误
 */
function parseRequestPath(pathname) {
  // 过滤掉空字符串，得到路径段
  const path = pathname.split('/').filter(p => p !== '');
  
  // 路径必须至少包含 user 和 repo (2个段)
  if (path.length < 2) {
    throw new Error('Usage: /<user>/<repo>/[tag] - Requires at least 2 segments for standard parsing.');
  }
  
  const user = path[0];
  const repo = path[1];
  // 如果路径中有第三个参数，则使用它作为 tag，否则默认为 'latest'
  const tag = path.length > 2 ? path[2] : 'latest';

  return { user, repo, tag };
}

/**
 * 从 Docker Hub API 获取指定镜像的 digest
 * @param {string} user 镜像的用户名
 * @param {string} repo 镜像的仓库名
 * @param {string} tag 镜像的标签
 * @returns {Promise<string>} 返回镜像的 digest
 * @throws {Error} 如果 API 请求或响应失败则抛出错误
 */
async function fetchDockerDigest(user, repo, tag) {
  // 构造目标 API 的完整 URL
  const targetUrl = `https://hub.docker.com/v2/repositories/${user}/${repo}/tags/${tag}`;
  
  // 创建一个新的请求，用于转发到目标 API
  const newRequest = new Request(targetUrl, {
    method: 'GET',
    headers: { 'Accept': 'application/json' },
    redirect: 'follow'
  });

  // 删除可能导致问题的请求头
  newRequest.headers.delete('host');

  const response = await fetch(newRequest);

  // 检查响应状态是否成功
  if (!response.ok) {
    // 捕获 Docker Hub 的 4xx/5xx 错误，并附带状态码
    const statusText = response.statusText || `Status ${response.status}`;
    let errorMessage = `Upstream error: ${statusText}`;
    
    // 尝试读取响应体以获取更详细的错误信息
    try {
        const text = await response.text();
        if (text) {
             // 尝试解析 JSON 错误，如果失败则使用原始文本
             try {
                 const json = JSON.parse(text);
                 errorMessage += ` - ${json.detail || json.message || text}`;
             } catch {
                 errorMessage += ` - ${text}`;
             }
        }
    } catch (e) { /* 忽略读取或解析响应体的错误 */ }
    
    throw new Error(errorMessage);
  }

  const json = await response.json();
  // Docker Hub V2 API 响应中，digest 有时直接在顶层，有时在 images 数组的第一个元素中
  const digest = json.digest || json.images?.[0]?.digest; 
  
  // 检查响应中是否包含 digest
  if (!digest) {
    throw new Error('Digest not found in response.');
  }
  
  return digest;
}

/**
 * 主处理函数，负责处理传入的请求，增加了对官方镜像（/repo 或 /repo/tag）的健壮性处理
 * @param {Request} request 传入的请求对象
 * @returns {Response} 返回一个响应对象
 */
async function handleRequest(request) {
  const url = new URL(request.url);
  // 获取并过滤掉空字符串，得到路径段
  const pathSegments = url.pathname.split('/').filter(p => p !== '');
  
  let user, repo, tag;
  let digest;
  
  try {
    if (pathSegments.length === 1) {
      // 案例 1: /nginx (单段路径). 默认视为官方镜像 library/nginx:latest
      user = 'library';
      repo = pathSegments[0];
      tag = 'latest';
      
      digest = await fetchDockerDigest(user, repo, tag);
      
    } else if (pathSegments.length >= 2) {
      // 案例 2: /myuser/myrepo, /myuser/myrepo/mytag, 或 /nginx/latest (两段或多段路径)
      
      // 1. 尝试作为非官方或已完整指定用户名的镜像进行解析 (例如: /nginx/latest -> user=nginx, repo=latest, tag=latest)
      const parsedPath = parseRequestPath(url.pathname);
      user = parsedPath.user;
      repo = parsedPath.repo;
      tag = parsedPath.tag;

      try {
        // 尝试获取 digest
        digest = await fetchDockerDigest(user, repo, tag);
        
      } catch (e) {
        // 如果第一次尝试失败，检查是否属于官方镜像的特殊情况
        
        // 只有当路径段长度为 2 且第一个段不是 'library' 时，才进行重试。
        // 这解决了 /nginx/latest 被错误解析为非官方镜像的问题。
        if (pathSegments.length === 2 && user !== 'library') {
          // 2. 尝试作为官方镜像进行重试, e.g., /nginx/latest -> library/nginx:latest
          const officialUser = 'library';
          const officialRepo = pathSegments[0]; // 原始请求的第一个段是 repo
          const officialTag = pathSegments[1]; // 原始请求的第二个段是 tag
          
          digest = await fetchDockerDigest(officialUser, officialRepo, officialTag);
          
        } else {
          // 否则，抛出原始错误
          throw e;
        }
      }
    } else {
        // 路径段小于 1
        throw new Error('Usage: /<user>/<repo>/[tag] or /<repo>/[tag]');
    }

    // 3. 返回 digest 结果
    return new Response(digest, {
      headers: {
        'Content-Type': 'text/plain',
        // 增加缓存控制，避免重复查询 Docker Hub
        'Cache-Control': 'public, max-age=300, s-maxage=300' // 缓存 5 分钟
      }
    });

  } catch (error) {
    // 统一处理错误响应
    console.error('Error:', error.message);
    const message = error.message;
    let status = 500;
    
    // 根据错误信息判断状态码
    if (message.startsWith('Usage:')) {
      status = 400; // 用户请求格式错误
    } else if (message.includes('Status 404')) {
      status = 404; // 镜像未找到
    } else if (message.startsWith('Upstream error:')) {
      // 尝试从错误信息中提取状态码
      const match = message.match(/Status (\d+)/);
      status = match ? parseInt(match[1]) : 400; // 默认 400
    } else if (message.includes('Digest not found')) {
      status = 404; // 标签存在但 digest 缺失
    }
    
    // 返回包含详细错误信息的响应
    return new Response(message, { status: status });
  }
}
