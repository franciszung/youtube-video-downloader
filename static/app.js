// YouTube 下载器前端

const API = {
    async getConfig() {
        const r = await fetch('/api/config');
        return r.json();
    },
    async saveConfig(cfg) {
        const r = await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cfg)
        });
        return r.json();
    },
    async getFormats(url) {
        const r = await fetch('/api/formats', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });
        return r.json();
    },
    async download(data) {
        const r = await fetch('/api/download', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data)
        });
        return r.json();
    },
    async getTasks() {
        const r = await fetch('/api/tasks');
        return r.json();
    },
    async getFiles() {
        const r = await fetch('/api/files');
        return r.json();
    },
    async deleteFile(filename) {
        const r = await fetch('/api/delete-file', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename })
        });
        return r.json();
    },
    async extractFrames(filename, count) {
        const r = await fetch('/api/extract-frames', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ filename, count })
        });
        return r.json();
    }
};

let currentConfig = {};
let pollTimer = null;
let settingsCollapsed = false;

function formatBytes(bytes) {
    if (!bytes) return '0 B';
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
}

function formatDuration(seconds) {
    if (!seconds) return '';
    const m = Math.floor(seconds / 60);
    const s = Math.floor(seconds % 60);
    return `${m}:${s.toString().padStart(2, '0')}`;
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

async function loadConfig() {
    try {
        currentConfig = await API.getConfig();
        document.getElementById('proxy').value = currentConfig.proxy || '';
        document.getElementById('use-proxy').checked = currentConfig.use_proxy !== false;
        document.getElementById('nodejs-runtime').value = currentConfig.nodejs_runtime || '';
        document.getElementById('use-nodejs-runtime').checked = currentConfig.use_nodejs_runtime !== false;
        document.getElementById('cookies-source').value = currentConfig.cookies_source || '';
        document.getElementById('use-cookies').checked = currentConfig.use_cookies === true;
        document.getElementById('output-dir').value = currentConfig.output_dir || '';
    } catch (e) {
        showToast('加载配置失败: ' + e.message, 'error');
    }
}

async function saveSettings() {
    const cfg = {
        proxy: document.getElementById('proxy').value.trim(),
        use_proxy: document.getElementById('use-proxy').checked,
        nodejs_runtime: document.getElementById('nodejs-runtime').value.trim(),
        use_nodejs_runtime: document.getElementById('use-nodejs-runtime').checked,
        cookies_source: document.getElementById('cookies-source').value.trim(),
        use_cookies: document.getElementById('use-cookies').checked,
        output_dir: document.getElementById('output-dir').value.trim()
    };
    try {
        await API.saveConfig(cfg);
        currentConfig = cfg;
        showToast('设置已保存', 'success');
    } catch (e) {
        showToast('保存失败: ' + e.message, 'error');
    }
}

async function resetSettings() {
    const defaults = {
        proxy: 'http://127.0.0.1:7892',
        use_proxy: true,
        nodejs_runtime: 'C:/Users/francis/.workbuddy/binaries/node/versions/22.22.2/node.exe',
        use_nodejs_runtime: true,
        output_dir: '',
        default_quality: '1080p'
    };
    try {
        await API.saveConfig(defaults);
        await loadConfig();
        showToast('已恢复默认设置', 'success');
    } catch (e) {
        showToast('重置失败: ' + e.message, 'error');
    }
}

async function fetchFormats() {
    const url = document.getElementById('url').value.trim();
    if (!url) {
        showToast('请输入 YouTube URL', 'error');
        return;
    }
    const btn = document.getElementById('btn-formats');
    btn.disabled = true;
    btn.textContent = '获取中...';
    try {
        const data = await API.getFormats(url);
        btn.disabled = false;
        btn.textContent = '获取格式';
        if (data.error) {
            showToast(data.error, 'error');
            return;
        }
        renderFormats(data.title, data.formats);
    } catch (e) {
        btn.disabled = false;
        btn.textContent = '获取格式';
        showToast('获取格式失败: ' + e.message, 'error');
    }
}

function renderFormats(title, formats) {
    const panel = document.getElementById('formats-panel');
    const tbody = document.querySelector('#formats-table tbody');
    tbody.innerHTML = '';

    if (title) {
        const h3 = panel.querySelector('h3');
        h3.textContent = `可用格式 - ${title}`;
    }

    // 过滤出比较有意义的格式
    const seen = new Set();
    const display = formats.filter(f => {
        if (seen.has(f.id)) return false;
        seen.add(f.id);
        return true;
    }).slice(0, 80);

    display.forEach(f => {
        const tr = document.createElement('tr');
        tr.innerHTML = `
            <td>${f.id}</td>
            <td>${f.ext}</td>
            <td>${f.resolution}</td>
            <td>${f.fps}</td>
            <td>${f.note}</td>
        `;
        tbody.appendChild(tr);
    });

    panel.classList.remove('hidden');
}

async function startDownload() {
    const url = document.getElementById('url').value.trim();
    if (!url) {
        showToast('请输入 YouTube URL', 'error');
        return;
    }

    const quality = document.getElementById('quality').value;
    const outputName = document.getElementById('output-name').value.trim();
    const extractFrames = document.getElementById('extract-frames').checked;

    const btn = document.getElementById('btn-download');
    btn.disabled = true;
    btn.textContent = '已提交...';

    try {
        const data = await API.download({
            url,
            quality,
            output_name: outputName,
            extract_frames: extractFrames
        });
        btn.disabled = false;
        btn.textContent = '开始下载';
        if (data.error) {
            showToast(data.error, 'error');
            return;
        }
        showToast('下载任务已创建', 'success');
        document.getElementById('url').value = '';
        startPolling();
    } catch (e) {
        btn.disabled = false;
        btn.textContent = '开始下载';
        showToast('创建任务失败: ' + e.message, 'error');
    }
}

async function renderTasks() {
    try {
        const tasks = await API.getTasks();
        const container = document.getElementById('tasks-list');
        if (!tasks.length) {
            container.innerHTML = '<p class="empty">暂无任务</p>';
            return;
        }
        container.innerHTML = '';
        tasks.slice().reverse().forEach(task => {
            container.appendChild(createTaskElement(task));
        });
        // 自动展开进行中任务的日志
        tasks.forEach(task => {
            if (['preparing','downloading','merging','extracting_frames'].includes(task.status)) {
                const logEl = document.getElementById(`log-${task.id}`);
                if (logEl) logEl.classList.remove('hidden');
            }
        });
    } catch (e) {
        console.error('renderTasks error', e);
    }
}

async function checkServiceStatus() {
    const el = document.getElementById('service-status');
    try {
        const cfg = await API.getConfig();
        el.textContent = `服务正常 · yt-dlp: ${cfg.ytdlp_version || '未知'}`;
        el.className = 'service-status ok';
    } catch (e) {
        el.textContent = '服务连接失败，请检查 start.bat 是否已启动';
        el.className = 'service-status error';
    }
}

function createTaskElement(task) {
    const div = document.createElement('div');
    div.className = 'task-item';
    div.id = `task-${task.id}`;

    const statusClass = `status-${task.status}`;
    const statusText = {
        queued: '等待中',
        preparing: '解析中',
        downloading: '下载中',
        merging: '合并中',
        extracting_frames: '提取帧',
        completed: '完成',
        failed: '失败'
    }[task.status] || task.status;

    const fileInfo = task.file ? `
        <div class="file-meta">
            文件: ${task.file.name} · ${formatBytes(task.file.size)} · ${task.file.resolution} · ${formatDuration(task.file.duration)}
        </div>
    ` : '';

    const framesHtml = task.frames && task.frames.length ? `
        <div class="frames-grid">
            ${task.frames.map(f => `
                <div class="frame-thumb">
                    <img src="/thumbnails/${task.file ? task.file.name.replace('.mp4', '') : ''}/${f.file}" alt="" onerror="this.style.display='none'">
                    <div class="frame-time">${f.time}s</div>
                </div>
            `).join('')}
        </div>
    ` : '';

    const isActive = ['queued','preparing','downloading','merging','extracting_frames'].includes(task.status);
    const filenameHint = task.output_name ? `输出文件: ${task.output_name}.mp4` : '';

    div.innerHTML = `
        <div class="task-header">
            <div class="task-title">${task.title || task.url}</div>
            <div class="task-status ${statusClass}">${statusText}</div>
        </div>
        ${filenameHint ? `<div class="task-filename">${filenameHint}</div>` : ''}
        <div class="task-message">${task.message || ''}</div>
        <div class="progress-bar">
            <div class="progress-fill" style="width: ${task.progress || 0}%"></div>
        </div>
        <div class="task-meta">
            ${task.speed ? `<span>速度: ${task.speed}</span>` : ''}
            ${task.downloaded ? `<span>已下载: ${task.downloaded}</span>` : ''}
            ${task.total_size ? `<span>总大小: ${task.total_size}</span>` : ''}
            ${task.quality ? `<span>清晰度: ${task.quality}</span>` : ''}
        </div>
        ${fileInfo}
        ${framesHtml}
        <div class="task-actions">
            <button onclick="toggleLog('${task.id}')">${isActive ? '隐藏日志' : '查看日志'}</button>
            ${task.status === 'completed' && task.file ? `<a href="/downloads/${task.file.name}" download target="_blank"><button>下载到本地</button></a>` : ''}
            ${task.status === 'completed' && task.file ? `<button onclick="extractFrames('${task.file.name}')">提取关键帧</button>` : ''}
        </div>
        <div id="log-${task.id}" class="task-log ${isActive ? '' : 'hidden'}">${(task.log || []).join('\n')}</div>
    `;
    return div;
}

window.toggleLog = function(taskId) {
    const el = document.getElementById(`log-${taskId}`);
    el.classList.toggle('hidden');
};

window.extractFrames = async function(filename) {
    try {
        const data = await API.extractFrames(filename, 8);
        if (data.error) {
            showToast(data.error, 'error');
            return;
        }
        showToast(`已提取 ${data.frames.length} 张关键帧`, 'success');
        renderTasks();
        renderFiles();
    } catch (e) {
        showToast('提取失败: ' + e.message, 'error');
    }
};

async function cleanupJunk() {
    if (!confirm('清理 downloads 目录下的所有临时文件 (.part-Frag*、.f*.m4a 等)?\n\n不会影响已下载的 MP4 文件。')) return;
    try {
        const data = await fetch('/api/cleanup-junk', { method: 'POST' }).then(r => r.json());
        if (data.error) {
            showToast(data.error, 'error');
            return;
        }
        const msg = `已清理 ${data.removed} 个临时文件` + (data.failed && data.failed.length ? `,失败 ${data.failed.length} 个` : '');
        showToast(msg, 'success');
        renderFiles();
    } catch (e) {
        showToast('清理失败: ' + e.message, 'error');
    }
}

window.cleanupJunk = cleanupJunk;

async function renderFiles() {
    try {
        const files = await API.getFiles();
        const container = document.getElementById('files-list');
        if (!files.length) {
            container.innerHTML = '<p class="empty">暂无文件</p>';
            return;
        }
        container.innerHTML = '';
        files.slice().reverse().forEach(f => {
            const div = document.createElement('div');
            div.className = 'file-item';
            div.innerHTML = `
                <div class="file-header">
                    <div class="file-name">${f.name}</div>
                </div>
                <div class="file-meta">${formatBytes(f.size)} · ${new Date(f.modified).toLocaleString()}</div>
                <div class="file-actions">
                    <a href="/downloads/${f.name}" download target="_blank"><button>播放/下载</button></a>
                    <button onclick="extractFrames('${f.name}')">提取关键帧</button>
                    <button onclick="deleteFile('${f.name}')" class="btn-danger">删除</button>
                </div>
            `;
            container.appendChild(div);
        });
    } catch (e) {
        console.error('renderFiles error', e);
    }
}

window.deleteFile = async function(filename) {
    if (!confirm(`确定删除 ${filename} 吗？`)) return;
    try {
        const data = await API.deleteFile(filename);
        if (data.error) {
            showToast(data.error, 'error');
            return;
        }
        showToast('已删除', 'success');
        renderFiles();
    } catch (e) {
        showToast('删除失败: ' + e.message, 'error');
    }
};

function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(async () => {
        await renderTasks();
        await renderFiles();
    }, 1500);
}

function toggleSettings() {
    const panel = document.getElementById('settings-panel');
    const btn = document.getElementById('btn-toggle-settings');
    settingsCollapsed = !settingsCollapsed;
    panel.classList.toggle('hidden', settingsCollapsed);
    btn.textContent = settingsCollapsed ? '▶' : '▼';
}

async function clearCompleted() {
    // 前端不直接删除任务，只是刷新列表
    await renderTasks();
    showToast('已刷新任务列表', 'info');
}

document.addEventListener('DOMContentLoaded', () => {
    loadConfig();
    checkServiceStatus();
    renderFiles();
    startPolling();

    document.getElementById('btn-download').addEventListener('click', startDownload);
    document.getElementById('btn-formats').addEventListener('click', fetchFormats);
    document.getElementById('btn-save-settings').addEventListener('click', saveSettings);
    document.getElementById('btn-reset-settings').addEventListener('click', resetSettings);
    document.getElementById('btn-toggle-settings').addEventListener('click', toggleSettings);
    document.getElementById('btn-refresh-files').addEventListener('click', renderFiles);
    document.getElementById('btn-clear-tasks').addEventListener('click', clearCompleted);
    document.getElementById('btn-cleanup-junk').addEventListener('click', cleanupJunk);
});
