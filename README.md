# fofa-skills

<p align="center">
  <b>FOFA 网络空间搜索引擎 · Claude Code Skill</b><br>
  资产发现 · 漏洞测绘 · 威胁情报 · 指纹识别<br>
  自带缓存、F 点预算守卫，零 pip 依赖。
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.9%20%7C%203.10%20%7C%203.11%20%7C%203.12%20%7C%203.13-blue" alt="Python versions">
  <img src="https://img.shields.io/badge/dependencies-zero-brightgreen" alt="Zero pip dependencies">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <a href="README_EN.md">English</a>
</p>

---

## 为什么需要 fofa-skills？

FOFA 的 API 很强大，但让 AI 直接调用会遇到几个工程问题：

- **上下文爆炸** — 单次查询最多返回 10,000 条，全量塞进 LLM 上下文既浪费又昂贵
- **F 点预算** — 翻页消耗 F 点，AI 无脑翻页几秒就能烧光余额
- **重复调用** — 同一条查询反复打 API，浪费配额和时间
- **频率限制** — FOFA 限制 1 次/秒，连续请求会被 429

fofa-skills 一次性解决所有这些问题。它是一个 **Claude Code Skill + 工具脚本** 组合，在 FOFA API 之上封装了缓存、限流、F 点硬阻断和 AI 优化的输出格式。

## 特性

| 特性 | 实现方式 |
|------|---------|
| **F 点预算守卫** | Page > 1 默认硬阻断，仅用户明确说"可以消耗F点"才放行 |
| **Hash 缓存** | SHA-256(query + fields + page + size) → SQLite，精确匹配复用 |
| **摘要输出** | 搜索只返回元信息 + 20 条预览，全量数据在 SQLite 中按需读取 |
| **请求限流** | 内置 1 秒间隔 + 429 指数退避重试 |
| **账号信息缓存** | 5 分钟 TTL，避免每次查询都调 info API |
| **零 pip 依赖** | sqlite3、urllib、json、hashlib、argparse —— 全部 stdlib |
| **AI 优先 CLI** | stdout 输出结构化 JSON，专为 LLM tool-calling 设计 |

## 快速开始

```bash
git clone https://github.com/keyblues/fofa-skills.git
cd fofa-skills

# 设置 API KEY（从 https://fofa.info 个人中心获取）
export FOFA_KEY="your_32_char_api_key"

# 验证账号
python scripts/fofa_smart.py info

# 搜索 — 返回摘要，全量数据自动存入缓存
python scripts/fofa_smart.py search -q 'host=".edu" && port="443"' -f "ip,port,host,title"

# 读取缓存 — 过滤 + 分页
python scripts/fofa_smart.py cache-read --hash "<query_hash>" --filter "country=CN" -p 1 -s 50

# 缓存统计
python scripts/fofa_smart.py cache-stats

# 清理 30 天前的缓存
python scripts/fofa_smart.py cache-clean --days 30
```

## 使用场景

### 资产发现
```bash
# 发现某域名下所有资产
python scripts/fofa_smart.py search -q 'domain="example.com"'

# 发现暴露的数据库
python scripts/fofa_smart.py search -q 'protocol="mysql" && country="CN"'

# 查找某 IP 段的所有服务
python scripts/fofa_smart.py search -q 'ip="1.1.1.0/24"'
```

### 漏洞测绘
```bash
# 查找受影响版本的 Apache
python scripts/fofa_smart.py search -q 'server="Apache/2.4.49"' --full

# Log4j 受影响资产
python scripts/fofa_smart.py search -q 'app="Log4j"'

# 特定 CVE 影响的组件
python scripts/fofa_smart.py search -q 'body="ThinkPHP" && header="5.0"'
```

### 威胁情报
```bash
# SSL 证书指纹关联
python scripts/fofa_smart.py search -q 'cert="CN=*.suspicious-domain.com"'

# 查找相同 title 的可疑站点
python scripts/fofa_smart.py search -q 'title="钓鱼登录"'
```

### 指纹识别
```bash
# Favicon hash 定位
python scripts/fofa_smart.py search -q 'icon_hash="-247388890"'

# 服务器指纹
python scripts/fofa_smart.py search -q 'header="nginx/1.18.0"'
```

### 统计聚合与主机信息
```bash
# 统计某组件的端口分布
python scripts/fofa_smart.py stats -q 'app="Apache"' -f "port"

# 统计某国家的资产协议分布
python scripts/fofa_smart.py stats -q 'country="CN"' -f "protocol"

# 查看指定 IP 的详细信息
python scripts/fofa_smart.py host --host "1.1.1.1" --detail
```

---

## 版本

```bash
python scripts/fofa_smart.py --version
# fofa-skills 0.1.0
```

## 架构

```
┌─────────────────────────────────────────────────┐
│                 Claude Code / AI                 │
│          调用 fofa_smart.py 子命令                │
└──────────────┬──────────────────────────────────┘
               │
     ┌─────────▼──────────┐
     │   fofa_smart.py    │  编排 CLI
     │   (10 个子命令)     │  · info / search / stats / host
     └──┬──────────────┬──┘  · cache-read / delete / export / clean / stats
        │              │     · audit-log
        │              │
   ┌────▼────┐   ┌─────▼──────┐
   │fofa_api │   │ fofa_cache │
   │ HTTP    │   │  SQLite    │
   │ 限流重试 │   │  哈希缓存   │
   │ F点守卫 │   │  过滤分页   │
   └────┬────┘   └────────────┘
        │
   ┌────▼────┐
   │  FOFA   │
   │  API    │
   └─────────┘
```

## 项目结构

```
fofa-skills/
├── SKILL.md                 # Claude Code Skill 指令
├── README.md                # 项目说明（中文）
├── README_EN.md             # Project overview (English)
├── LICENSE                  # MIT
├── CONTRIBUTING.md          # 贡献指南
├── CHANGELOG.md             # 版本记录
├── pyproject.toml           # 项目元数据
├── .env.example             # 环境变量模板
├── scripts/
│   ├── fofa_errors.py       # 统一 JSON 错误信封 + stderr 日志
│   ├── fofa_cache.py        # SQLite 缓存层
│   fofa_api.py          # API 层（限流/重试/F点守卫/业务错误检测）
│   └── fofa_smart.py    # CLI 入口（AI 调用界面 + 审计日志）
├── examples/
│   └── sample-outputs.txt   # 示例输出
└── data/
    └── fofa_cache.db        # 首次运行时自动创建
```

## F 点预算守卫

这是一个**硬安全锁**，不是配置开关。

```python
# fofa_api.py — 每次 search() 调用
if page > 1 and not allow_fpoints:
    return {"error": True, "msg": "F点消耗被拒绝", "code": 2001}
```

- **默认**：仅 page=1，F 点零消耗
- **解锁**：用户明确说"可以消耗F点" / "允许使用F点"后，AI 才会传 `--allow-fpoints`
- **范围**：单次生效，每次翻页都需确认

## 缓存策略

- **精确 hash 匹配**：query + fields + full + page + size 全部参与 hash，只做精确命中的缓存复用
- **不做拆分匹配**：`host=".edu"` 和 `host=".edu" && port="443"` 是两个独立缓存，宁多调一次 API 也不错用缓存
- **覆盖缓存优化**：请求 page>1 时，自动检测是否已有 page=1 的缓存数据能覆盖所需范围，避免重复 API 调用
- **TTL**：`full=false` 24 小时，`full=true` 7 天
- **账号信息**：独立缓存，TTL 5 分钟

## FAQ

**Q：免费注册用户能用吗？**
A：不能。注册用户没有 API 权限，每次搜索前会先调 info 接口验证，未付费账号直接拒绝。

**Q：能关闭缓存吗？**
A：缓存是上下文管理设计的核心部分，不建议关闭。如需新鲜数据，缩短 TTL 或手动 `cache-clean`。

**Q：FOFA 的 `full=true` 全量模式支持吗？**
A：支持，通过 `--full` 参数。缓存 TTL 自动延长至 7 天。

**Q：能当独立 CLI 工具用吗？**
A：可以。所有输出都是结构化 JSON，脱离 AI 也能直接使用。

**Q：为什么不做查询语句的包含匹配复用？**
A：故意的。FOFA 语法复杂，拆分/包含匹配容易出错。安全优先，只做精确 hash 匹配。

**Q：审计日志记录了什么？**
A：每次操作记录时间戳、子命令、查询内容、参数、结果码和耗时。用 `audit-log` 子命令查看。

**Q：支持哪些 FOFA 查询字段？**
A：除了基础字段（ip, port, protocol, host, domain, title, server, body, header, banner, cert, icon_hash），还支持 cert.subject, cert.issuer, jarm, icp, cname, mf_hash, body_hash 等高级字段。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。欢迎 PR，请保持零依赖原则。

## 许可

MIT — 见 [LICENSE](LICENSE)。
