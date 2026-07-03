import type { Plugin, ViteDevServer } from 'vite';
import fs from 'node:fs';
import path from 'node:path';
import { spawnPython } from './python';
import { setupFileWatcher } from './file-watcher';
import { setupWebSocket } from './ws';
import { getSettings, updateSettings } from './settings';
import { streamChat } from './ai-proxy';

/**
 * Origins allowed to make requests to the API. The webviewer is served from
 * localhost:8090 (also reachable as 127.0.0.1:8090), so legitimate same-origin
 * requests — from a browser or from the FileMaker Web Viewer, which loads the
 * SPA from this URL — carry one of these Origins. Any other Origin is a
 * cross-origin caller and is rejected. Keep this in sync with the `port` in
 * vite.config.ts.
 */
const ALLOWED_ORIGINS = new Set([
  'http://localhost:8090',
  'http://127.0.0.1:8090',
]);

/** Resolve the agent directory (sibling to webviewer/) */
function agentDir(): string {
  // process.cwd() = webviewer/, agent/ is sibling
  return path.resolve(process.cwd(), '..', 'agent');
}

/**
 * Resolve the main repo's agent directory.
 * In a git worktree, gitignored dirs (context/, xml_parsed/) only exist
 * at the main repo root, not in the worktree. This follows the .git
 * worktree link to find the original repo.
 */
function mainAgentDir(): string {
  const repoRoot = path.resolve(process.cwd(), '..');
  const dotGit = path.join(repoRoot, '.git');
  try {
    const stat = fs.statSync(dotGit);
    if (stat.isFile()) {
      // Worktree: .git is a file containing "gitdir: <path>"
      const content = fs.readFileSync(dotGit, 'utf-8').trim();
      const match = content.match(/^gitdir:\s*(.+)$/);
      if (match) {
        // gitdir points to e.g. /repo/.git/worktrees/<name>
        // Main repo .git is two levels up from that
        const mainGitDir = path.resolve(match[1], '..', '..');
        const mainRoot = path.dirname(mainGitDir);
        const mainAgent = path.join(mainRoot, 'agent');
        if (fs.existsSync(mainAgent)) return mainAgent;
      }
    }
  } catch { /* not a worktree or .git missing */ }
  // Fallback to local agent dir
  return path.resolve(repoRoot, 'agent');
}

/**
 * Resolve the context directory for a given solution.
 * Accepts an optional solution name; when omitted, auto-detects if only one
 * solution subfolder exists under agent/context/.
 */
function resolveContextDir(agentDir: string, solution?: string): string {
  const contextBase = path.join(agentDir, 'context');
  if (solution) {
    return path.join(contextBase, solution);
  }
  // Auto-detect: if only one solution subfolder, use it
  let entries: fs.Dirent[] = [];
  try {
    entries = fs.readdirSync(contextBase, { withFileTypes: true })
      .filter(e => e.isDirectory());
  } catch { /* context dir doesn't exist yet */ }
  if (entries.length === 1) return path.join(contextBase, entries[0].name);
  if (entries.length === 0) throw new Error('agent/context/ is empty — run fmcontext.sh first');
  throw new Error('Multiple solutions in agent/context/ — specify ?solution= query param');
}

export function apiMiddleware(): Plugin {
  return {
    name: 'fm-api-middleware',
    configureServer(server: ViteDevServer) {
      const agent = agentDir();

      // WebSocket for file watcher
      setupWebSocket(server);
      setupFileWatcher(server, path.join(agent, 'CONTEXT.json'));

      server.middlewares.use(async (req, res, next) => {
        const url = new URL(req.url ?? '/', `http://${req.headers.host}`);
        const pathname = url.pathname;

        // --- Same-origin (CSRF) guard ---
        // The dev server binds to 127.0.0.1 only, but any web page open in a
        // browser on THIS host can still issue cross-origin requests to
        // localhost:8090. POST /api/chat spawns the `claude` CLI, so an
        // unguarded cross-origin request is a same-host drive-by RCE vector.
        // A browser always attaches an Origin header to cross-origin requests
        // (and to same-origin non-GET requests) — including the literal "null"
        // origin used by sandboxed iframes and data: URLs — so rejecting any
        // request whose Origin is present but not in the localhost allowlist
        // closes the browser attack surface (it also defeats DNS rebinding,
        // since the rebound page keeps its original Origin). An absent Origin
        // is allowed: a browser cannot suppress it on a POST, so a missing
        // Origin only comes from a same-host non-browser client that already
        // has local code execution. This is compatible with the SPA's mixed
        // Content-Types (application/xml on validate/clipboard/sandbox), so it
        // does not depend on the request body type.
        const origin = req.headers.origin;
        if (origin !== undefined && !ALLOWED_ORIGINS.has(origin)) {
          res.statusCode = 403;
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ error: 'Cross-origin request rejected' }));
          return;
        }

        // --- GET /api/version ---
        if (req.method === 'GET' && pathname === '/api/version') {
          const versionFile = path.resolve(process.cwd(), '..', 'version.txt');
          let local = 'unknown';
          try { local = fs.readFileSync(versionFile, 'utf-8').trim(); } catch { /* missing */ }

          // Fetch remote version from GitHub (non-blocking, best-effort)
          let remote: string | null = null;
          try {
            const controller = new AbortController();
            const timeout = setTimeout(() => controller.abort(), 5000);
            const resp = await fetch(
              'https://raw.githubusercontent.com/petrowsky/agentic-fm/main/version.txt',
              { signal: controller.signal },
            );
            clearTimeout(timeout);
            if (resp.ok) remote = (await resp.text()).trim();
          } catch { /* no network / timeout */ }

          const updateAvailable = remote !== null && remote !== local && compareVersions(remote, local) > 0;
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ local, remote, updateAvailable }));
          return;
        }

        // --- GET /api/context ---
        if (req.method === 'GET' && pathname === '/api/context') {
          const contextPath = path.join(agent, 'CONTEXT.json');
          try {
            const data = fs.readFileSync(contextPath, 'utf-8');
            res.setHeader('Content-Type', 'application/json');
            res.end(data);
          } catch {
            res.statusCode = 404;
            res.end(JSON.stringify({ error: 'CONTEXT.json not found' }));
          }
          return;
        }

        // --- GET /api/settings ---
        if (req.method === 'GET' && pathname === '/api/settings') {
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify(getSettings()));
          return;
        }

        // --- POST /api/settings ---
        if (req.method === 'POST' && pathname === '/api/settings') {
          const body = JSON.parse(await readBody(req));
          const updated = updateSettings(body);
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify(updated));
          return;
        }

        // --- POST /api/chat ---
        if (req.method === 'POST' && pathname === '/api/chat') {
          const raw = await readBody(req);
          const body = JSON.parse(raw);
          const roles = (body.messages ?? []).map((m: { role: string }) => m.role);
          console.log(`[ai-chat] POST /api/chat — ${roles.length} messages [${roles.join(', ')}]`);
          await streamChat(body, res);
          return;
        }

        // --- GET /api/custom-instructions ---
        if (req.method === 'GET' && pathname === '/api/custom-instructions') {
          const filePath = path.join(agent, 'config', '.custom-instructions.md');
          let content = '';
          try { content = fs.readFileSync(filePath, 'utf-8'); } catch { /* not found */ }
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ content }));
          return;
        }

        // --- POST /api/custom-instructions ---
        if (req.method === 'POST' && pathname === '/api/custom-instructions') {
          const body = JSON.parse(await readBody(req));
          const filePath = path.join(agent, 'config', '.custom-instructions.md');
          const content = (body.content ?? '').toString();
          if (content.trim()) {
            fs.writeFileSync(filePath, content, 'utf-8');
          } else {
            try { fs.unlinkSync(filePath); } catch { /* already absent */ }
          }
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ ok: true }));
          return;
        }

        // --- GET /api/system-prompt ---
        // Returns the webviewer system prompt base instructions.
        // Override: agent/config/webviewer-system-prompt.md
        // Fallback: agent/config/webviewer-system-prompt.example.md
        if (req.method === 'GET' && pathname === '/api/system-prompt') {
          const overridePath = path.join(agent, 'config', 'webviewer-system-prompt.md');
          const examplePath = path.join(agent, 'config', 'webviewer-system-prompt.example.md');
          let content = '';
          try { content = fs.readFileSync(overridePath, 'utf-8'); } catch {
            try { content = fs.readFileSync(examplePath, 'utf-8'); } catch { /* neither found */ }
          }
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ content }));
          return;
        }

        // --- GET /api/docs ---
        if (req.method === 'GET' && pathname === '/api/docs') {
          const conventionsPath = path.join(agent, 'docs', 'CODING_CONVENTIONS.md');
          const knowledgeDir = path.join(agent, 'docs', 'knowledge');
          let conventions = '';
          let knowledge = '';
          try {
            conventions = fs.readFileSync(conventionsPath, 'utf-8');
          } catch { /* not found */ }
          try {
            const files = fs.readdirSync(knowledgeDir)
              .filter(f => f.endsWith('.md') && f !== 'MANIFEST.md')
              .sort();
            knowledge = files
              .map(f => {
                const content = fs.readFileSync(path.join(knowledgeDir, f), 'utf-8');
                return `## ${f.replace('.md', '')}\n\n${content}`;
              })
              .join('\n\n---\n\n');
          } catch { /* not found */ }
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ conventions, knowledge }));
          return;
        }

        // --- GET /api/index/:name ---
        const indexMatch = pathname.match(/^\/api\/index\/(.+)$/);
        if (req.method === 'GET' && indexMatch) {
          const name = decodeURIComponent(indexMatch[1]);
          const solution = url.searchParams.get('solution') ?? undefined;
          try {
            const main = mainAgentDir();
            const contextDir = resolveContextDir(main, solution);
            const indexPath = path.join(contextDir, `${name}.index`);
            const data = fs.readFileSync(indexPath, 'utf-8');
            const rows = parseIndex(data);
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify(rows));
          } catch {
            res.statusCode = 404;
            res.end(JSON.stringify({ error: `Index ${name} not found` }));
          }
          return;
        }

        // --- GET /api/step-catalog ---
        if (req.method === 'GET' && pathname === '/api/step-catalog') {
          const catalogPath = path.join(agent, 'catalogs', 'step-catalog-en.json');
          try {
            const data = fs.readFileSync(catalogPath, 'utf-8');
            res.setHeader('Content-Type', 'application/json');
            res.end(data);
          } catch {
            res.statusCode = 404;
            res.end(JSON.stringify({ error: 'step-catalog-en.json not found' }));
          }
          return;
        }

        // --- GET /api/lint-config ---
        if (req.method === 'GET' && pathname === '/api/lint-config') {
          // Merge built-in defaults with project-level overrides (same priority as Python)
          const builtinPath = path.join(agent, 'fmlint', 'fmlint.config.json');
          const projectPath = path.join(agent, 'config', 'fmlint.config.json');

          let merged: Record<string, any> = {};
          for (const cfgPath of [builtinPath, projectPath]) {
            try {
              const data = JSON.parse(fs.readFileSync(cfgPath, 'utf-8'));
              const rules = data.rules ?? {};
              for (const [id, val] of Object.entries(rules)) {
                merged[id] = { ...(merged[id] ?? {}), ...(val as Record<string, any>) };
              }
            } catch {
              // File not found or invalid — skip
            }
          }

          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ rules: merged }));
          return;
        }

        // --- GET /api/steps ---
        if (req.method === 'GET' && pathname === '/api/steps') {
          const stepsDir = path.join(agent, 'snippet_examples', 'steps');
          try {
            const steps = enumerateSteps(stepsDir);
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify(steps));
          } catch (err) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: String(err) }));
          }
          return;
        }

        // --- GET /api/snippet/:category/:step ---
        const snippetMatch = pathname.match(/^\/api\/snippet\/(.+?)\/(.+)$/);
        if (req.method === 'GET' && snippetMatch) {
          const category = decodeURIComponent(snippetMatch[1]);
          const step = decodeURIComponent(snippetMatch[2]);
          const snippetPath = path.join(agent, 'snippet_examples', 'steps', category, `${step}.xml`);
          try {
            const data = fs.readFileSync(snippetPath, 'utf-8');
            res.setHeader('Content-Type', 'application/xml');
            res.end(data);
          } catch {
            res.statusCode = 404;
            res.end(`Snippet not found: ${category}/${step}`);
          }
          return;
        }

        // --- POST /api/validate ---
        if (req.method === 'POST' && pathname === '/api/validate') {
          const body = await readBody(req);
          try {
            const result = await validateSnippet(agent, body);
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify(result));
          } catch (err) {
            res.statusCode = 500;
            res.end(JSON.stringify({ valid: false, errors: [String(err)], warnings: [] }));
          }
          return;
        }

        // --- POST /api/clipboard/write ---
        if (req.method === 'POST' && pathname === '/api/clipboard/write') {
          const body = await readBody(req);
          try {
            await clipboardWrite(agent, body);
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ ok: true }));
          } catch (err) {
            res.statusCode = 500;
            res.end(JSON.stringify({ ok: false, error: String(err) }));
          }
          return;
        }

        // --- POST /api/clipboard/read ---
        if (req.method === 'POST' && pathname === '/api/clipboard/read') {
          try {
            const xml = await clipboardRead(agent);
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ xml }));
          } catch (err) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: String(err) }));
          }
          return;
        }

        // --- POST /api/convert/hr-to-xml ---
        // Note: Conversion is done client-side in the browser.
        // This endpoint exists for headless/API usage.
        if (req.method === 'POST' && pathname === '/api/convert/hr-to-xml') {
          const body = await readBody(req);
          // Return the body as-is — actual conversion happens client-side
          // Server-side conversion would require bundling the converter
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ info: 'Use client-side converter', input: body }));
          return;
        }

        // --- POST /api/convert/xml-to-hr ---
        if (req.method === 'POST' && pathname === '/api/convert/xml-to-hr') {
          const body = await readBody(req);
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ info: 'Use client-side converter', input: body }));
          return;
        }

        // --- GET /api/scripts/search?q=<query> ---
        if (req.method === 'GET' && pathname === '/api/scripts/search') {
          const query = (url.searchParams.get('q') ?? '').trim();
          if (!query) {
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify([]));
            return;
          }
          try {
            const results = searchScripts(agent, query);
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify(results));
          } catch (err) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: String(err) }));
          }
          return;
        }

        // --- GET /api/scripts/load?id=<id>&name=<name> ---
        if (req.method === 'GET' && pathname === '/api/scripts/load') {
          const id = url.searchParams.get('id') ?? '';
          const name = url.searchParams.get('name') ?? '';
          if (!id) {
            res.statusCode = 400;
            res.end(JSON.stringify({ error: 'id parameter required' }));
            return;
          }
          try {
            const result = await loadScript(agent, id, name);
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify(result));
          } catch (err) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: String(err) }));
          }
          return;
        }

        // --- GET/POST /api/layout-prefs ---
        if (pathname === '/api/layout-prefs') {
          const prefsPath = path.join(agent, 'config', '.layout-prefs.json');

          if (req.method === 'GET') {
            try {
              const data = fs.readFileSync(prefsPath, 'utf-8');
              res.setHeader('Content-Type', 'application/json');
              res.end(data);
            } catch {
              res.statusCode = 404;
              res.end(JSON.stringify({ error: 'No layout prefs found' }));
            }
            return;
          }

          if (req.method === 'POST') {
            const body = await readBody(req);
            fs.mkdirSync(path.dirname(prefsPath), { recursive: true });
            fs.writeFileSync(prefsPath, body, 'utf-8');
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ ok: true }));
            return;
          }
        }

        // --- GET/POST/DELETE /api/autosave ---
        if (pathname === '/api/autosave') {
          const autosavePath = path.join(agent, 'config', '.autosave.json');

          if (req.method === 'GET') {
            try {
              const data = fs.readFileSync(autosavePath, 'utf-8');
              res.setHeader('Content-Type', 'application/json');
              res.end(data);
            } catch {
              res.statusCode = 404;
              res.end(JSON.stringify({ error: 'No autosave found' }));
            }
            return;
          }

          if (req.method === 'POST') {
            const body = await readBody(req);
            fs.mkdirSync(path.dirname(autosavePath), { recursive: true });
            fs.writeFileSync(autosavePath, body, 'utf-8');
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ ok: true }));
            return;
          }

          if (req.method === 'DELETE') {
            try { fs.unlinkSync(autosavePath); } catch { /* ignore */ }
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ ok: true }));
            return;
          }
        }

        // --- GET /api/library ---
        if (req.method === 'GET' && pathname === '/api/library') {
          const libraryDir = path.join(agent, 'library');
          try {
            const items = enumerateLibrary(libraryDir);
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ items }));
          } catch (err) {
            res.statusCode = 500;
            res.end(JSON.stringify({ error: String(err) }));
          }
          return;
        }

        // --- GET /api/library/item?path=Category/File.xml ---
        if (req.method === 'GET' && pathname === '/api/library/item') {
          const itemPath = url.searchParams.get('path') ?? '';
          if (!itemPath) {
            res.statusCode = 400;
            res.end('Missing path parameter');
            return;
          }
          // Prevent path traversal
          const normalized = path.normalize(itemPath);
          if (normalized.startsWith('..') || path.isAbsolute(normalized)) {
            res.statusCode = 400;
            res.end('Invalid path');
            return;
          }
          const fullPath = path.join(agent, 'library', normalized);
          try {
            const data = fs.readFileSync(fullPath, 'utf-8');
            res.setHeader('Content-Type', 'text/plain');
            res.end(data);
          } catch {
            res.statusCode = 404;
            res.end('Library item not found');
          }
          return;
        }

        // --- POST /api/library/save ---
        if (req.method === 'POST' && pathname === '/api/library/save') {
          const raw = await readBody(req);
          let body: { path?: string; content?: string };
          try {
            body = JSON.parse(raw);
          } catch {
            res.statusCode = 400;
            res.end(JSON.stringify({ error: 'Invalid JSON' }));
            return;
          }
          const { path: itemPath, content } = body;
          if (!itemPath || content === undefined) {
            res.statusCode = 400;
            res.end(JSON.stringify({ error: 'path and content are required' }));
            return;
          }
          const normalized = path.normalize(itemPath);
          if (normalized.startsWith('..') || path.isAbsolute(normalized)) {
            res.statusCode = 400;
            res.end(JSON.stringify({ error: 'Invalid path' }));
            return;
          }
          const fullPath = path.join(agent, 'library', normalized);
          fs.mkdirSync(path.dirname(fullPath), { recursive: true });
          fs.writeFileSync(fullPath, content, 'utf-8');
          res.setHeader('Content-Type', 'application/json');
          res.end(JSON.stringify({ success: true }));
          return;
        }

        // --- GET/DELETE /api/agent-output ---
        if (pathname === '/api/agent-output') {
          const outputPath = path.join(agent, 'config', '.agent-output.json');

          if (req.method === 'GET') {
            try {
              const data = fs.readFileSync(outputPath, 'utf-8');
              res.setHeader('Content-Type', 'application/json');
              res.end(data);
            } catch {
              res.setHeader('Content-Type', 'application/json');
              res.end(JSON.stringify({ available: false }));
            }
            return;
          }

          if (req.method === 'DELETE') {
            try { fs.unlinkSync(outputPath); } catch { /* already gone */ }
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ ok: true }));
            return;
          }
        }

        // --- GET /api/sandbox ---
        if (req.method === 'GET' && pathname === '/api/sandbox') {
          const sandboxDir = path.join(agent, 'sandbox');
          try {
            const files = fs.readdirSync(sandboxDir).filter(f => f.endsWith('.xml'));
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify(files));
          } catch {
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify([]));
          }
          return;
        }

        // --- GET/POST /api/sandbox/:filename ---
        const sandboxMatch = pathname.match(/^\/api\/sandbox\/(.+)$/);
        if (sandboxMatch) {
          const filename = decodeURIComponent(sandboxMatch[1]);
          // Prevent path traversal
          if (filename.includes('..') || filename.includes('/')) {
            res.statusCode = 400;
            res.end(JSON.stringify({ error: 'Invalid filename' }));
            return;
          }
          const filePath = path.join(agent, 'sandbox', filename);

          if (req.method === 'GET') {
            try {
              const data = fs.readFileSync(filePath, 'utf-8');
              res.setHeader('Content-Type', 'application/xml');
              res.end(data);
            } catch {
              res.statusCode = 404;
              res.end('File not found');
            }
            return;
          }

          if (req.method === 'POST') {
            const body = await readBody(req);
            fs.mkdirSync(path.dirname(filePath), { recursive: true });
            fs.writeFileSync(filePath, body, 'utf-8');
            res.setHeader('Content-Type', 'application/json');
            res.end(JSON.stringify({ ok: true }));
            return;
          }
        }

        next();
      });
    },
  };
}

/** Parse pipe-delimited index file into arrays, skipping comment/empty lines */
function parseIndex(data: string): string[][] {
  return data
    .split('\n')
    .filter(line => line.trim() && !line.startsWith('#'))
    .map(line => line.split('|').map(col => col.trim()));
}

/** Enumerate all step XML files from snippet_examples/steps/ */
function enumerateSteps(stepsDir: string): { name: string; category: string; file: string }[] {
  const steps: { name: string; category: string; file: string }[] = [];
  if (!fs.existsSync(stepsDir)) return steps;

  for (const category of fs.readdirSync(stepsDir)) {
    const catPath = path.join(stepsDir, category);
    if (!fs.statSync(catPath).isDirectory()) continue;

    for (const file of fs.readdirSync(catPath)) {
      if (!file.endsWith('.xml')) continue;
      steps.push({
        name: file.replace('.xml', ''),
        category,
        file: `${category}/${file}`,
      });
    }
  }

  return steps.sort((a, b) => a.name.localeCompare(b.name));
}

/** Enumerate all .xml and .md files from the library directory */
function enumerateLibrary(libraryDir: string): { path: string; name: string; category: string }[] {
  const items: { path: string; name: string; category: string }[] = [];
  if (!fs.existsSync(libraryDir)) return items;

  for (const category of fs.readdirSync(libraryDir)) {
    const catPath = path.join(libraryDir, category);
    if (!fs.statSync(catPath).isDirectory()) continue;

    for (const file of fs.readdirSync(catPath)) {
      if (!file.endsWith('.xml') && !file.endsWith('.md')) continue;
      const ext = path.extname(file);
      items.push({
        path: `${category}/${file}`,
        name: path.basename(file, ext),
        category,
      });
    }
  }

  return items.sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name));
}

/** Read request body as string */
function readBody(req: import('http').IncomingMessage): Promise<string> {
  return new Promise((resolve, reject) => {
    const chunks: Buffer[] = [];
    req.on('data', (chunk: Buffer) => chunks.push(chunk));
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf-8')));
    req.on('error', reject);
  });
}

/** Write XML to a temp file, run validate_snippet.py, parse results */
async function validateSnippet(
  agent: string,
  xml: string,
): Promise<{ valid: boolean; errors: string[]; warnings: string[] }> {
  const tmpFile = path.join(agent, 'sandbox', '.validate_tmp.xml');
  fs.writeFileSync(tmpFile, xml, 'utf-8');
  try {
    const { stdout, stderr, exitCode } = await spawnPython(agent, [
      path.join(agent, 'scripts', 'validate_snippet.py'),
      tmpFile,
    ]);

    if (exitCode === 0) {
      return { valid: true, errors: [], warnings: parseValidationOutput(stdout) };
    }
    const output = (stdout + '\n' + stderr).trim();
    return {
      valid: false,
      errors: output ? output.split('\n') : ['Validation failed'],
      warnings: [],
    };
  } finally {
    try { fs.unlinkSync(tmpFile); } catch { /* ignore */ }
  }
}

function parseValidationOutput(output: string): string[] {
  return output
    .split('\n')
    .map(l => l.trim())
    .filter(l => l && l.toLowerCase().includes('warning'));
}

/** Write XML to temp file, call clipboard.py write */
async function clipboardWrite(agent: string, xml: string): Promise<void> {
  const tmpFile = path.join(agent, 'sandbox', '.clipboard_tmp.xml');
  fs.writeFileSync(tmpFile, xml, 'utf-8');
  try {
    const { exitCode, stderr } = await spawnPython(agent, [
      path.join(agent, 'scripts', 'clipboard.py'),
      'write',
      tmpFile,
    ]);
    if (exitCode !== 0) {
      throw new Error(stderr || 'clipboard.py write failed');
    }
  } finally {
    try { fs.unlinkSync(tmpFile); } catch { /* ignore */ }
  }
}

/** Read solution name from CONTEXT.json if present */
function solutionFromContext(agentDir: string): string | undefined {
  try {
    const data = JSON.parse(fs.readFileSync(path.join(agentDir, 'CONTEXT.json'), 'utf-8'));
    return typeof data.solution === 'string' ? data.solution : undefined;
  } catch { return undefined; }
}

/** Cached scripts index — avoids re-reading and parsing the file on every search */
let cachedScriptsIndex: { path: string; mtime: number; rows: string[][] } | null = null;

function getScriptsIndex(main: string, solution: string | undefined): string[][] {
  const indexPath = path.join(resolveContextDir(main, solution), 'scripts.index');
  const mtime = fs.statSync(indexPath).mtimeMs;
  if (cachedScriptsIndex && cachedScriptsIndex.path === indexPath && cachedScriptsIndex.mtime === mtime) {
    return cachedScriptsIndex.rows;
  }
  const data = fs.readFileSync(indexPath, 'utf-8');
  const rows = parseIndex(data);
  cachedScriptsIndex = { path: indexPath, mtime, rows };
  return rows;
}

/** Search scripts.index for matching scripts */
function searchScripts(
  _agent: string,
  query: string,
): { name: string; id: number; folder: string }[] {
  const main = mainAgentDir();
  const solution = solutionFromContext(main);
  const rows = getScriptsIndex(main, solution); // each row: [ScriptName, ScriptID, FolderPath]

  const isNumeric = /^\d+$/.test(query);

  if (isNumeric) {
    // Exact ID match
    const matches = rows.filter(r => r[1] === query);
    return matches.map(r => ({ name: r[0], id: Number(r[1]), folder: r[2] ?? '' }));
  }

  const qLower = query.toLowerCase();
  const tokens = qLower.split(/\s+/);

  // Exact name match (case-insensitive)
  const exact = rows.filter(r => r[0].toLowerCase() === qLower);
  if (exact.length > 0) {
    return exact.slice(0, 20).map(r => ({ name: r[0], id: Number(r[1]), folder: r[2] ?? '' }));
  }

  // Contains match: all query tokens present in name
  const contains = rows.filter(r => {
    const nameLower = r[0].toLowerCase();
    return tokens.every(t => nameLower.includes(t));
  });

  return contains.slice(0, 20).map(r => ({ name: r[0], id: Number(r[1]), folder: r[2] ?? '' }));
}

/** Discover the solution name (first directory under xml_parsed/scripts/) */
function discoverSolution(): string | null {
  const main = mainAgentDir();
  const scriptsDir = path.join(main, 'xml_parsed', 'scripts');
  if (!fs.existsSync(scriptsDir)) return null;
  const entries = fs.readdirSync(scriptsDir, { withFileTypes: true });
  const dir = entries.find(e => e.isDirectory());
  return dir?.name ?? null;
}

/**
 * Find a script file by ID using filesystem search.
 * Folder paths in scripts.index don't include the ` - ID <n>` suffixes
 * that appear in actual directory names, so we search by filename pattern.
 */
function findScriptFile(baseDir: string, scriptId: string, ext: string): string | null {
  const suffix = `- ID ${scriptId}${ext}`;

  function search(dir: string): string | null {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        const found = search(full);
        if (found) return found;
      } else if (entry.name.endsWith(suffix)) {
        return full;
      }
    }
    return null;
  }

  return search(baseDir);
}

/** Load a script's HR text and convert SaXML to fmxmlsnippet */
async function loadScript(
  agent: string,
  scriptId: string,
  _scriptName: string,
): Promise<{ hr?: string; xml?: string; name?: string }> {
  const main = mainAgentDir();
  const solution = discoverSolution();
  if (!solution) throw new Error('No solution found in xml_parsed/scripts/');

  const sanitizedDir = path.join(main, 'xml_parsed', 'scripts_sanitized', solution);
  const scriptsDir = path.join(main, 'xml_parsed', 'scripts', solution);

  const hrFile = findScriptFile(sanitizedDir, scriptId, '.txt');
  const xmlFile = findScriptFile(scriptsDir, scriptId, '.xml');

  const result: { hr?: string; xml?: string; name?: string } = {};

  if (hrFile) {
    result.hr = fs.readFileSync(hrFile, 'utf-8');
    // Extract script name from filename: "Name - ID 123.txt"
    const baseName = path.basename(hrFile, '.txt');
    const nameMatch = baseName.match(/^(.+?)\s*-\s*ID\s+\d+$/);
    if (nameMatch) result.name = nameMatch[1].trim();
  }

  if (xmlFile) {
    try {
      const { stdout, exitCode, stderr } = await spawnPython(agent, [
        path.join(agent, 'scripts', 'fm_xml_to_snippet.py'),
        xmlFile,
      ]);
      if (exitCode === 0 && stdout.trim()) {
        result.xml = stdout;
      } else if (stderr) {
        console.warn('fm_xml_to_snippet.py warnings:', stderr);
        if (stdout.trim()) result.xml = stdout;
      }
    } catch {
      // Conversion failed — still return HR if we have it
    }

    if (!result.name) {
      const baseName = path.basename(xmlFile, '.xml');
      const nameMatch = baseName.match(/^(.+?)\s*-\s*ID\s+\d+$/);
      if (nameMatch) result.name = nameMatch[1].trim();
    }
  }

  if (!result.hr && !result.xml) {
    throw new Error(`Script ID ${scriptId} not found in xml_parsed`);
  }

  return result;
}

/** Compare semver strings: returns >0 if a > b, <0 if a < b, 0 if equal */
function compareVersions(a: string, b: string): number {
  const pa = a.split('.').map(Number);
  const pb = b.split('.').map(Number);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const na = pa[i] ?? 0;
    const nb = pb[i] ?? 0;
    if (na !== nb) return na - nb;
  }
  return 0;
}

/** Call clipboard.py read, return XML */
async function clipboardRead(agent: string): Promise<string> {
  const tmpFile = path.join(agent, 'sandbox', '.clipboard_read_tmp.xml');
  try {
    const { exitCode, stderr } = await spawnPython(agent, [
      path.join(agent, 'scripts', 'clipboard.py'),
      'read',
      tmpFile,
    ]);
    if (exitCode !== 0) {
      throw new Error(stderr || 'clipboard.py read failed');
    }
    return fs.readFileSync(tmpFile, 'utf-8');
  } finally {
    try { fs.unlinkSync(tmpFile); } catch { /* ignore */ }
  }
}
