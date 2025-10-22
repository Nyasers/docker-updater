// Worker 脚本的入口点，监听 fetch 事件
addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request));
});

// V2 兼容的容器镜像仓库别名及其 API 域名映射
const REGISTRIES = {
  // 别名: V2 API 域名
  'ghcr': 'ghcr.io',
  'gcr': 'gcr.io',
  // 'docker' 是默认的 Docker Hub
  'docker': 'registry-1.docker.io',
};
const DEFAULT_REGISTRY_URL = REGISTRIES.docker;

// 定义自动回退时需要尝试的注册中心列表
// official: true 表示该仓库需要特殊的 "library/" 官方镜像回退逻辑 (目前只有 Docker Hub)
const SEARCH_REGISTRIES = [
  { alias: 'docker', url: DEFAULT_REGISTRY_URL, official: true },
  { alias: 'ghcr', url: REGISTRIES.ghcr, official: false },
  { alias: 'gcr', url: REGISTRIES.gcr, official: false },
];

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
 * 从 V2 兼容的容器镜像仓库 API 获取指定镜像的 digest (通过 manifest)
 * @param {string} registryUrl 目标镜像仓库的 V2 API 域名 (e.g., 'registry-1.docker.io')
 * @param {string} user 镜像的用户名 (e.g., 'library' 或 'myuser')
 * @param {string} repo 镜像的仓库名 (e.g., 'nginx')
 * @param {string} tag 镜像的标签 (e.g., 'latest')
 * @param {string | null} authToken 可选的认证令牌 (e.g., Bearer token)
 * @returns {Promise<string>} 返回镜像的 digest
 * @throws {Error} 如果 API 请求或响应失败则抛出错误
 */
async function fetchV2Digest(registryUrl, user, repo, tag, authToken) {
  // 构造 repo path。对于官方镜像（Docker Hub），user是'library'，路径只有'repo'。
  const repoPath = user === 'library' ? repo : `${user}/${repo}`;
  // V2 Manifest Endpoint 格式: https://<registry>/v2/<repo_path>/manifests/<tag>
  const targetUrl = `https://${registryUrl}/v2/${repoPath}/manifests/${tag}`;
  
  // V2 API 的标准 Accept 头部
  const headers = { 
    // 请求 Manifest V2 格式，这是获取 Docker-Content-Digest 的标准方式
    'Accept': 'application/vnd.docker.distribution.manifest.v2+json'
  };

  // 如果提供了 AuthToken，则添加到请求头
  if (authToken) {
      // 传递给上游仓库的认证信息使用 Bearer 格式
      headers['Authorization'] = `Bearer ${authToken}`;
  }

  const newRequest = new Request(targetUrl, {
    method: 'GET',
    headers: headers,
    redirect: 'follow'
  });

  // 删除可能导致问题的请求头
  newRequest.headers.delete('host');

  const response = await fetch(newRequest);

  // 检查响应状态是否成功
  if (!response.ok) {
    // 捕获 4xx/5xx 错误，并附带状态码
    const statusText = response.statusText || `Status ${response.status}`;
    let errorMessage = `Upstream error: ${statusText} from ${registryUrl}`;
    
    // 特殊处理 401 Unauthorized，提示需要认证
    if (response.status === 401) {
        errorMessage = `Upstream error: Status 401 Unauthorized. The registry (${registryUrl}) likely requires an explicit authentication token, which this simple Worker does not fetch.`;
    }

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

  // 1. 尝试从响应头中获取标准的 Docker Content Digest (这是 V2 API 的标准做法)
  const digest = response.headers.get('Docker-Content-Digest');
  
  if (digest) {
    return digest;
  }
  
  // 2. 尝试从 JSON 响应体中获取 (兼容 Docker Hub 早期或特定 API)
  try {
    const json = await response.json();
    const bodyDigest = json.digest || json.images?.[0]?.digest; 
    if (bodyDigest) {
        return bodyDigest;
    }
  } catch (e) {
    // 忽略 JSON 解析错误，继续抛出未找到 digest 的错误
  }
  
  throw new Error('Digest not found in response header or body.');
}

/**
 * 创建成功的 Response 对象
 * @param {string} digest 镜像的 digest
 * @returns {Response}
 */
function createSuccessResponse(digest) {
    return new Response(digest, {
        headers: {
            'Content-Type': 'text/plain',
            // 增加缓存控制，避免重复查询
            'Cache-Control': 'public, max-age=300, s-maxage=300' // 缓存 5 分钟
        }
    });
}

/**
 * 主处理函数，负责处理传入的请求
 * @param {Request} request 传入的请求对象
 * @returns {Response} 返回一个响应对象
 */
async function handleRequest(request) {
  const url = new URL(request.url);
  
  // **认证逻辑：从 Authorization Header 中读取令牌 (标准和安全的方法)**
  let authToken = request.headers.get('Authorization');
  if (authToken && authToken.startsWith('Bearer ')) {
      // 提取 Bearer 后面的实际令牌
      authToken = authToken.substring(7).trim(); 
  }
  
  // 获取并过滤掉空字符串，得到路径段
  const pathSegments = url.pathname.split('/').filter(p => p !== '');
  
  let digest;

  try {
    
    // --- 案例 1: 明确指定注册中心，无回退逻辑 (Unambiguous Explicit or Docker Shorthand) ---
    if (REGISTRIES[pathSegments[0]]) {
      const registryAlias = pathSegments[0];
      const registryUrl = REGISTRIES[registryAlias];
      
      let user, repo, tag;
      
      // 1. Docker Shorthand: /docker/nginx (2 segments) 或 /docker/nginx/latest (3 segments)
      const isDockerShorthand = registryAlias === 'docker' && pathSegments.length >= 2 && pathSegments.length <= 3;
      
      // 2. Unambiguous Explicit: /ghcr/user/repo/tag (4+ segments) 或 /docker/user/repo/tag (4+ segments)
      // 路径有 4 段或更多时，明确跳过回退逻辑，视为显式指定。
      const isUnambiguousExplicit = pathSegments.length >= 4;

      if (isDockerShorthand || isUnambiguousExplicit) {
          
          if (isDockerShorthand) {
              // 格式: /docker/nginx -> library/nginx:latest
              // 格式: /docker/nginx/latest -> library/nginx:latest
              user = 'library';
              repo = pathSegments[1];
              tag = pathSegments.length === 3 ? pathSegments[2] : 'latest';
          } else { // isUnambiguousExplicit (4+ segments)
              // 适用于：/ghcr/myuser/myrepo/tag (4段) 或 /docker/myuser/myrepo/tag (4段)
              // slice(1) 移除别名段
              const subPathname = '/' + pathSegments.slice(1).join('/');
              const parsed = parseRequestPath(subPathname);
              user = parsed.user;
              repo = parsed.repo;
              tag = parsed.tag;
          }
          
          digest = await fetchV2Digest(registryUrl, user, repo, tag, authToken); // 传入 authToken
          return createSuccessResponse(digest);
          
      } 
      // 如果是非 Docker 别名，且路径长度为 2 或 3 (e.g., /ghcr/myrepo)，则会跳出此 if 块，
      // 进入 Case 2/3 (自动回退) 流程，以检查 Docker Hub 上是否存在同名用户。
    }
    
    // --- 案例 2 & 3: 默认 Docker Hub 或需要回退的路径 (Automatic Fallback Loop) ---
    // 包含所有 1 段路径，以及所有可能与注册中心别名冲突的 2 段/3 段路径（如 /ghcr/repo）
    if (pathSegments.length >= 1) {
        
        // 如果用户只输入了 /ghcr，这属于用法错误
        if (pathSegments.length === 1 && REGISTRIES[pathSegments[0]]) {
            throw new Error('Usage: /<registry>/<user>/<repo>/[tag] or /<user>/<repo>/[tag] or /<repo>/[tag]');
        }
        
        let initialUser, initialRepo, initialTag;
        
        // 定义初始的 user/repo/tag
        if (pathSegments.length === 1) {
            // 1 段路径: /nginx -> 默认为官方镜像 library/nginx:latest。我们将其分解为 repo=nginx
            initialUser = pathSegments[0]; // 此时 initialUser 实际上是 repo 名称
            initialRepo = 'DUMMY'; // 占位符
            initialTag = 'latest';
        } else {
            // 2+ 段路径: /myuser/myrepo/tag -> user=myuser, repo=myrepo, tag=tag
            const parsedPath = parseRequestPath(url.pathname);
            initialUser = parsedPath.user;
            initialRepo = parsedPath.repo;
            initialTag = parsedPath.tag;
        }

        const errors = []; // 用于存储所有失败的尝试
        
        // 自动回退循环：尝试 Docker Hub, GHCR, GCR
        for (const registry of SEARCH_REGISTRIES) {
            let attemptUser, attemptRepo, attemptTag;
            
            // 1. 标准尝试 (适用于所有仓库)
            if (pathSegments.length === 1) {
                 // 1 段路径: /nginx -> library/nginx:latest
                 attemptUser = 'library';
                 attemptRepo = pathSegments[0];
                 attemptTag = 'latest';
            } else {
                 // 2+ 段路径: /user/repo -> user/repo:tag
                 attemptUser = initialUser;
                 attemptRepo = initialRepo;
                 attemptTag = initialTag;
            }

            try {
                digest = await fetchV2Digest(registry.url, attemptUser, attemptRepo, attemptTag, authToken); // 传入 authToken
                return createSuccessResponse(digest); // 成功! 立即返回
            } catch (e) {
                
                // 检查是否为 Docker Hub 2 段路径失败，且需要尝试官方镜像回退
                const isDockerHubTwoSegmentFailure = (
                    registry.alias === 'docker' && 
                    pathSegments.length === 2 && 
                    attemptUser !== 'library'
                );

                if (isDockerHubTwoSegmentFailure) {
                    // Docker Hub 官方镜像回退逻辑: /nginx/latest 失败后，尝试 library/nginx:latest
                    attemptUser = 'library';
                    attemptRepo = initialUser; // 原始路径的第一段是 repo 名
                    attemptTag = initialRepo;  // 原始路径的第二段是 tag 名

                    try {
                        digest = await fetchV2Digest(registry.url, attemptUser, attemptRepo, attemptTag, authToken); // 传入 authToken
                        return createSuccessResponse(digest); // Docker Hub 官方成功! 立即返回
                    } catch (e2) {
                        errors.push(`Attempt failed on ${registry.alias} (Official fallback): ${e2.message}`);
                    }
                }
                
                // 如果错误不是 404 (未找到)，则停止回退并抛出该特定错误。
                if (!e.message.includes('Status 404') && !e.message.includes('Upstream error: Status 404')) {
                    // 只有在非 404/401 错误时才停止回退，因为 401 错误在其他仓库可能依然成功。
                    if (!e.message.includes('Status 401')) {
                        throw new Error(`Non-404/401 error from ${registry.alias}. Stopping fallback: ${e.message}`);
                    }
                }
                
                // 如果是 404 或 401，存储错误信息，继续尝试下一个注册中心。
                errors.push(`Attempt failed on ${registry.alias} (Standard): ${e.message}`);
            }
        }
        
        // 如果循环结束仍未找到，则抛出最终的 404 错误
        throw new Error(`Image not found on any default registry (Docker Hub, GHCR, GCR). Last attempt errors: ${errors.join(' | ')}`);

    } else {
        // 路径段小于 1
        throw new Error('Usage: /<registry>/<user>/<repo>/[tag] or /<user>/<repo>/[tag] or /<repo>/[tag]');
    }

  } catch (error) {
    // 统一处理错误响应
    console.error('Error:', error.message);
    const message = error.message;
    let status = 500;
    
    // 根据错误信息判断状态码
    if (message.startsWith('Usage:')) {
      status = 400; // 用户请求格式错误
    } else if (message.includes('Status 404') || message.includes('Image not found')) {
      status = 404; // 镜像未找到
    } else if (message.includes('Status 401')) {
      status = 401; // 认证错误
    } else if (message.startsWith('Upstream error:')) {
      // 尝试从错误信息中提取状态码
      const match = message.match(/Status (\d+)/);
      status = match ? parseInt(match[1]) : 400; 
    } else if (message.includes('Digest not found')) {
      status = 404; // 标签存在但 digest 缺失
    }
    
    // 返回包含详细错误信息的响应
    return new Response(message, { status: status });
  }
}
