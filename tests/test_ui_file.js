// Verify the browser form creates the documented Markdown contribution file.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const sandbox = {crypto: webcrypto, TextEncoder, setTimeout};
function payloads(text) {
  const boundary = text.match(/\| Boundary \| (.*?) \|/)[1];
  const payload = text.split(`--- ${boundary}:proposed ---\n\n`)[1];
  const [proposed, tail] = payload.split(`\n\n--- ${boundary}:base ---\n\n## Base content\n\n`);
  return {proposed, base: tail.split(`\n\n--- ${boundary}:end ---\n`)[0]};
}
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('wiki_worker/static/app.js', 'utf8'), sandbox);

(async () => {
  const app = sandbox.wikiApp();
  const base = '# Chính sách\n\nThời hạn 30 ngày.\n';
  const proposed = base.replace('30', '7');
  const primary = {path: 'policy.md', version: '20260908-1', hash: await app.hash(base)};
  const related = {path: 'docs/related.md', version: '20260908-2'};
  const source = {path: 'sources/handbook.md', version: '20260908-3'};
  app.selectedReference = primary;
  app.documentContent = base;
  app.startContribution();
  assert.equal(app.form.scopeFiles, `${primary.path} | ${primary.version} | `);
  Object.assign(app.form, {
    id: 'ui-file', submitter: 'author-agent', reason: 'Policy update', content: proposed,
    scopeFiles: `${primary.path} | ${primary.version} | Thay thời hạn\n${related.path} | ${related.version} | Cần đồng bộ`,
    sourceFiles: `${source.path} | ${source.version}`
  });

  await app.createFile();
  assert.equal(app.error, false);
  assert.equal(app.generated.name, 'ui-file.contribution.md');
  const text = app.generated.text;
  assert.ok(text.startsWith('# Wiki contribution\n'));
  assert.ok(text.includes('| Format | wiki-contribution-v3 |'));
  assert.ok(text.includes('## Scope and impact files'));
  assert.ok(text.includes(`| ${primary.path} | ${primary.version} | Thay thời hạn |`));
  assert.ok(text.includes(`| ${related.path} | ${related.version} | Cần đồng bộ |`));
  assert.ok(text.includes(`| ${source.path} | ${source.version} |`));
  assert.ok(!text.includes('| File | Version | SHA-256 |'));
  assert.ok(text.includes(`| Base SHA-256 | ${primary.hash} |`));
  assert.ok(text.includes(`| Proposed SHA-256 | ${await app.hash(proposed)} |`));
  assert.deepEqual(payloads(text), {base, proposed});
  assert.ok(text.indexOf('## Proposed content') < text.indexOf('## Base content'));

  app.form.scopeFiles = 'bad | version | impact';
  await app.createFile();
  assert.equal(app.error, true);
  assert.equal(app.generated, null);

  app.form.scopeFiles = `${primary.path} | ${primary.version} | Update\n${primary.path} | ${primary.version} | duplicate`;
  await app.createFile();
  assert.equal(app.error, true);

  app.form.scopeFiles = '';
  await app.createFile();
  assert.equal(app.error, true);
  app.form.scopeFiles = `${related.path} | ${related.version} | Wrong target`;
  await app.createFile();
  assert.equal(app.error, true);
  app.form.scopeFiles = `${primary.path} | 20260908-99 | Wrong version`;
  await app.createFile();
  assert.equal(app.error, true);
  app.form.scopeFiles = `${primary.path} | ${primary.version} | Update`;
  app.documentContent = base + 'tampered';
  await app.createFile();
  assert.equal(app.error, true);

  app.documentContent = base;
  app.startContribution();
  assert.equal(app.form.scopeFiles, `${primary.path} | ${primary.version} | Update`);
  app.form.editMode = 'replace'; app.form.before = '30 ngày'; app.form.change = '14 ngày';
  await app.createFile();
  assert.equal(app.error, false);
  assert.equal(payloads(app.generated.text).proposed, base.replace('30', '14'));

  app.form.editMode = 'append'; app.form.change = '\nGhi chú mới.\n';
  await app.createFile();
  assert.equal(app.error, false);
  assert.equal(payloads(app.generated.text).proposed, base + '\nGhi chú mới.\n');

  app.wikiPaths = ['z.md', 'docs/nested.md', 'docs/guide.md', 'index.md'];
  assert.deepEqual(
    JSON.parse(JSON.stringify(app.wikiTree)),
    [
      {type: 'folder', key: 'd:docs', name: 'docs', depth: 0},
      {type: 'file', key: 'f:docs/guide.md', path: 'docs/guide.md', name: 'guide.md', depth: 1},
      {type: 'file', key: 'f:docs/nested.md', path: 'docs/nested.md', name: 'nested.md', depth: 1},
      {type: 'file', key: 'f:index.md', path: 'index.md', name: 'index.md', depth: 0},
      {type: 'file', key: 'f:z.md', path: 'z.md', name: 'z.md', depth: 0}
    ]);
  app.toggleFolder('docs');
  assert.equal(app.isFolderExpanded('docs'), false);
  assert.deepEqual(JSON.parse(JSON.stringify(app.visibleWikiTree.map(row => row.path || row.name))), ['docs', 'index.md', 'z.md']);
  app.toggleFolder('docs');
  assert.equal(app.isFolderExpanded('docs'), true);
  console.log('Contribution Markdown: version-only references and content modes validated.');
})().catch(error => { console.error(error); process.exitCode = 1; });
