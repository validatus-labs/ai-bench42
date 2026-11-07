#!/usr/bin/env python3
"""Validate/read sealed public research snapshots; no acquisition or network CLI.
Flow: pinned index -> exact catalog -> bounded no-follow files -> inert response.
Imported only by the coordinator-owned offline documentation broker.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import time
from urllib.parse import urlsplit, urljoin

MAX_BODY = 2 * 1024 * 1024
HOSTS = {'docs.python.org', 'www.rfc-editor.org', 'datatracker.ietf.org',
         'developer.mozilla.org', 'support.google.com', 'support.microsoft.com',
         'support.mozilla.org', 'support.apple.com', 'docs.k9mail.app',
         'raw.githubusercontent.com'}
REPOS = {'crisp-oss/email-reply-parser': {'README.md', 'LICENSE', 'lib/regex.ts'},
         'crisp-oss/email-forward-parser': {'README.md', 'LICENSE', 'lib/parser.ts'},
         'github/email_reply_parser': {'README.md', 'LICENSE', 'lib/email_reply_parser.rb'},
         'mailgun/talon': {'README.rst', 'LICENSE', 'talon/quotations.py', 'talon/signature/bruteforce.py'}}


def encoded(v):
    return (json.dumps(v, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def safe_url(url):
    if not isinstance(url, str) or len(url) > 2048 or any(ord(c) < 33 for c in url) or '%' in url or '\\' in url:
        raise ValueError('Invalid public research URL')
    p = urlsplit(url)
    if p.scheme != 'https' or p.netloc not in HOSTS or p.query or p.fragment or p.username or p.password:
        raise ValueError('Exact public research origin required')
    if p.hostname == 'raw.githubusercontent.com':
        parts = p.path.lstrip('/').split('/')
        if len(parts) < 4 or '/'.join(parts[:2]) not in REPOS or not re.fullmatch('[0-9a-f]{40}', parts[2]) or '/'.join(parts[3:]) not in REPOS['/'.join(parts[:2])]:
            raise ValueError('Only pinned named public parser files allowed')
    return url


def config(raw):
    value = json.loads(raw)
    if value.get('mode') != 'PINNED_OFFLINE_BROWSER_SNAPSHOTS' or value.get('schema_version') != 1:
        raise ValueError('Research config schema')
    rows = value['entries']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 64:
        raise ValueError('Research count')
    urls = [safe_url(r['url']) for r in rows]
    if len(set(urls)) != len(urls) or any(not r.get('publisher') or not r.get('provenance') or not r.get('adaptation') for r in rows):
        raise ValueError('Unique sources and provenance required')
    for r in rows:
        if 'license_url' in r and r['license_url'] not in urls:
            raise ValueError('License must be pinned in package')
        if urlsplit(r['url']).hostname=='raw.githubusercontent.com':
            parts=urlsplit(r['url']).path.lstrip('/').split('/')
            if (r.get('repository'),r.get('revision'),r.get('source_path'))!=('/'.join(parts[:2]),parts[2],'/'.join(parts[3:])) or r.get('license_url')!='https://raw.githubusercontent.com/'+ '/'.join(parts[:3])+'/LICENSE':
                raise ValueError('Repository/revision/path/license provenance mismatch')
    return value


def private_read(root, name, limit):
    if '/' in name or name in ('.', '..'):
        raise ValueError('Object name')
    directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    finally:
        os.close(directory)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise ValueError('Bounded regular object required')
        data = bytearray()
        while len(data) <= limit:
            chunk = os.read(fd, min(65536, limit + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
        after = os.fstat(fd)
        if len(data) > limit or (info.st_size, info.st_mtime_ns, info.st_ctime_ns) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            raise ValueError('Object changed/oversized')
        return bytes(data)
    finally:
        os.close(fd)


class Snapshots:
    def __init__(self, root, expected_sha=None):
        self.root = Path(root)
        raw = private_read(self.root, 'index.json', 1024 * 1024)
        if expected_sha and digest(raw) != expected_sha:
            raise ValueError('Snapshot manifest drift')
        self.index_sha256 = digest(raw)
        self.index = json.loads(raw)
        if self.index.get('decision') != 'PINNED_RESEARCH_COMPLETE':
            raise ValueError('Incomplete research package')
        self.rows = self.index['entries']
        cfg = config(encoded(self.index['config']))
        if self.index['config_sha256'] != digest(encoded(cfg)) or set(self.rows) != {r['url'] for r in cfg['entries']}:
            raise ValueError('Snapshot configuration binding')
        for url in self.rows:
            self.fetch(url)
        actual = set(os.listdir(self.root))
        expected = {'index.json'} | {r['sha256'] + '.body' for r in self.rows.values()}
        if actual != expected:
            raise ValueError('Unexpected snapshot object')

    def fetch(self, url):
        safe_url(url)
        if url not in self.rows:
            raise ValueError('URL outside immutable snapshot catalog')
        row = self.rows[url]
        sha = row['sha256']
        if not re.fullmatch('[0-9a-f]{64}', sha) or row['status'] != 200 or not 0 < row['bytes'] <= MAX_BODY:
            raise ValueError('Snapshot metadata invalid')
        data = private_read(self.root, sha + '.body', MAX_BODY)
        if len(data) != row['bytes'] or digest(data) != sha or not row['redirect_chain'] or row['redirect_chain'][0] != url or row['redirect_chain'][-1] != row['final_url'] or any(u not in self.rows for u in row['redirect_chain']):
            raise ValueError('Snapshot content/redirect mismatch')
        return row['status'], {'content-type': row['content_type']}, data

    def response(self, url):
        status, headers, body = self.fetch(url)
        row = self.rows[url]
        return {'status':status,'headers':headers,'body':base64.b64encode(body).decode(),
                'final_url':row['final_url']}, row['redirect_chain']

