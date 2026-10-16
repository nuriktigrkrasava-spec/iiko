"""Read-only preflight. Never initializes a DB or prints credential values."""
import argparse
import ipaddress
import os
from pathlib import Path
import socket
import sqlite3
import ssl
import sys
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from outbound_security import trusted_url


def inspect_configuration(*, check_tls=False):
    env = os.environ
    errors, warnings = [], []
    for key in ('TELEGRAM_BOT_TOKEN', 'TELEGRAM_WEBHOOK_SECRET', 'ENCRYPTION_KEY'):
        if not env.get(key, '').strip():
            errors.append(f'{key}: required before a production restart')
    raw = env.get('TRUSTED_PROXY_CIDRS', '').strip()
    if not raw:
        message = 'TRUSTED_PROXY_CIDRS: unset; visitors behind one proxy share rate limits'
        (errors if env.get('RENDER') or env.get('RENDER_SERVICE_ID') else warnings).append(message)
    else:
        try:
            networks = [ipaddress.ip_network(item.strip()) for item in raw.split(',')]
            if any(n.prefixlen == 0 for n in networks):
                raise ValueError()
        except ValueError:
            errors.append('TRUSTED_PROXY_CIDRS: use explicit proxy CIDRs, never all addresses')
    for key in ('REVIEWS_2GIS_KEY', 'CATALOG_2GIS_KEY'):
        if not env.get(key, '').strip():
            warnings.append(f'{key}: not configured; verify 2GIS integration before rollout')
    # Widget template loading is read-only; validation prints no UID or secret.
    from widget_routes import _owner_versions
    try:
        _owner_versions(env.get('WIDGET_OWNER_VERSIONS') or '{}')
    except RuntimeError:
        errors.append('WIDGET_OWNER_VERSIONS: invalid JSON/version map')
    if env.get('ASSISTANT_SNAPSHOT') and not env.get('ASSISTANT_SNAPSHOT_OWNER_ID'):
        warnings.append('ASSISTANT_SNAPSHOT_OWNER_ID: missing; file snapshot will not be served')
    path = Path(env.get('DB_PATH') or 'iiko_boss.db').expanduser().resolve()
    if not path.is_file():
        errors.append('DB_PATH: database is missing; refusing to create an empty database')
        return errors, warnings
    if str(path) == '/data/iiko.db':
        errors.append('DB_PATH: old candidate path; existing service uses /data/iiko_boss.db')
    try:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as conn:
            rows = conn.execute('SELECT DISTINCT iiko_server FROM restaurants WHERE iiko_server IS NOT NULL').fetchall()
    except sqlite3.Error:
        errors.append('DB_PATH: cannot read the existing restaurants table')
        return errors, warnings
    hosts = set()
    for (value,) in rows:
        if not value:
            continue
        url = value.strip()
        if not url.startswith(('https://', 'http://')):
            url = 'https://' + url
        try:
            # Same policy as production. env is normally os.environ.
            trusted_url(url, 'iiko')
            hosts.add(urlsplit(url).hostname)
        except (TypeError, ValueError):
            errors.append('Stored iiko server violates HTTPS/443/host policy; inspect it privately')
    if check_tls:
        context = ssl.create_default_context()
        for host in sorted(hosts):
            try:
                with socket.create_connection((host, 443), timeout=10) as sock:
                    with context.wrap_socket(sock, server_hostname=host):
                        pass
            except (OSError, ssl.SSLError):
                errors.append('Stored iiko server TLS check failed; fix its certificate/chain, do not disable TLS')
    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-tls', action='store_true', help='Check certificates of approved iiko hosts, without credentials')
    args = parser.parse_args()
    errors, warnings = inspect_configuration(check_tls=args.check_tls)
    for message in warnings:
        print('WARNING:', message)
    for message in errors:
        print('ERROR:', message)
    print(f'Preflight: {len(errors)} errors, {len(warnings)} warnings. Database not modified.')
    return bool(errors)


if __name__ == '__main__':
    raise SystemExit(main())
