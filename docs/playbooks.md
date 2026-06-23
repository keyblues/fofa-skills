# Asset Discovery Playbooks

> Extracted from SKILL.md. This document contains the 7-dimension asset discovery model, query optimization techniques, 5 detailed playbooks, de-duplication strategy, risk prioritization, F-point budget strategy, and cross-engine validation.

## Asset Discovery Playbooks (CRITICAL — Read Before Recon)

> **Why this section exists**: Single-dimension queries always miss assets. An organization's true exposure spans 7 dimensions — domain, IP, certificate, fingerprint, organization, time, and network. These Playbooks enforce multi-dimensional coverage so you find assets others miss. Follow them strictly; do not skip steps.

### The 7-Dimension Asset Discovery Model

Every asset exists simultaneously in 7 dimensions. Querying only 1-2 dimensions is the #1 cause of incomplete asset inventory:

| Dimension | FOFA Fields | What It Catches | What It Misses Alone |
|-----------|-------------|-----------------|---------------------|
| **Domain** | `domain`, `host` | Assets indexed by hostname | IPs without DNS, cert-only assets |
| **IP** | `ip` (incl. CIDR) | All services on a host | Shared-hosting neighbors, CDN-shadowed origins |
| **Certificate** | `cert`, `cert.subject`, `cert.issuer` | TLS-bound assets, SAN domains | Non-TLS services (HTTP, SSH, DBs) |
| **Fingerprint** | `icon_hash`, `jarm`, `body_hash`, `mf_hash` | Same app/framework instances | Custom/unique fingerprints |
| **Organization** | `icp`, `org`, `asn` | Org-owned assets across domains | Third-party hosted, unregistered |
| **Time** | `after`, `before`, `--full` | Historical/exposed-then-fixed assets | Currently live only (without `--full`) |
| **Network** | `port`, `protocol`, `server`, `banner` | Service-level exposure | Non-standard ports, custom protocols |

**Rule**: For any "find all assets of X" request, execute at least 5 of 7 dimensions. For full exposure assessment, execute all 7.

### Query Optimization: How to Find More Than Others

These techniques maximize asset coverage. Apply them within every Playbook:

#### 1. Hostname Wildcards — Cover All Subdomains
```
# ❌ MISS: only matches exact domain
domain="example.com"

# ✅ CATCH ALL: leading dot matches all subdomains
host=".example.com"

# ✅ BROADEST: combine both
host="example.com" || host=".example.com"
```
> `host=".example.com"` matches `www.example.com`, `api.example.com`, `dev.internal.example.com` — all subdomains. `domain=` only matches the exact apex.

#### 2. Certificate SAN Reverse Lookup — Discover Hidden Subdomains
Certificates list all covered domains in Subject Alternative Names (SAN). Querying cert fields finds subdomains that DNS might not reveal:
```bash
# Find ALL domains covered by a wildcard cert
search -q 'cert.subject="CN=*.example.com"' -f "host,domain,ip"

# Broader: any cert mentioning the org name
search -q 'cert="example.com"' -f "host,ip,title"

# Find self-signed certs (potential dev/staging infra that bypasses CA)
search -q 'cert.subject="CN=*.example.com" && cert.issuer="CN=*.example.com"'
```

#### 3. IP Pivot — Find Co-hosted Domains
After finding IPs for a target, reverse-pivot to discover other domains on the same server (shared hosting = shared risk):
```bash
# Step 1: Get IPs
search -q 'domain="target.com"' -f "ip"

# Step 2: For each IP, find OTHER domains (exclude known)
search -q 'ip="1.2.3.4" && domain!="target.com"' -f "domain,host,title"
```

#### 4. ICP Filing Correlation — Org-Wide Asset Discovery (China)
Chinese ICP filing numbers link all domains owned by one organization. One filing → all domains:
```bash
# Find ALL domains under same ICP filing
search -q 'icp="京ICP备12345678号"' -f "domain,host,title"

# ICP + port: find exposed admin panels across org
search -q 'icp="京ICP备12345678号" && (port="8080" || port="8443" || port="9090")'
```

#### 5. ASN Pivot — Discover Org-Owned IP Ranges
Organizations often own entire AS numbers. Query by ASN to find all IPs in their network:
```bash
# All assets in an organization's AS
search -q 'asn="15169"' -f "ip,host,port,title"

# ASN + high-risk ports
search -q 'asn="15169" && (port="3389" || port="22" || port="3306")'
```

#### 6. Fingerprint Correlation — Find Same Application Instances
Same favicon/JARM/body hash = same application deployment. Use to find all instances of a target's app:
```bash
# Step 1: Get target's fingerprints
# Note: icon_hash/body_hash may require higher FOFA tier. If 820001 error, use jarm/cert instead.
search -q 'domain="target.com"' -f "ip,host,jarm,cert"              # unrestricted fields
search -q 'domain="target.com"' -f "ip,host,icon_hash,jarm"         # if icon_hash permitted

# Step 2: Pivot by JARM (same TLS config = same infra team) — works for all tiers
search -q 'jarm="29d29d15d29d29d000..."' -f "host,ip,port"

# Step 3: Pivot by icon_hash (same favicon = same org's app) — may need higher tier
# If 820001 error: skip this step, use cert/banner/header as fallback
search -q 'icon_hash="-247388890"' -f "host,ip,title,domain"

# Step 4: Pivot by body_hash (identical page = same template/deployment) — may need higher tier
search -q 'body_hash="abc123..."' -f "host,ip,title"
```

#### 7. CNAME Chain Tracing — Find CDN Origin and Related Domains
CNAME records reveal DNS aliases. Query to find domains pointing to your target's infrastructure:
```bash
# Find all domains with CNAME pointing to target
search -q 'cname="cdn.target.com"' -f "host,domain,ip"

# Find CDN origin behind a domain (look for direct IP, not CDN)
search -q 'domain="target.com" && ip!="104.16.0.0/12"' -f "ip,host,title"
```

#### 8. Historical Data — Find Exposed-Then-Fixed Assets
`--full` searches FOFA's entire historical archive. Assets that were exposed but later fixed still appear:
```bash
# Find assets that WERE exposed (may still be vulnerable internally)
search -q 'domain="target.com" && port="3389"' --full -f "ip,host,title"

# Time-bounded: what was exposed last year?
search -q 'domain="target.com" && after="2025-01-01" && before="2025-12-31"' --full
```

#### 9. Non-Standard Port Discovery — Find Hidden Services
Attackers (and devs) hide services on non-standard ports. Exclude common ports to surface them:
```bash
# Exclude 80/443 to find everything else
search -q 'domain="target.com" && port!="80" && port!="443"' -f "ip,port,protocol,host"

# Common admin/management ports
search -q 'domain="target.com" && (port="8080" || port="8443" || port="9090" || port="10000" || port="2222")'

# Database ports (high risk)
search -q 'domain="target.com" && (port="3306" || port="5432" || port="6379" || port="27017" || port="1433" || port="9200")'
```

#### 10. Exclusion Method — Discover Unknown Assets
After mapping known assets, EXCLUDE them to surface the unknown:
```bash
# Known subdomains excluded → reveals forgotten/dev domains
search -q 'host=".target.com" && host!="www.target.com" && host!="api.target.com" && host!="mail.target.com"'

# Exclude default pages to find real applications
search -q 'domain="target.com" && title!="Default Web Site Page" && title!="IIS7" && title!="Welcome to nginx"'
```

#### 11. F-Point Optimization — Free Recon First
Before any paid search, use `stats` (free) to assess scope. Never blindly paginate:
```bash
# FREE: how many assets total?
stats -q 'domain="target.com"' -f "port"

# FREE: country distribution (is org multinational?)
stats -q 'icp="京ICP备12345678号"' -f "country"

# FREE: port distribution (which ports to prioritize?)
stats -q 'host=".target.com"' -f "port"

# THEN: targeted search on high-value ports only (saves F-points)
search -q 'host=".target.com" && (port="3389" || port="22")' -f "ip,host,port"
```

---

### Playbook 1: Full Exposure Assessment (Organization-Wide)

**Trigger**: "查 xx 公司/组织的所有暴露面" / "find all exposed assets of organization X"

**Goal**: Build complete asset inventory across all 7 dimensions. This is the most comprehensive Playbook — execute every step.

**Execution Checklist** (tick each box as you complete it):

Every `search` below carries `--tag target.com` so the whole assessment is grouped under one target. If context compression wipes your in-memory hash list mid-assessment, run `cache-list --tag target.com` to recover every hash — no re-fetch, no re-spend of F-points.

```
□ D1: ICP/ASN → search -q 'icp="..."' --tag target.com
□ D2: Domain  → search -q 'host=".target.com"' --tag target.com
□ D3: Cert    → search -q 'cert.subject="CN=*.target.com"' --tag target.com
□ D4: IP Pivot→ search -q 'ip="x.x.x.x" && domain!="..."' --tag target.com
□ D5: Fingerprint → search -q 'icon_hash="..."' / 'jarm="..."' --tag target.com
□ D6: CNAME   → search -q 'cname="cdn.target.com"' --tag target.com
□ D7: History → search -q '...' --full --tag target.com
□ Recover (if needed) → cache-list --tag target.com
□ Correlate   → correlate --tag target.com --key ip
□ Report      → report --tag target.com
```

> **Why `--tag` instead of `--hashes`**: an assessment spans 7+ searches; their hashes live only in your conversation context. Context compression (inevitable in long tasks) erases them, and `correlate --hashes` would then force a re-fetch — burning F-points a second time for data already cached. `--tag` reads straight from the cache, so the final correlate/report step is free and resilient no matter what context did.

**F-Point Tip**: Ask user to set `FOFA_FPOINTS_BUDGET=1000` before starting to avoid per-request confirmation churn across 7 dimensions.

**Workflow** (execute in order, accumulate results into a unified asset list):

```bash
# === DIMENSION 1: Organization (start here for China targets) ===
# Step 1a: ICP reverse lookup — find all domains under org's filing
stats -q 'icp="京ICP备12345678号"' -f "domain"          # FREE: scope check
search -q 'icp="京ICP备12345678号"' -f "domain,host,title,ip" --tag target.com  # all domains

# Step 1b: ASN lookup — find org-owned IP ranges
search -q 'asn="12345"' -f "ip,host,port,title" --tag target.com

# === DIMENSION 2: Domain ===
# Step 2: For EACH domain found in Step 1, enumerate subdomains
search -q 'host=".target.com"' -f "ip,host,domain,title" --tag target.com           # all subdomains
search -q 'domain="target.com"' -f "ip,host,domain,title" --tag target.com          # apex + www

# === DIMENSION 3: Certificate ===
# Step 3: Find all hosts sharing org's TLS certificates
search -q 'cert.subject="CN=*.target.com"' -f "host,ip,domain" --tag target.com     # wildcard cert
search -q 'cert="target.com"' -f "host,ip,domain" --tag target.com                  # any cert mention
# Find dev/staging via self-signed certs
search -q 'cert.subject="CN=*.target.com" && cert.issuer="CN=*.target.com"' --tag target.com

# === DIMENSION 4: IP Pivot ===
# Step 4: For each unique IP found above, find co-hosted domains
# (repeat for each IP — reveals shared infrastructure)
search -q 'ip="1.2.3.4" && domain!="target.com"' -f "domain,host,title" --tag target.com

# === DIMENSION 5: Fingerprint ===
# Step 5: Get target fingerprints, then pivot
search -q 'domain="target.com"' -f "ip,icon_hash,jarm,body_hash" --tag target.com   # get fingerprints
search -q 'icon_hash="-247388890"' -f "host,ip,domain" --tag target.com             # same favicon
search -q 'jarm="29d29d15d29d29d000..."' -f "host,ip,port" --tag target.com         # same TLS config

# === DIMENSION 6: CNAME ===
# Step 6: Find domains pointing to target's infrastructure
search -q 'cname="cdn.target.com"' -f "host,domain,ip" --tag target.com

# === DIMENSION 7: Time (Historical) ===
# Step 7: Find assets that were exposed but may have changed
search -q 'icp="京ICP备12345678号" && port="3389"' --full -f "ip,host,title" --tag target.com
search -q 'icp="京ICP备12345678号" && after="2025-01-01"' --full -f "ip,host,title" --tag target.com

# === FINAL: Risk-Prioritized Sweep ===
# Step 8: High-risk ports across ALL discovered assets
search -q 'icp="京ICP备12345678号" && (port="3389" || port="22" || port="3306" || port="6379" || port="27017" || port="9200" || port="5900")' -f "ip,host,port,title" --tag target.com

# Step 9: Admin panels and management interfaces
search -q 'icp="京ICP备12345678号" && (title="管理" || title="admin" || title="login" || title="后台" || title="dashboard")' -f "ip,host,title" --tag target.com

# Step 10: Exposed databases and risky services
search -q 'icp="京ICP备12345678号" && (protocol="mysql" || protocol="redis" || protocol="mongodb" || protocol="elasticsearch" || protocol="postgresql")' -f "ip,port,protocol,host" --tag target.com
```

**De-duplication & Reporting**: After all search steps, use `correlate` and `report` (free, local SQLite operations) instead of manual merging. Because every search carried `--tag target.com`, the final steps operate on the whole assessment by tag — no need to enumerate or remember hashes:
```bash
# Step 11: Correlate all queries for this target by IP — see overlap and unique assets
correlate --tag target.com --key ip

# Step 12: Generate full summary report
report --tag target.com

# (Recovery) If context compression wiped your memory of what you searched:
cache-list --tag target.com      # re-surface every hash, query_raw, and result_count
```

> **Forgot `--tag` on earlier searches?** Retroactively group them with `cache-tag --hash <h> --tag target.com` — no re-fetch, no F-point re-spend. Then `correlate --tag` / `report --tag` work as above.

The `report` command outputs: total assets, unique IPs, port/country/protocol/server distributions, high-risk exposed ports, and admin panels — all in one call, no context flooding. Use `--limit N` to cap the high-risk/admin detail rows when context is tight.

**F-Point Budget**: Steps 1-7 use page=1 (free) if size ≤ 100. Steps 8-10 may need pagination. For multi-step assessments, ask user to set `FOFA_FPOINTS_BUDGET=1000` once to avoid per-request confirmation churn. Use `stats` first to estimate scope.

---

### Playbook 2: Vulnerability Impact Assessment

**Trigger**: "CVE-XXXX-XXXX 影响哪些资产" / "what assets are affected by Log4j"

**Workflow**:

```bash
# Step 1: FREE scope assessment — how many affected?
stats -q 'app="Log4j"' -f "country"        # geographic spread
stats -q 'app="Log4j"' -f "port"           # which ports

# Step 2: Precise version match (if version known)
search -q 'app="Apache-Log4j" && body="2.14.0"' -f "ip,host,title,server"

# Step 3: Fingerprint match (icon_hash of vulnerable version)
search -q 'icon_hash="-xxx" && country="CN"' -f "ip,host,title"

# Step 4: Banner/header signature (vulnerability indicator)
search -q 'header="X-Powered-By: vulnerable" && body="exploitable"' -f "ip,host"

# Step 5: Historical exposure (--full finds assets that WERE vulnerable)
search -q 'app="Log4j"' --full -f "ip,host,title,server"

# Step 6: Org-scoped impact (if user specifies organization)
search -q 'icp="京ICP备12345678号" && app="Log4j"' -f "ip,host,title"
```

**AI Behavior**: Explain CVE → component mapping to user (e.g., "CVE-2021-44228 affects Log4j 2.0-beta9 to 2.14.1"). Suggest cross-referencing with Censys/Shodan for global coverage.

---

### Playbook 3: Threat Intelligence & C2 Hunting

**Trigger**: "追踪 C2 基础设施" / "find C2 infrastructure" / "phishing campaign analysis"

**Workflow**:

```bash
# Step 1: JARM fingerprint (known C2 frameworks have known JARM hashes)
search -q 'jarm="07d14d16d21d21d000..."' -f "host,ip,port"
# Common C2 JARM hashes (maintain internal knowledge):
#   Cobalt Strike default: 07d14d16d21d21d000...
#   Metasploit default:    07d14d16d21d21d000...

# Step 2: Certificate anomalies (C2s often use self-signed or suspicious certs)
search -q 'jarm="07d14d16d21d21d000..." && cert.issuer="CN=Unknown"' -f "host,ip"
search -q 'cert.subject="CN=*" && cert.issuer="CN=*"' -f "host,ip"  # self-signed

# Step 3: Infrastructure pivot (find C2's neighbors)
search -q 'ip="1.2.3.4"' -f "host,domain,port,protocol"  # what else is on C2 IP

# Step 4: Phishing detection (same template = same campaign)
search -q 'title="登录" && body="password" && domain!="legitimate.com"' -f "host,ip,title"
search -q 'body_hash="phishing_template_hash"' -f "host,ip,title"  # identical phishing page

# Step 5: Icon-based phishing correlation
search -q 'icon_hash="-247388890" && domain!="legitimate-brand.com"' -f "host,ip,title"

# Step 6: Timeline analysis (when did C2 appear?)
search -q 'jarm="07d14d16d21d21d000..." && after="2025-06-01"' --full -f "host,ip"
```

**AI Behavior**: Warn user this is threat intelligence research. Suggest reporting confirmed C2 to appropriate authorities. Cross-reference with Shodan (IoT/ICS C2) and Censys (academic/research C2).

---

### Playbook 4: Subdomain Discovery

**Trigger**: "找出所有子域名" / "enumerate subdomains of target.com"

**Workflow** (each technique catches different subdomains — run ALL):

```bash
# Technique 1: Host wildcard (broadest DNS-based)
search -q 'host=".target.com"' -f "host,domain,ip"           # all *.target.com
search -q 'host="target.com"' -f "host,domain,ip"            # apex + exact

# Technique 2: Certificate SAN (finds subdomains not in DNS)
search -q 'cert.subject="CN=*.target.com"' -f "host,domain"  # cert-covered
search -q 'cert="target.com"' -f "host,domain"               # any cert mention

# Technique 3: CNAME chain (finds alias targets)
search -q 'cname="target.com"' -f "host,domain,ip"           # who points to target
search -q 'cname="*.target.com"' -f "host,domain,ip"

# Technique 4: ICP (finds org's other domains)
search -q 'icp="京ICP备12345678号"' -f "domain,host"         # all org domains

# Technique 5: Historical (--full finds deprecated subdomains)
search -q 'host=".target.com"' --full -f "host,ip,title"     # was alive before

# Technique 6: Body content (finds subdomains mentioned in pages)
search -q 'body="target.com" && host!=".target.com"' -f "host,ip,title"

# Merge all results, deduplicate by hostname
```

**Why this finds more than others**: Most tools only use Technique 1 (DNS). Certificate SAN (Technique 2) reveals subdomains that DNS doesn't resolve but still have valid certs. CNAME (Technique 3) finds indirect references. Historical (Technique 5) finds decommissioned subdomains that may still have stale configs.

---

### Playbook 5: Fingerprint Identification & Component Mapping

**Trigger**: "识别指纹" / "what application is running on these hosts"

> **Field Permission Warning**: `icon_hash`, `body_hash`, `mf_hash`, `product`, `category` require higher FOFA membership tiers. If a query returns error code 820001 ("field permission denied"), fall back to unrestricted fields: `cert`, `cert.subject`, `cert.issuer`, `jarm`, `banner`, `header`, `server`, `title`. These are available to all paid users.

**Workflow**:

```bash
# Step 1: JARM (TLS fingerprint — works for ALL tiers, start here)
search -q 'domain="target.com"' -f "jarm,host,ip"            # get target's JARM
search -q 'jarm="29d29d15d29d29d000..."' -f "host,ip,port"   # same TLS config

# Step 2: Favicon hash (most reliable for app ID — may need higher tier)
# If 820001 error: skip, use JARM/banner/header instead
search -q 'domain="target.com"' -f "icon_hash,host,ip"       # get target's icon_hash
search -q 'icon_hash="-247388890"' -f "host,ip,title"        # find all same-app instances

# Step 3: Banner-based service ID (works for ALL tiers)
search -q 'banner="SSH-2.0-OpenSSH_8.0"' -f "ip,host,port"   # specific SSH version
search -q 'banner="MySQL 5.7"' -f "ip,host,port"             # specific MySQL version

# Step 4: Body hash (identical page = same template — may need higher tier)
search -q 'body_hash="abc123..."' -f "host,ip,title"

# Step 5: Server header (HTTP framework — works for ALL tiers)
search -q 'server="nginx/1.18.0"' -f "ip,host,title"         # exact nginx version
search -q 'header="X-Powered-By: PHP/7.4"' -f "ip,host"      # PHP version

# Step 6: Product (Pro+ only — structured component ID)
search -q 'product="Apache-HTTPD"' -f "ip,host,title"
```

---

### Asset De-duplication Strategy

Multi-dimensional queries produce overlapping results. AI MUST de-duplicate before presenting to user:

1. **By IP**: Same IP = same host (even if different domains). Merge into one host record.
2. **By Hostname**: Same hostname with different ports = same host, multiple services.
3. **By Icon Hash**: Same icon_hash across different IPs = same application, different deployments (don't merge — they're separate assets).
4. **By Cert Subject**: Same cert across different IPs = same TLS deployment (note relationship but don't merge).

Use `cache-read` with filters to cross-reference:
```bash
# Get unique IPs from a result set
cache-read --hash <hash> --filter "ip=1.2.3.4" -s 10000
```

---

### Risk Prioritization Framework

When presenting results, tag assets by risk level:

| Risk Level | Indicators | Priority |
|-----------|------------|----------|
| **Critical** | Exposed DBs (3306/5432/6379/27017/9200), RDP (3389), SSH (22) on public IPs | Immediate |
| **High** | Admin panels (title contains 管理/admin/login/dashboard), default credential pages | Urgent |
| **Medium** | Non-standard ports, outdated server versions, self-signed certs on prod domains | Review |
| **Low** | Standard web (80/443), current versions, proper certs | Monitor |
| **Info** | Historical assets (--full), CDN IPs, parked domains | Log only |

**AI Behavior**: Always sort results by risk level (Critical → Info). For Critical/High, explicitly warn user. For exposed databases, remind of data protection obligations.

---

### F-Point Budget Strategy for Playbooks

| Playbook | Free Steps | Paid Steps | Estimated F-Points |
|----------|-----------|------------|-------------------|
| Full Exposure | Steps 1-7 (page=1, size≤100) | Steps 8-10 (may paginate) | 0 if ≤100 assets/org; ~100 F-points for large orgs |
| Vulnerability | Steps 1-4 (stats + page=1) | Steps 5-7 (--full pagination) | 0 for scope; F-points for full export |
| Threat Intel | Steps 1-3 (page=1) | Steps 4-6 (may paginate) | Typically 0 (C2 infra is small) |
| Subdomain | All steps (page=1) | Rarely needs pagination | ~0 |
| Fingerprint | All steps (page=1) | Step 7 (product, Pro+) | ~0 |

**Rule**: Always run `stats` first (free) to estimate scope. If `stats` shows >100 results, warn user that pagination will cost F-points and ask for authorization before proceeding.

---

### Cross-Engine Validation

FOFA's coverage is strongest for Chinese internet space. For comprehensive recon, suggest cross-referencing:

| Engine | Strength | When to Suggest |
|--------|----------|-----------------|
| **Censys** | TLS cert data, academic/research networks | After certificate-based pivoting (Playbook 1 Step 3) |
| **Shodan** | IoT/ICS, banner fingerprints, global coverage | After banner-based ID (Playbook 5 Step 5) |
| **FOFA** | Chinese assets, ICP data, historical archive | Default engine — always use first |

> Note: This skill only covers FOFA. Cross-referencing requires separate tools, but AI MUST suggest it when the target is non-Chinese or when FOFA returns <10 results (possible coverage gap).
