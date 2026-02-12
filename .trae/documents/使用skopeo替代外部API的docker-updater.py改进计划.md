# 使用skopeo替代外部API的docker-updater.py改进计划

## 1. 分析当前代码

当前`docker-updater.py`的主要功能是：
- 从配置文件加载API地址
- 检查系统中可用的容器工具（Docker或Podman）
- 获取正在运行的Compose项目
- 解析镜像字符串，提取镜像信息
- **从外部API获取镜像的最新digest**
- 更新Compose文件中的镜像为带最新digest的版本
- 执行部署流程（pull、down、update、up）
- 清理旧镜像

## 2. 改进方案

### 2.1 移除外部API依赖
- 删除`DIGEST_API_BASE_URL`配置项
- 修改`load_config()`函数，不再需要API配置
- 移除`requests`库的使用

### 2.2 添加Skopeo支持
- 添加`check_skopeo_availability()`函数，检查Skopeo是否可用
- 修改`get_latest_digest()`函数，使用Skopeo命令获取镜像digest
- 在主流程中集成Skopeo检查

### 2.3 核心函数修改
1. **修改`load_config()`**：
   - 简化配置加载，移除API URL相关代码
   - 创建简化版的config.json模板

2. **添加`check_skopeo_availability()`**：
   - 检查系统是否安装了Skopeo
   - 如果未安装，给出明确的错误信息和安装建议

3. **重写`get_latest_digest()`**：
   - 使用`skopeo inspect`命令获取镜像元数据
   - 从输出中提取digest信息
   - 处理不同镜像仓库的情况

4. **修改`main()`**：
   - 在工具检查阶段添加Skopeo检查
   - 移除API URL相关的验证

## 3. 优势

- **无外部依赖**：不再需要配置和依赖外部API服务
- **更可靠**：直接与镜像仓库交互，获取最准确的信息
- **更安全**：减少网络请求，降低安全风险
- **更灵活**：支持更多的镜像仓库和认证方式
- **跨平台**：Skopeo在主流操作系统上都可用

## 4. 实施步骤

1. 修改配置加载逻辑
2. 添加Skopeo可用性检查
3. 重写获取digest的函数
4. 更新主流程集成
5. 测试功能完整性

## 5. 预期结果

- 脚本不再需要外部API配置
- 能够使用Skopeo获取镜像的最新digest
- 保持原有的部署流程和功能
- 提供清晰的错误信息和用户指导