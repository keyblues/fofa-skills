# FOFA Query Syntax Reference

> Extracted from SKILL.md. Field reference, logic operators, and time range syntax for constructing FOFA queries.

## FOFA Query Syntax Reference

> This reference is for AI to understand FOFA syntax. When explaining queries to users, use plain language per part — do NOT copy-paste from this table.

### Basic Fields

| Syntax | Example | Description |
|--------|---------|-------------|
| `ip` | `ip="1.1.1.1"` | IP match, supports CIDR (`ip="1.1.1.0/24"`) |
| `port` | `port="443"` | Port number |
| `protocol` | `protocol="https"` | Protocol type |
| `host` | `host=".edu"` | Hostname match; leading `.` matches all hostnames ending with that suffix |
| `domain` | `domain="example.com"` | Domain exact match |
| `title` | `title="admin"` | Page title keyword |
| `server` | `server="Apache"` | Server software |
| `body` | `body="login"` | HTTP response body |
| `header` | `header="nginx"` | HTTP response header |
| `banner` | `banner="SSH-2.0"` | Service banner |
| `cert` | `cert="CN=*.google.com"` | SSL certificate (broad match across all cert fields) |
| `cert.subject` | `cert.subject="CN=*.example.com"` | Certificate subject — more granular than `cert` |
| `cert.issuer` | `cert.issuer="CN=Let's Encrypt"` | Certificate issuer / CA |
| `icon_hash` | `icon_hash="-247388890"` | Favicon hash (**requires higher FOFA tier** — error 820001 if denied) |
| `jarm` | `jarm="29d29d15d29d29d000..."` | TLS JARM fingerprint (useful for C2 detection) |
| `body_hash` | `body_hash="abc123"` | HTTP response body hash (**requires higher FOFA tier**) |
| `cname` | `cname="cdn.example.com"` | CNAME DNS record |

### Asset & Ownership

| Syntax | Example | Description |
|--------|---------|-------------|
| `app` | `app="Apache"` | Component/application |
| `product` | `product="Apache-HTTPD"` | Product ID (Pro+ required) |
| `category` | `category="service"` | Asset category (Pro+ required) |
| `os` | `os="Linux"` | Operating system |
| `asn` | `asn="15169"` | AS number |
| `org` | `org="Google LLC"` | Organization |
| `country` | `country="CN"` | Country (ISO code) |
| `city` | `city="Beijing"` | City |
| `type` | `type="service"` | Asset type |
| `icp` | `icp="京ICP备12345678"` | ICP registration number (China) |
| `mf_hash` | `mf_hash="xxx"` | Multi-function fingerprint hash (**requires higher FOFA tier**) |

### Logic Operators

| Syntax | Example | Description |
|--------|---------|-------------|
| `&&` | `port="443" && country="CN"` | AND |
| `\|\|` | `port="80" \|\| port="443"` | OR |
| `()` | `(app="nginx" \|\| app="apache") && country="US"` | Grouping |

### Time Range

| Syntax | Example | Description |
|--------|---------|-------------|
| `after` | `after="2024-01-01"` | After this date |
| `before` | `before="2024-12-31"` | Before this date |
