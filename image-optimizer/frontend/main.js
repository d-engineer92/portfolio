/**
 * Image Optimizer — Frontend Logic
 */

(() => {
    'use strict';

    // --- DOM refs ---
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const optionsPanel = document.getElementById('optionsPanel');
    const fileList = document.getElementById('fileList');
    const optimizeBtn = document.getElementById('optimizeBtn');
    const clearBtn = document.getElementById('clearBtn');
    const stripMetadata = document.getElementById('stripMetadata');
    const convertWebp = document.getElementById('convertWebp');
    const qualitySlider = document.getElementById('qualitySlider');
    const qualityValue = document.getElementById('qualityValue');
    const progressPanel = document.getElementById('progressPanel');
    const resultsPanel = document.getElementById('resultsPanel');
    const resultsSummary = document.getElementById('resultsSummary');
    const resultsGrid = document.getElementById('resultsGrid');
    const downloadBtn = document.getElementById('downloadBtn');
    const newBtn = document.getElementById('newBtn');

    let selectedFiles = [];
    let lastBlob = null;
    let lastFilename = '';

    // --- Helpers ---
    function formatBytes(bytes) {
        if (bytes === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(1024));
        return (bytes / Math.pow(1024, i)).toFixed(i > 0 ? 1 : 0) + ' ' + units[i];
    }

    function show(el) { el.classList.remove('hidden'); }
    function hide(el) { el.classList.add('hidden'); }

    // --- Quality slider ---
    qualitySlider.addEventListener('input', () => {
        qualityValue.textContent = qualitySlider.value;
    });

    // --- Drag & Drop ---
    ['dragenter', 'dragover'].forEach(event => {
        dropZone.addEventListener(event, e => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });
    });

    ['dragleave', 'drop'].forEach(event => {
        dropZone.addEventListener(event, e => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
        });
    });

    dropZone.addEventListener('drop', e => {
        const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
        if (files.length) addFiles(files);
    });

    dropZone.addEventListener('click', e => {
        if (e.target.tagName !== 'LABEL' && e.target.tagName !== 'INPUT') {
            fileInput.click();
        }
    });

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length) {
            addFiles(Array.from(fileInput.files));
            fileInput.value = '';
        }
    });

    // --- File management ---
    function addFiles(files) {
        for (const file of files) {
            if (selectedFiles.length >= 20) break;
            if (!selectedFiles.some(f => f.name === file.name && f.size === file.size)) {
                selectedFiles.push(file);
            }
        }
        renderFileList();
        show(optionsPanel);
        hide(resultsPanel);
    }

    function removeFile(index) {
        selectedFiles.splice(index, 1);
        if (selectedFiles.length === 0) {
            hide(optionsPanel);
        }
        renderFileList();
    }

    function renderFileList() {
        fileList.innerHTML = selectedFiles.map((file, i) => {
            const thumbUrl = URL.createObjectURL(file);
            return `
                <div class="file-item">
                    <div class="file-item-icon">
                        <img src="${thumbUrl}" alt="" loading="lazy">
                    </div>
                    <span class="file-item-name" title="${file.name}">${file.name}</span>
                    <span class="file-item-size">${formatBytes(file.size)}</span>
                    <button class="file-item-remove" data-index="${i}" title="削除">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                            <line x1="18" y1="6" x2="6" y2="18" />
                            <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                    </button>
                </div>
            `;
        }).join('');

        fileList.querySelectorAll('.file-item-remove').forEach(btn => {
            btn.addEventListener('click', () => removeFile(parseInt(btn.dataset.index)));
        });
    }

    // --- Clear ---
    clearBtn.addEventListener('click', () => {
        selectedFiles = [];
        lastBlob = null;
        lastFilename = '';
        fileList.innerHTML = '';
        hide(optionsPanel);
        hide(resultsPanel);
    });

    // --- New ---
    newBtn.addEventListener('click', () => {
        selectedFiles = [];
        lastBlob = null;
        lastFilename = '';
        fileList.innerHTML = '';
        hide(resultsPanel);
        hide(optionsPanel);
    });

    // --- Optimize ---
    optimizeBtn.addEventListener('click', async () => {
        if (selectedFiles.length === 0) return;

        optimizeBtn.disabled = true;
        hide(optionsPanel);
        show(progressPanel);
        hide(resultsPanel);

        const formData = new FormData();
        for (const file of selectedFiles) {
            formData.append('files', file);
        }
        formData.append('strip_metadata', stripMetadata.checked ? 'true' : 'false');
        formData.append('convert_webp', convertWebp.checked ? 'true' : 'false');
        formData.append('quality', qualitySlider.value);

        try {
            if (selectedFiles.length === 1) {
                await optimizeSingle(formData);
            } else {
                await optimizeMultiple(formData);
            }
        } catch (err) {
            alert('エラー: ' + (err.message || '最適化に失敗しました'));
            show(optionsPanel);
        } finally {
            hide(progressPanel);
            optimizeBtn.disabled = false;
        }
    });

    async function optimizeSingle(formData) {
        const resp = await fetch('api/optimize', { method: 'POST', body: formData });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        const blob = await resp.blob();
        const origSize = parseInt(resp.headers.get('X-Original-Size') || '0');
        const optSize = parseInt(resp.headers.get('X-Optimized-Size') || blob.size);
        const savingsPct = parseFloat(resp.headers.get('X-Savings-Pct') || '0');
        const outputFormat = resp.headers.get('X-Output-Format') || '';
        const width = resp.headers.get('X-Width') || '';
        const height = resp.headers.get('X-Height') || '';

        const contentDisp = resp.headers.get('Content-Disposition') || '';
        const utf8Match = contentDisp.match(/filename\*=UTF-8''(.+?)(?:;|$)/i);
        const plainMatch = contentDisp.match(/filename="?([^"]+)"?/);
        if (utf8Match) {
            lastFilename = decodeURIComponent(utf8Match[1]);
        } else if (plainMatch) {
            lastFilename = plainMatch[1];
        } else {
            lastFilename = 'optimized_image';
        }
        lastBlob = blob;

        const results = [{
            filename: selectedFiles[0].name,
            output_filename: lastFilename,
            original_size: origSize,
            optimized_size: optSize,
            savings_pct: savingsPct,
            output_format: outputFormat,
            width: parseInt(width),
            height: parseInt(height),
        }];

        renderResults(results);
    }

    async function optimizeMultiple(formData) {
        const resp = await fetch('api/optimize', { method: 'POST', body: formData });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${resp.status}`);
        }

        const blob = await resp.blob();
        lastBlob = blob;
        lastFilename = 'optimized_images.zip';

        const resultsHeader = resp.headers.get('X-Results');
        let results = [];
        if (resultsHeader) {
            try { results = JSON.parse(decodeURIComponent(resultsHeader)); } catch { }
        }

        renderResults(results);
    }

    // --- Render Results ---
    function renderResults(results) {
        if (results.length === 0) {
            resultsGrid.innerHTML = '<p style="color: var(--text-secondary); text-align: center;">結果を取得できませんでした</p>';
            show(resultsPanel);
            return;
        }

        const totalOriginal = results.reduce((s, r) => s + r.original_size, 0);
        const totalOptimized = results.reduce((s, r) => s + r.optimized_size, 0);
        const totalSavings = totalOriginal - totalOptimized;
        const totalPct = totalOriginal > 0 ? ((totalSavings / totalOriginal) * 100).toFixed(1) : '0';

        resultsSummary.innerHTML = `
            <div class="summary-stat">
                <span class="summary-stat-value">${results.length}</span>
                <span class="summary-stat-label">ファイル数</span>
            </div>
            <div class="summary-stat">
                <span class="summary-stat-value">${formatBytes(totalOriginal)}</span>
                <span class="summary-stat-label">元サイズ</span>
            </div>
            <div class="summary-stat">
                <span class="summary-stat-value">${formatBytes(totalOptimized)}</span>
                <span class="summary-stat-label">最適化後</span>
            </div>
            <div class="summary-stat">
                <span class="summary-stat-value success">-${totalPct}%</span>
                <span class="summary-stat-label">削減率</span>
            </div>
        `;

        resultsGrid.innerHTML = results.map((r, i) => {
            const savingsClass = r.savings_pct > 0 ? 'positive' : 'neutral';
            const file = selectedFiles[i];
            const thumbUrl = file ? URL.createObjectURL(file) : '';

            return `
                <div class="result-item">
                    <div class="result-thumb">
                        ${thumbUrl ? `<img src="${thumbUrl}" alt="">` : ''}
                    </div>
                    <div class="result-info">
                        <div class="result-filename" title="${r.filename}">${r.filename}</div>
                        <div class="result-meta">
                            <div class="result-sizes">
                                ${formatBytes(r.original_size)}
                                <span class="result-arrow">→</span>
                                ${formatBytes(r.optimized_size)}
                            </div>
                            ${r.output_format ? `<span>${r.output_format}</span>` : ''}
                            ${r.width && r.height ? `<span>${r.width}×${r.height}</span>` : ''}
                        </div>
                    </div>
                    <span class="result-savings ${savingsClass}">
                        ${r.savings_pct > 0 ? '-' : ''}${r.savings_pct}%
                    </span>
                </div>
            `;
        }).join('');

        show(resultsPanel);
    }

    // --- Download ---
    downloadBtn.addEventListener('click', () => {
        if (!lastBlob) return;
        const url = URL.createObjectURL(lastBlob);
        const a = document.createElement('a');
        a.href = url;
        a.download = lastFilename;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
    });

})();
