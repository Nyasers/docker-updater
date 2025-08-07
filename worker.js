addEventListener('fetch', event => {
  event.respondWith(handleRequest(event.request));
});

async function handleRequest(request) {
  const url = new URL(request.url);

  // 从 URL 路径中提取 user, repo 和 tag
  const path = url.pathname.split('/').filter(p => p !== '');
  
  // 路径必须至少包含 user 和 repo
  if (path.length < 2) {
    return new Response('Usage: /<user>/<repo>/[tag]', { status: 400 });
  }

  const user = path[0];
  const repo = path[1];
  
  // 如果路径中有第三个参数，则使用它作为 tag，否则默认为 'latest'
  const tag = path.length > 2 ? path[2] : 'latest';

  // 构造目标 API 的完整 URL
  const targetUrl = `https://hub.docker.com/v2/repositories/${user}/${repo}/tags/${tag}`;

  // 创建一个新的请求，用于转发到目标 API
  const newRequest = new Request(targetUrl, {
    method: request.method,
    headers: request.headers,
    body: request.body,
    redirect: 'follow'
  });

  // 删除可能导致问题的请求头
  newRequest.headers.delete('host');

  try {
    // 发起新的请求并等待响应
    const response = await fetch(newRequest);

    // 检查响应状态是否成功
    if (!response.ok) {
        return new Response(`Upstream error: ${response.statusText}`, { status: response.status });
    }

    // 解析 JSON 响应
    const json = await response.json();
    
    // 获取顶层的 digest 字段
    const digest = json.digest;

    if (!digest) {
        return new Response('Digest not found in response.', { status: 404 });
    }

    // 返回 digest 作为纯文本响应
    return new Response(digest, {
        headers: {
            'Content-Type': 'text/plain'
        }
    });

  } catch (error) {
    console.error('Error:', error);
    return new Response('Internal Server Error', { status: 500 });
  }
}
