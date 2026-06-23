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

## 这是什么

**fofa-skills** 是一个面向 Claude Code / AI Agent 的 [FOFA](https://fofa.info) 网络空间搜索引擎 Skill。

它解决让 AI 直接调用 FOFA API 时的四个工程痛点：

| 痛点 | 解决方式 |
|------|---------|
| **上下文爆炸** — 单次查询最多 10,000 条，全量塞进 LLM 既浪费又昂贵 | 搜索只返回摘要 + 20 条预览，全量数据存 SQLite，按需 `cache-read` |
| **F 点预算失控** — 翻页消耗 F 点，AI 无脑翻页几秒烧光余额 | `page > 1` 默认硬阻断，必须用户明确授权才放行 |
| **重复调用** — 同一查询反复打 API，浪费配额和时间 | SHA-256 哈希缓存，精确匹配复用，覆盖缓存优化 |
| **频率限制** — FOFA 限制 1 次/秒，连续请求会被 429 | 内置 1 秒限流 + 429 指数退避重试 |

## 特性

- **F 点预算守卫** — 硬安全锁，不是配置开关，`page > 1` 默认拒绝
- **Hash 缓存** — SHA-256(query + fields + page + size) → SQLite，精确匹配
- **摘要输出** — 搜索只返回元信息 + 20 条预览，全量数据在本地按需读取
- **请求限流** — 1 秒间隔 + 429 指数退避
- **账号信息缓存** — 5 分钟 TTL，避免每次查询都调 info API
- **审计日志** — 每次操作自动记录，可按日期清理
- **零 pip 依赖** — 仅使用 Python 标准库
- **AI 优先 CLI** — stdout 输出结构化 JSON，专为 LLM tool-calling 设计

## 安装

```bash
git clone https://github.com/keyblues/fofa-skills.git
cd fofa-skills

# 设置 API KEY（从 https://fofa.info 个人中心获取）
export FOFA_KEY="your_32_char_api_key"

# 验证账号
python scripts/fofa_smart.py info
```

> 也可用 `pip install -e .` 安装为全局 `fofa-skills` 命令，但**不安装任何第三方包**——仅注册入口点。

## 架构

```
┌─────────────────────────────────────────────────┐
│                 Claude Code / AI                 │
│          调用 fofa_smart.py 子命令                │
└──────────────┬──────────────────────────────────┘
               │
     ┌─────────▼──────────┐
     │   fofa_smart.py    │  编排 CLI（14 个子命令）
     └──┬──────────────┬──┘
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

**14 个子命令**：`info` · `search` · `stats` · `host` · `cache-read` · `cache-delete` · `cache-clean` · `cache-stats` · `cache-list` · `cache-tag` · `correlate` · `report` · `audit-log` · `audit-clean`

## 项目结构

```
fofa-skills/
├── SKILL.md                      # Claude Code Skill 指令（精简版）
├── docs/
│   ├── playbooks.md              # 5 个资产发现 Playbooks + 7 维度模型
│   ├── command-reference.md      # 14 个子命令完整参数参考
│   └── fofa-syntax.md            # FOFA 查询语法参考
├── scripts/
│   ├── fofa_errors.py            # 统一 JSON 错误信封 + stderr 日志
│   ├── fofa_cache.py             # SQLite 缓存层
│   ├── fofa_api.py               # API 层（限流/重试/F点守卫/业务错误检测）
│   └── fofa_smart.py             # CLI 入口
├── examples/
│   └── sample-outputs.txt        # 示例输出
├── data/
│   └── fofa_cache.db             # 首次运行时自动创建
├── README.md                     # 项目说明（中文）
├── README_EN.md                  # Project overview (English)
├── CHANGELOG.md                  # 版本记录
├── CONTRIBUTING.md               # 贡献指南
├── pyproject.toml                # 项目元数据
└── LICENSE                       # MIT
```

## 设计原则

- **零依赖**：只用标准库，克隆即用，不污染环境
- **安全优先**：F 点硬阻断、审计日志、拒绝规则内置
- **AI 友好**：JSON 输出、`__fofa__` 标记、摘要而非全量
- **缓存精确**：只做精确 hash 匹配，不拆分查询语句，宁多调不错用

> **并发说明**：内置限流（1 req/s）基于单进程全局变量，适用于单 Claude Code 会话。多进程/多线程嵌入需自行外加限流。

## F 点预算守卫

这是**硬安全锁**，不是配置开关：

- **默认**：仅 `page=1`，F 点零消耗
- **解锁**：用户明确说"可以消耗F点"后，AI 才会传 `--allow-fpoints`
- **范围**：单次生效，每次翻页都需确认

## 缓存策略

- **精确 hash 匹配**：query + fields + full + page + size 全部参与 hash
- **覆盖缓存优化**：请求 `page>1` 时自动检测是否已有 `page=1` 缓存能覆盖所需范围
- **TTL**：`full=false` 24 小时，`full=true` 7 天
- **账号信息**：独立缓存，TTL 5 分钟

## FAQ

**Q：免费注册用户能用吗？**
A：不能。注册用户没有 API 权限，每次搜索前会先调 info 接口验证，未付费账号直接拒绝。

**Q：能关闭缓存吗？**
A：`search` 支持 `--no-cache` 跳过缓存，但不建议常规使用。如需新鲜数据，缩短 TTL 或手动 `cache-clean`。

**Q：能当独立 CLI 工具用吗？**
A：可以。所有输出都是结构化 JSON，脱离 AI 也能直接使用。

**Q：为什么不做查询语句的包含匹配复用？**
A：故意的。FOFA 语法复杂，拆分/包含匹配容易出错。安全优先，只做精确 hash 匹配。

**Q：审计日志记录了什么？**
A：时间戳、子命令、查询内容、参数、结果码、耗时。可用 `audit-log` 查看、`audit-clean` 清理。

## 参与贡献

见 [CONTRIBUTING.md](CONTRIBUTING.md)。欢迎 PR，请保持零依赖原则。

## 许可

MIT — 见 [LICENSE](LICENSE)。
