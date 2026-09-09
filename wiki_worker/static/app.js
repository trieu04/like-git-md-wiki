function wikiApp() {
  return {
    view: 'contribute', config: {}, skillRole: 'contributor', skillContent: '',
    notice: '', error: false, busy: false, generated: null,
    form: {id: '', submitter: '', reason: '', content: '', scopeFiles: '', sourceFiles: '', editMode: '', before: '', change: ''},
    contributions: [], contribution: null, contributionId: '', decision: '', decisionReason: '',
    importText: '', importAuthor: '', wikiPaths: [], documentContent: '', selectedPath: '', selectedReference: null,
    collapsedFolders: [],
    async init() {
      try { this.config = await this.request('/api/config'); await this.refresh(); }
      catch (e) { this.fail(e); }
    },
    async request(path, options = {}) {
      const response = await fetch(path, {headers: {'Content-Type': 'application/json'}, ...options});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
      return data;
    },
    async requestText(path) {
      const response = await fetch(path);
      const data = await response.text();
      if (!response.ok) throw new Error(data || `HTTP ${response.status}`);
      return data;
    },
    async refresh() {
      try {
        [this.contributions, this.wikiPaths] = await Promise.all([
          this.request('/api/contribution'), this.request('/api/wiki')]);
      }
      catch (e) { this.fail(e); }
    },
    get wikiTree() {
      const rows = [], folders = new Set();
      for (const path of [...this.wikiPaths].sort((left, right) => left.localeCompare(right))) {
        const parts = path.split('/');
        for (let depth = 0; depth < parts.length - 1; depth++) {
          const key = parts.slice(0, depth + 1).join('/');
          if (!folders.has(key)) { folders.add(key); rows.push({type:'folder', key:'d:' + key, name:parts[depth], depth}); }
        }
        rows.push({type:'file', key:'f:' + path, path, name:parts.at(-1), depth:parts.length - 1});
      }
      return rows;
    },
    get visibleWikiTree() {
      return this.wikiTree.filter(row => row.type === 'folder' || !this.collapsedFolders.some(folder => row.path.startsWith(folder + '/')));
    },
    isFolderExpanded(path) { return !this.collapsedFolders.includes(path); },
    toggleFolder(path) {
      this.collapsedFolders = this.isFolderExpanded(path)
        ? [...this.collapsedFolders, path]
        : this.collapsedFolders.filter(folder => folder !== path);
    },
    async openDocument(path) {
      this.clear(); this.documentContent = ''; this.selectedReference = null; this.selectedPath = path;
      try {
        const document = await this.request('/api/wiki/document?path=' + encodeURIComponent(path));
        this.documentContent = document.content; this.selectedReference = document.reference; this.view = 'document';
      } catch (e) { this.fail(e); }
    },
    async openSkill(role) {
      this.clear(); this.skillRole = role; this.skillContent = '';
      try {
        this.skillContent = await this.requestText('/api/skill/' + encodeURIComponent(role));
        this.view = 'skill';
      } catch (e) { this.fail(e); }
    },
    startContribution() {
      this.clear();
      if (!this.selectedReference) { this.fail(new Error('Chọn file chính từ cây Wiki files trước.')); return; }
      const first = this.form.scopeFiles.split('\n')[0].split('|').map(value => value.trim());
      const sameTarget = first[0] === this.selectedReference.path && first[1] === this.selectedReference.version;
      Object.assign(this.form, {content: this.bodyText(this.documentContent), editMode: '', before: '', change: '',
        scopeFiles: sameTarget ? this.form.scopeFiles : `${this.selectedReference.path} | ${this.selectedReference.version} | `});
      this.generated = null; this.view = 'contribute';
    },
    async hash(text) {
      const bytes = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
      return Array.from(new Uint8Array(bytes), b => b.toString(16).padStart(2, '0')).join('');
    },
    markdownHtml(text) {
      const source = text == null ? '' : String(text);
      if (typeof globalThis.marked === 'undefined' || typeof globalThis.DOMPurify === 'undefined') {
        const escaped = source.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        return `<pre>${escaped}</pre>`;
      }
      return globalThis.DOMPurify.sanitize(globalThis.marked.parse(source));
    },
    async readSmall(file) {
      if (!file || file.size > 4 * 1024 * 1024 + 65536) throw new Error('Chọn file không quá 4 MiB + 64 KiB.');
      return file.text();
    },
    bodyText(text) { return text.replace(/^<!-- wiki-review: start -->[\s\S]*?<!-- wiki-review: end -->\s*/, ''); },
    tableCell(text) { return String(text).replace(/\\/g, '\\\\').replace(/\|/g, '\\|').replace(/\r?\n/g, '<br>'); },
    parseScope(text) {
      const result = [], paths = new Set();
      for (const line of text.split('\n').map(x => x.trim()).filter(Boolean)) {
        const parts = line.split('|').map(x => x.trim());
        if (parts.length !== 3 || !parts[0] || !/^\d{8}-\d+$/.test(parts[1]) || !parts[2]) throw new Error('Phạm vi phải có dạng: file | YYYYMMDD-N | tác động.');
        if (paths.has(parts[0])) throw new Error('Phạm vi không được trùng file.');
        paths.add(parts[0]); result.push({path: parts[0], version: parts[1], impact: parts[2]});
      }
      return result;
    },
    parseReferences(text) {
      const result = [], paths = new Set();
      for (const line of text.split('\n').map(x => x.trim()).filter(Boolean)) {
        const parts = line.split('|').map(x => x.trim());
        if (parts.length !== 2 || !parts[0] || !/^\d{8}-\d+$/.test(parts[1])) throw new Error('Nguồn phải có dạng: file | YYYYMMDD-N.');
        if (paths.has(parts[0])) throw new Error('Nguồn không được trùng file.');
        paths.add(parts[0]); result.push({path: parts[0], version: parts[1]});
      }
      return result;
    },
    proposedContent(form) {
      const base = this.bodyText(this.documentContent);
      if (form.editMode === 'replace') {
        if (!form.before) throw new Error('Nhập đoạn cần thay thế.');
        if (base.split(form.before).length !== 2) throw new Error('Đoạn cần thay thế phải xuất hiện đúng một lần trong file chính.');
        return base.replace(form.before, form.change);
      }
      if (form.editMode === 'append') {
        if (!form.change.trim()) throw new Error('Nhập nội dung cần thêm.');
        return base + (base && !base.endsWith('\n') ? '\n' : '') + form.change;
      }
      return form.content;
    },
    async createFile() {
      this.busy = true; this.clear(); this.generated = null;
      try {
        const f = this.form;
        const proposed = this.proposedContent(f);
        if (!this.selectedReference || !/^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/.test(f.id) || !f.submitter.trim() || !f.reason.trim() || !proposed.trim()) throw new Error('Điền phạm vi, mã, tác giả, lý do và nội dung.');
        if (proposed.includes('<!-- wiki-review:')) throw new Error('Bản sửa không được chứa khối trạng thái review cũ.');
        const scope = this.parseScope(f.scopeFiles), sources = this.parseReferences(f.sourceFiles);
        if (!scope.length || scope[0].path !== this.selectedReference.path || scope[0].version !== this.selectedReference.version) throw new Error('Dòng đầu phạm vi phải khớp file và phiên bản đã mở. Chọn file từ cây wiki rồi bấm Tạo đóng góp để đổi file cần sửa.');
        const baseHash = await this.hash(this.documentContent), proposedHash = await this.hash(proposed);
        if (baseHash !== this.selectedReference.hash) throw new Error('Nội dung file chính không khớp phiên bản đã chọn. Mở lại file từ cây wiki.');
        const scopeRows = scope.map(x => `| ${x.path} | ${x.version} | ${this.tableCell(x.impact)} |`).join('\n');
        const sourceRows = sources.map(x => `| ${x.path} | ${x.version} |`).join('\n');
        let boundary = `wc-${baseHash}`;
        while (this.documentContent.includes(boundary) || proposed.includes(boundary)) boundary += '-';
        const text = `# Wiki contribution\n\n| Field | Value |\n| --- | --- |\n| Format | wiki-contribution-v3 |\n| Boundary | ${boundary} |\n| ID | ${this.tableCell(f.id)} |\n| Base SHA-256 | ${baseHash} |\n| Proposed SHA-256 | ${proposedHash} |\n| Author | ${this.tableCell(f.submitter)} |\n| Reason | ${this.tableCell(f.reason)} |\n\n## Scope and impact files\n\n| File | Version | Impact |\n| --- | --- | --- |\n${scopeRows}\n\n## Sources\n\n| File | Version |\n| --- | --- |\n${sourceRows}\n\n## Proposed content\n\n--- ${boundary}:proposed ---\n\n${proposed}\n\n--- ${boundary}:base ---\n\n## Base content\n\n${this.documentContent}\n\n--- ${boundary}:end ---\n`;
        if (new TextEncoder().encode(text).length > 4 * 1024 * 1024 + 65536) throw new Error('File đóng góp vượt giới hạn kích thước.');
        this.generated = {name: f.id + '.contribution.md', text};
        this.notice = 'Đã tạo file trong trình duyệt. Tải file để giao reviewer.';
      } catch (e) { this.fail(e); } finally { this.busy = false; }
    },
    downloadFile() {
      if (!this.generated) return;
      const url = URL.createObjectURL(new Blob([this.generated.text], {type: 'text/markdown'}));
      const link = document.createElement('a'); link.href = url; link.download = this.generated.name;
      document.body.appendChild(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
    async loadImport(event) {
      this.importText = ''; this.importAuthor = ''; this.clear();
      try {
        const text = await this.readSmall(event.target.files[0]);
        if (!text.startsWith('# Wiki contribution\n\n| Field | Value |')) throw new Error('Chọn file .contribution.md. Bundle thư mục dùng lệnh scan.');
        this.importText = text;
      } catch (e) { this.fail(e); }
    },
    async importFile() {
      this.busy = true; this.clear();
      try {
        const result = await this.request('/api/contribution/import', {method: 'POST', body: JSON.stringify({file: this.importText, submitter: this.importAuthor})});
        await this.refresh(); await this.openContribution(result.id);
        this.notice = 'Đã tiếp nhận file. Nội dung đang chờ review.';
      } catch (e) { this.fail(e); } finally { this.busy = false; }
    },
    async openContribution(id) {
      this.clear(); this.contribution = null; this.decision = ''; this.decisionReason = '';
      try {
        this.contribution = await this.request('/api/contribution/' + encodeURIComponent(id));
        this.contributionId = id; this.view = 'review';
      } catch (e) { this.fail(e); }
    },
    async decide() {
      if (!this.decision || !this.decisionReason.trim()) return;
      this.busy = true; this.clear();
      try {
        const c = this.contribution;
        await this.request(`/api/contribution/${encodeURIComponent(c.id)}/review`, {method: 'POST', body: JSON.stringify({
          bundle_hash: c.bundle_hash, time: c.time, artifact: c.artifact, actor: this.config.reviewer,
          reason: this.decisionReason, approve: this.decision === 'approve'})});
        await this.refresh(); await this.openContribution(c.id); this.notice = 'Đã ghi quyết định của reviewer.';
      } catch (e) { this.fail(e); } finally { this.busy = false; }
    },
    async publish() {
      this.busy = true; this.clear();
      try {
        const id = this.contribution.id;
        const result = await this.request(`/api/contribution/${encodeURIComponent(id)}/publish`, {method: 'POST', body: '{}'});
        await this.refresh(); await this.openContribution(id); this.notice = 'Kết quả: ' + this.stateLabel(result.state);
      } catch (e) { this.fail(e); } finally { this.busy = false; }
    },
    stateLabel(state) { return ({pending:'Chờ review',approved:'Đã duyệt',rejected:'Từ chối',published:'Đã xuất bản',stale:'Cần đóng góp mới'})[state] || state; },
    contextLabel(state) { return ({current:'Nguồn vẫn khớp phiên bản đã đọc.',stale:'Ngữ cảnh đã thay đổi. Cần đọc lại và tạo đóng góp mới.',unversioned:'Chưa có ngữ cảnh được ghim phiên bản.'})[state] || state; },
    clear() { this.notice = ''; this.error = false; },
    fail(error) { this.error = true; this.notice = error.message || String(error); }
  };
}
