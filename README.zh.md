# namecom-utils

几个用于 Name.com DNS、DDNS 和证书申请的小工具：

| 工具 | 用途 |
| --- | --- |
| `namecom` | 查询、添加、替换和删除 DNS 记录 |
| `namecom-ddns` | 获取 IP 并更新 DNS，也可以只输出 IP |
| `certbot-namecom-hook` | 添加和清理 DNS-01 验证记录 |
| `request-cert` | 申请证书，导出证书链和私钥 |

三个 Python 脚本各自独立，通过共用配置访问 Name.com API，不需要安装第三方 Python
包。域名的 DNS 必须由 Name.com 托管。

## 依赖

- `namecom`、`certbot-namecom-hook`：Python 3。
- `namecom-ddns`：Python 3；HTTP 反射需要 `curl`，接口取址需要 Linux 的 `ip` 命
  令（iproute2）。
- `request-cert`：Bash、Certbot、GNU coreutils，以及放在同一目录下且可执行的
  `certbot-namecom-hook`。

可以直接在项目目录中运行这些脚本。每个工具都支持 `--help`。

## 配置

默认读取 `/etc/namecom.ini`，也可以使用 `--config PATH` 指定配置文件。

```sh
cp namecom.ini.example namecom.ini
chmod 600 namecom.ini
# 编辑 namecom.ini，填入实际的 zone、账户和 API token
```

配置格式：

```ini
[aaa.com]
username = a-account
token = a-key

[bbb.com.uk]
username = b-account
token = b-key
```

每个节名是一个托管的 DNS zone，可以分别使用不同账户。操作 `x.aaa.com` 时使用
`[aaa.com]`；存在多个匹配 zone 时，使用最长的完整域名后缀匹配。

以下示例使用当前目录中的 `namecom.ini`。如果使用默认配置，可以省略
`--config ./namecom.ini`。

## namecom

### 查询

```sh
./namecom --config ./namecom.ini get x.aaa.com A
./namecom --config ./namecom.ini get aaa.com TXT --json
./namecom --config ./namecom.ini get x.aaa.com
```

`get` 精确匹配记录名称，类型可省略，省略时返回该名称下的所有类型记录。默认一行一
条，以制表符分隔名称、类型、JSON 引号包裹的 value 和 TTL，有 priority 时也会输出
；没有匹配记录时不输出内容。`--json` 输出数组，每条包含 `name`、`type`、`value`
、`ttl`、`id` 和可用的 `priority`。

```text
x.aaa.com A    "192.0.2.1"    TTL=300
x.aaa.com AAAA "2001:db8::1"  TTL=300
```

列出一个 zone 或配置中所有 zone 的记录：

```sh
./namecom --config ./namecom.ini list aaa.com
./namecom --config ./namecom.ini list
./namecom --config ./namecom.ini list --json
```

`list` 的域名必须是配置中的 zone。省略域名时，依次查询所有配置的 zone。默认以制
表符分隔名称、类型、JSON 引号包裹的 value 和 TTL，有 priority 时也会输出。JSON
输出还包含记录 `id` 和可用的 `priority`。`list` 可以显示 API 返回的所有记录类型
。

### 添加、替换和删除

```sh
./namecom --config ./namecom.ini add x.aaa.com A 192.0.2.1
./namecom --config ./namecom.ini set x.aaa.com AAAA 2001:db8::1
./namecom --config ./namecom.ini set aaa.com TXT 'some text' --ttl 600
./namecom --config ./namecom.ini del x.aaa.com A
# 删除该完整域名下的所有类型记录
./namecom --config ./namecom.ini del x.aaa.com
```

显式指定类型时，支持 `A`、`AAAA`、`CNAME`、`TXT`；`get` 和 `del` 省略类型时匹配
所有类型（包括 MX 等）：

- `add`：直接添加，即使已有相同记录也会发起添加请求。默认 TTL 为 300 秒。
- `set`：精确匹配名称和类型。多于一条时逐条删除多余记录，剩一条时更新，没有时添
  加。最后一条的 value 和 TTL 都匹配时跳过更新。未指定 TTL 时保留已有记录的 TTL
  ，新记录使用 300 秒。
- `del`：删除所有名称和类型都匹配的记录；省略类型时删除该完整名称下的所有记录，
  不影响其他子域名。没有匹配记录也视为成功。

`add` 和 `set` 支持 `--ttl SECONDS`，范围为 300–4294967295。修改操作不保证原子性
，也不自动回滚或重试。

根域名直接写 `aaa.com`；通配符名称需要由 shell 引号保护，例如 `'*.aaa.com'`。查
询数据输出到 stdout，操作日志和错误输出到 stderr。

## namecom-ddns

默认使用 ip.sb 获取 IPv4，更新 A 记录，在前台循环运行，间隔 60 秒：

```sh
./namecom-ddns --config ./namecom.ini x.aaa.com
```

常用选项：

```sh
# 只执行一次
./namecom-ddns --config ./namecom.ini --once x.aaa.com

# 修改循环间隔
./namecom-ddns --config ./namecom.ini --interval 120 x.aaa.com

# 获取 IPv6，更新 AAAA 记录
./namecom-ddns --config ./namecom.ini -6 x.aaa.com

# 从指定接口取址
./namecom-ddns --config ./namecom.ini -4 -I eth0 x.aaa.com
./namecom-ddns --config ./namecom.ini -6 -I eth0 x.aaa.com

# 指定反射服务
./namecom-ddns --config ./namecom.ini -R ifconfig.co x.aaa.com
```

`-4/--ipv4` 和 `-6/--ipv6` 二选一，默认 `-4`。如果需要同时更新 A 和 AAAA，分别运
行两个进程。

`-I/--interface` 和 `-R/--reflect` 二选一。反射服务支持 `ip.sb`（默认）、
`ifconfig.co`、`ipify.org`、`cip.cc`。目前 cip.cc 不支持 IPv6；工具不会自动切换
服务。反射使用 curl，并保留用户的代理等环境设置。

接口取址会排除 link-local、temporary、tentative、dadfailed、deprecated 和已失效
的地址，选择剩余地址中的第一条。不会排除 IPv4 私网地址或 IPv6 ULA，用户负责选择
合适的接口。

循环开始时读取已有 DNS 记录并打印其 IP。IP 匹配时跳过，不匹配时更新，多条匹配记
录会按 `namecom set` 的逻辑收敛为一条。更新保留已有 TTL，新建使用 300 秒。

运行中会缓存已知 DNS IP，不会每轮重新读取 DNS；如果外部修改了记录而本机 IP 没变
，需要重启工具才能重新检查。循环中的查询、取址或更新失败会打印错误，并在下一个间
隔重试；`--once` 失败直接非零退出。配置等启动错误直接退出。日志写入 stderr。

### 只获取 IP

`--ip-only` 只取址一次并输出 IP，不需要域名或 Name.com 配置，不访问 Name.com API
：

```sh
./namecom-ddns --ip-only
./namecom-ddns --ip-only -6
./namecom-ddns --ip-only -6 -I eth0
./namecom-ddns --ip-only -R ipify.org
```

成功时 stdout 仅包含 IP 和换行，失败时错误写入 stderr，并非零退出。

## request-cert

```sh
./request-cert --config ./namecom.ini aaa.com '*.aaa.com'
./request-cert --config ./namecom.ini aaa.com www.aaa.com -o ./certs
```

使用 Certbot 的 manual DNS-01 验证，通过同目录下的 `certbot-namecom-hook` 操作
DNS。首次运行时，Certbot 可能要求输入邮箱、接受服务条款等。

- `-o DIR` 或 `--output DIR` 指定导出目录，默认当前目录。
- 只导出 `fullchain.pem`（权限 644）和 `privkey.pem`（权限 600），已有同名文件会
  被替换。
- 不生成 DH 参数文件，也不自动重新加载 Web 服务。
- Certbot 的 `--config-dir`、`--work-dir`、`--logs-dir` 都设置为
  `$HOME/.letsencrypt`，可以以普通用户运行。
- 证书名称取第一个域名，去掉开头的 `*.`、末尾的点并转为小写。使用
  `--keep-until-expiring`，尚未到续订时间时复用已有证书。

导出的文件是副本。单独运行 Certbot 续订不会同步更新这些副本；再次运行
`request-cert` 可以申请或复用证书，并重新导出。脚本本身不安装定时续订任务。

## certbot-namecom-hook

通常通过 `request-cert` 使用，也可以自行配置 Certbot：

```sh
certbot certonly --manual --preferred-challenges dns \
  --manual-auth-hook "/absolute/path/certbot-namecom-hook auth \
    --config /absolute/path/namecom.ini --wait 25" \
  --manual-cleanup-hook "/absolute/path/certbot-namecom-hook \
    cleanup --config /absolute/path/namecom.ini" \
  -d aaa.com -d '*.aaa.com'
```

请替换示例中的绝对路径；非 root 运行时还应像 `request-cert` 一样指定可写的
Certbot 配置、工作和日志目录。

Hook 从 Certbot 环境变量中获取域名和验证值，只支持 DNS-01：

- `auth` 添加 `_acme-challenge.<域名>` 的 TXT 记录，TTL 为 300 秒。默认等待 5 秒
  ，可以用 `--wait SECONDS` 调整，设为 0 则不等待。
- 一次申请有多个 challenge 时，根据 `CERTBOT_REMAINING_CHALLENGES` 仅在最后一次
  auth 等待；变量不可用时，每次 auth 都等待。
- 等待是固定延迟，不主动检测 DNS 是否已传播。
- `cleanup` 删除当前 challenge 名称下的所有 TXT 记录，包括历史残留；没有记录时成
  功。不会清理整个 zone 的其他 challenge 名称。

这种清理方式可能影响同时使用相同 challenge 名称的其他申请，适用于不需要协调并发
申请的小工具场景。成功时 hook 保持静默，失败时写入 stderr 并非零退出，不通过
stdout 向 cleanup 传递状态。

### 配合 nginx 安装证书

要使用 DNS hook 验证域名，并让 Certbot 自动安装证书、修改 nginx 配置，
可以分别指定验证插件和安装插件：

- `-i nginx`：使用 nginx 插件安装证书，需要已安装 Certbot 的 nginx 插件。
- `-a manual`：使用 manual 插件，通过 hook 完成 DNS-01 验证。

这种情况下，强烈建议将 `namecom.ini` 放在 `/etc/namecom.ini`，
以免证书续订时找不到配置文件，或因访问权限（ACL）问题无法读取。

```sh
sudo certbot -i nginx -a manual --preferred-challenges dns \
  --manual-auth-hook "/absolute/path/certbot-namecom-hook auth" \
  --manual-cleanup-hook "/absolute/path/certbot-namecom-hook cleanup"
```
