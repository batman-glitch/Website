import { cp, mkdir, rm } from 'node:fs/promises';
import { basename, extname, relative } from 'node:path';
import { build } from 'esbuild';

const source = 'Website/cr/outputs';
const target = 'public';
await build({
  entryPoints: [`${source}/assets/studio-blob.js`],
  bundle: true,
  platform: 'browser',
  format: 'esm',
  outfile: `${source}/assets/studio-blob.bundle.js`,
});
await rm(target, { recursive: true, force: true });
await mkdir(target, { recursive: true });
await cp(source, target, {
  recursive: true,
  filter(path) {
    const name = basename(path);
    const localPath = relative(source, path);
    if (localPath === 'data' || localPath.startsWith('data/')) return false;
    if (name === 'README.md' || name === 'server.py' || name === 'admin.html') return false;
    if (extname(name) === '.py' || /\.(sqlite3?|db)$/i.test(name)) return false;
    return true;
  },
});
console.log('Bundled the admin uploader and staged public portfolio files for Vercel CDN delivery.');
