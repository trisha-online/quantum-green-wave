// Dependency-free static preview server for the site:  node web/site/server.js  ->  http://localhost:3000
// Fixed from the Manus version: it served files outside its folder (prefix check), crashed on directories,
// broke on URL-encoded names, and served .js / .css as octet-stream.
const http = require('http');
const fs = require('fs');
const path = require('path');

const root = path.resolve(__dirname);          // the folder this file is in, not wherever node was started
const port = Number(process.env.PORT) || 3000;
const types = {
  '.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8',
  '.json': 'application/json; charset=utf-8', '.svg': 'image/svg+xml', '.png': 'image/png', '.ico': 'image/x-icon'
};

http.createServer((req, res) => {
  let pathname;
  try {
    pathname = decodeURIComponent(new URL(req.url, 'http://localhost').pathname);
  } catch (e) {
    res.writeHead(400); res.end('Bad request'); return;
  }
  let file = path.resolve(root, '.' + (pathname.endsWith('/') ? pathname + 'index.html' : pathname));
  if (file !== root && !file.startsWith(root + path.sep)) {      // block ../ and look-alike sibling folders
    res.writeHead(403); res.end('Forbidden'); return;
  }
  fs.stat(file, (err, st) => {
    if (!err && st.isDirectory()) { file = path.join(file, 'index.html'); }
    fs.readFile(file, (err2, body) => {
      if (err2) { res.writeHead(404, { 'Content-Type': 'text/plain' }); res.end('Not found'); return; }
      res.writeHead(200, { 'Content-Type': types[path.extname(file).toLowerCase()] || 'application/octet-stream' });
      res.end(body);
    });
  });
}).listen(port, () => console.log(`Quantum Green Wave site: http://localhost:${port}/`));
