# namecom-utils

[中文文档](README.zh.md)

Small tools for Name.com DNS, DDNS, and certificate issuance:

| Tool | Purpose |
| --- | --- |
| `namecom` | Query, add, replace, and delete DNS records |
| `namecom-ddns` | Detect an IP and update DNS, or just print the IP |
| `certbot-namecom-hook` | Add and clean up DNS-01 challenge records |
| `request-cert` | Issue certificates and export the chain and private key |

The three Python scripts are independent and access the Name.com API using a
shared configuration file. No third-party Python packages are required. Your
domain's DNS must be hosted by Name.com.

## Dependencies

- `namecom`, `certbot-namecom-hook`: Python 3.
- `namecom-ddns`: Python 3; HTTP IP lookup requires `curl`, and interface
  address
  lookup requires the Linux `ip` command (iproute2).
- `request-cert`: Bash, Certbot, GNU coreutils, and an executable
  `certbot-namecom-hook` in the same directory.

You can run the scripts directly from the project directory. Each tool supports
`--help`.

## Configuration

The default configuration file is `/etc/namecom.ini`. Use `--config PATH` to
specify a different file.

```sh
cp namecom.ini.example namecom.ini
chmod 600 namecom.ini
# Edit namecom.ini with your actual zones, accounts, and API tokens
```

Configuration format:

```ini
[aaa.com]
username = a-account
token = a-key

[bbb.com.uk]
username = b-account
token = b-key
```

Each section names a hosted DNS zone and can use a different account. Operations
on `x.aaa.com` use `[aaa.com]`. If multiple zones match, the longest domain
suffix
matching complete DNS labels is used.

The examples below use `namecom.ini` in the current directory. You can omit
`--config ./namecom.ini` when using the default configuration file.

## namecom

### Querying records

```sh
./namecom --config ./namecom.ini get x.aaa.com A
./namecom --config ./namecom.ini get aaa.com TXT --json
./namecom --config ./namecom.ini get x.aaa.com
```

`get` matches the exact record name. The type is optional; omitting it returns
all record types at that name. By default, each record occupies one line, with
tab-separated name, type, JSON-quoted value, and TTL, plus priority when
present.
No output is produced if no records match. `--json` outputs an array containing
`name`, `type`, `value`, `ttl`, `id`, and `priority` when available.

```text
x.aaa.com A    "192.0.2.1"    TTL=300
x.aaa.com AAAA "2001:db8::1"  TTL=300
```

List records in one zone or all configured zones:

```sh
./namecom --config ./namecom.ini list aaa.com
./namecom --config ./namecom.ini list
./namecom --config ./namecom.ini list --json
```

The domain passed to `list` must be a configured zone. Omitting it queries all
configured zones in turn. The default output contains tab-separated name, type,
JSON-quoted value, and TTL, plus priority when present. JSON output also
includes
the record `id` and `priority` when available. `list` can display all record
types
returned by the API.

### Adding, replacing, and deleting records

```sh
./namecom --config ./namecom.ini add x.aaa.com A 192.0.2.1
./namecom --config ./namecom.ini set x.aaa.com AAAA 2001:db8::1
./namecom --config ./namecom.ini set aaa.com TXT 'some text' --ttl 600
./namecom --config ./namecom.ini del x.aaa.com A
# Delete all record types at this exact name
./namecom --config ./namecom.ini del x.aaa.com
```

Explicit types can be `A`, `AAAA`, `CNAME`, or `TXT`. Omitting the type for
`get`
or `del` matches all types, including MX and others:

- `add`: Sends an add request even if an identical record already exists. The
  default TTL is 300 seconds.
- `set`: Matches the exact name and type. If multiple records match, deletes
  extras one at a time, then updates the remaining record. If none match, adds
  one. Skips the final update if both value and TTL already match. Without an
  explicit TTL, preserves the existing TTL or uses 300 seconds for a new record.
- `del`: Deletes all records matching the name and type. Omitting the type
  deletes all records at that exact name without affecting other subdomains.
  No matching records is also considered a success.

`add` and `set` support `--ttl SECONDS`, from 300 to 4294967295. Changes are not
atomic, and there is no automatic rollback or retry.

Use `aaa.com` directly for the zone apex. Quote wildcard names to protect them
from shell expansion, for example `'*.aaa.com'`. Query data goes to stdout;
operation logs and errors go to stderr.

## namecom-ddns

By default, fetches IPv4 from ip.sb, updates the A record, and runs in a
foreground loop with a 60-second interval:

```sh
./namecom-ddns --config ./namecom.ini x.aaa.com
```

Common options:

```sh
# Run once
./namecom-ddns --config ./namecom.ini --once x.aaa.com

# Change the loop interval
./namecom-ddns --config ./namecom.ini --interval 120 x.aaa.com

# Fetch IPv6 and update the AAAA record
./namecom-ddns --config ./namecom.ini -6 x.aaa.com

# Read an address from a specific interface
./namecom-ddns --config ./namecom.ini -4 -I eth0 x.aaa.com
./namecom-ddns --config ./namecom.ini -6 -I eth0 x.aaa.com

# Choose an IP lookup service
./namecom-ddns --config ./namecom.ini -R ifconfig.co x.aaa.com
```

Choose either `-4/--ipv4` or `-6/--ipv6`; the default is `-4`. To update both A
and AAAA records, run two separate processes.

Choose either `-I/--interface` or `-R/--reflect`. Supported IP lookup services
are
`ip.sb` (default), `ifconfig.co`, `ipify.org`, and `cip.cc`. Currently, cip.cc
does
not support IPv6; the tool does not switch services automatically. HTTP lookup
uses curl and preserves the user's proxy and other environment settings.

Interface lookup excludes link-local, temporary, tentative, dadfailed,
deprecated, and expired addresses, then selects the first remaining address.
Private IPv4 addresses and IPv6 ULAs are allowed; choosing the appropriate
interface is the user's responsibility.

At the start of the loop, the tool reads existing DNS records and prints their
IPs. It skips updates when the IP matches and updates when it differs. Multiple
matching records are reduced to one using the same logic as `namecom set`.
Updates preserve the existing TTL; new records use 300 seconds.

The known DNS IP is cached rather than read again on every iteration. If a
record is changed externally while the local IP stays the same, restart the
tool to check it again. Query, IP lookup, or update failures inside the loop
print an error and retry after the next interval. With `--once`, failures exit
immediately with a nonzero status. Startup errors, such as configuration errors,
also exit immediately. Logs go to stderr.

### Printing only the IP

`--ip-only` fetches and prints the IP once. It requires neither a domain name
nor a Name.com configuration file, and does not access the Name.com API:

```sh
./namecom-ddns --ip-only
./namecom-ddns --ip-only -6
./namecom-ddns --ip-only -6 -I eth0
./namecom-ddns --ip-only -R ipify.org
```

On success, stdout contains only the IP and a newline. On failure, an error is
written to stderr and the tool exits with a nonzero status.

## request-cert

```sh
./request-cert --config ./namecom.ini aaa.com '*.aaa.com'
./request-cert --config ./namecom.ini aaa.com www.aaa.com -o ./certs
```

Uses Certbot's manual DNS-01 validation, managing DNS through the
`certbot-namecom-hook` in the same directory. On the first run, Certbot may ask
for an email address, acceptance of its terms of service, and other input.

- `-o DIR` or `--output DIR` sets the export directory, defaulting to the
  current
  directory.
- Exports only `fullchain.pem` (mode 644) and `privkey.pem` (mode 600),
  replacing
  existing files with those names.
- Does not generate DH parameters or automatically reload web services.
- Certbot's `--config-dir`, `--work-dir`, and `--logs-dir` are all set to
  `$HOME/.letsencrypt`, allowing the script to run as a regular user.
- The certificate name comes from the first domain, with a leading `*.` and
  trailing dot removed and letters converted to lowercase. Uses
  `--keep-until-expiring` to reuse certificates that are not yet due for
renewal.

Exported files are copies. Renewing with Certbot alone does not update them.
Run `request-cert` again to issue or reuse a certificate and export it again.
The script does not install a scheduled renewal task.

## certbot-namecom-hook

Usually used through `request-cert`, but you can also configure Certbot
directly:

```sh
certbot certonly --manual --preferred-challenges dns \
  --manual-auth-hook "/usr/bin/env /absolute/path/certbot-namecom-hook auth \
    --config /absolute/path/namecom.ini --wait 25" \
  --manual-cleanup-hook "/usr/bin/env /absolute/path/certbot-namecom-hook \
    cleanup --config /absolute/path/namecom.ini" \
  -d aaa.com -d '*.aaa.com'
```

Replace the absolute paths in the example. When running without root privileges,
set writable Certbot configuration, work, and log directories as `request-cert`
does.

The hook reads the domain and validation value from Certbot's environment
variables and supports only DNS-01:

- `auth` adds a TXT record at `_acme-challenge.<domain>` with a TTL of 300
  seconds.
  The default wait is 5 seconds. Adjust it with `--wait SECONDS`, or use 0 to
  disable waiting.
- For multiple challenges in one certificate request, uses
  `CERTBOT_REMAINING_CHALLENGES` to wait only after the last auth call. If the
  variable is unavailable, waits after every auth call.
- The wait is a fixed delay; the hook does not actively check DNS propagation.
- `cleanup` deletes all TXT records at the current challenge name, including
  leftovers from earlier runs. No records is considered a success. It does not
  clean up other challenge names in the zone.

This cleanup behavior can affect concurrent requests using the same challenge
name. It is intended for small-tool use cases that do not require coordination
between concurrent requests. The hook is silent on success. On failure, it
writes to stderr and exits with a nonzero status. It does not pass state to
cleanup through stdout.
