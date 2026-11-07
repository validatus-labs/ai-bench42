#!/usr/bin/env node
// Trusted page hook: original HTTPS URL -> private Unix broker -> verified response.
// Runs inside the worker, never exposes a TCP proxy, file reader or CONNECT tunnel.
// [J01] Exact frozen catalog/origins -> [J02] bounded Unix request -> [J03] route fulfillment.
'use strict';
const net = require('node:net');
const fs = require('node:fs');
const catalogPath = '/run/research-catalog.json';
const CATALOG = fs.existsSync(catalogPath) ? new Set(JSON.parse(fs.readFileSync(catalogPath, 'utf8'))) : null;
const ORIGINS = CATALOG ? new Set([...CATALOG].map(url => new URL(url).origin)) :
  new Set(['https://docs.python.org', 'https://www.rfc-editor.org', 'https://datatracker.ietf.org', 'https://developer.mozilla.org']);

function exchange(request) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection('/run/modelbench/docs.sock');
    let data = Buffer.alloc(0);
    socket.setTimeout(25000, () => socket.destroy(new Error('Documentation broker timeout')));
    socket.on('connect', () => socket.write(JSON.stringify(request) + '\n'));
    socket.on('error', reject);
    socket.on('data', chunk => {
      data = Buffer.concat([data, chunk]);
      if (data.length > 6 * 1024 * 1024) return socket.destroy(new Error('Broker response limit'));
      const end = data.indexOf(10);
      if (end !== -1) {
        try { resolve(JSON.parse(data.subarray(0, end).toString())); }
        catch (error) { reject(error); }
        socket.destroy();
      }
    });
    socket.on('end', () => reject(new Error('Incomplete documentation response')));
  });
}

exports.default = async ({page}) => {
  const context = page.context();
  if (context.__modelbenchRoutes) return;
  context.__modelbenchRoutes = true;
  await context.route('**/*', async route => {
    try {
      const request = route.request();
      const url = new URL(request.url());
      if (request.method() !== 'GET' || !ORIGINS.has(url.origin) || (CATALOG && !CATALOG.has(url.href.split('#')[0])) || url.username || url.password)
        return await route.fulfill({status: 403, contentType: 'text/plain', body: 'MODELBENCH_DENIED'});
      const response = await exchange({url: url.href, method: 'GET'});
      // Redirects are followed and validated by the broker. Fulfill the final
      // bytes at the requested browser URL; do not make Chromium open an
      // un-intercepted redirect connection in the disconnected namespace.
      if (response.final_url && !ORIGINS.has(new URL(response.final_url).origin))
        throw new Error('Forbidden redirect result');
      await route.fulfill({status: response.status, headers: response.headers,
                          body: Buffer.from(response.body, 'base64')});
    } catch {
      await route.abort('blockedbyclient');
    }
  });
};

exports.exchange = exchange;
