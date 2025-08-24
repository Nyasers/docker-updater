// Worker 脚本的入口点，监听 fetch 事件
addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request));
});

/**
 * 解析请求的 URL 路径，提取 user, repo 和 tag
 * @param {string} pathname 请求的 URL 路径名
 * @returns {{user: string, repo: string, tag: string}} 包含 user, repo 和 tag 的对象
 * @throws {Error} 如果路径无效则抛出错误
 */
function parseRequestPath(pathname) {
  // 过滤掉空字符串，得到路径段
  const path = pathname.split('/').filter(p => p !== '');
  
  // 路径必须至少包含 user 和 repo
  if (path.length < 2) {
    throw new Error('Usage: /<user>/<repo>/[tag]');
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
    throw new Error(`Upstream error: ${response.statusText}`);
  }

  const json = await response.json();
  const digest = json.digest;
  
  // 检查响应中是否包含 digest
  if (!digest) {
    throw new Error('Digest not found in response.');
  }
  
  return digest;
}

/**
 * 主处理函数，负责处理传入的请求
 * @param {Request} request 传入的请求对象
 * @returns {Response} 返回一个响应对象
 */
async function handleRequest(request) {
  try {
    const url = new URL(request.url);
    
    // 1. 解析请求路径
    const { user, repo, tag } = parseRequestPath(url.pathname);

    // 2. 从 Docker Hub 获取 digest
    const digest = await fetchDockerDigest(user, repo, tag);
    
    // 3. 返回 digest 作为纯文本响应
    return new Response(digest, {
      headers: {
        'Content-Type': 'text/plain'
      }
    });

  } catch (error) {
    console.error('Error:', error.message);
    // 根据错误类型返回不同的响应
    if (error.message.startsWith('Usage:')) {
      return new Response(error.message, { status: 400 });
    } else if (error.message.startsWith('Upstream error:')) {
      return new Response(error.message, { status: 400 }); // Docker Hub 状态码通常是 404
    } else if (error.message.startsWith('Digest not found:')) {
      return new Response(error.message, { status: 404 });
    } else {
      return new Response('Internal Server Error', { status: 500 });
    }
  }
}
