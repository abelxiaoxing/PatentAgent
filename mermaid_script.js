// 此脚本应在 mermaid.min.js 库加载后加载。

// 初始化 Mermaid.js
if (typeof mermaid !== 'undefined') {
    mermaid.initialize({
        startOnLoad: false,
        theme: 'neutral'
    });
} else {
    console.error('未找到 Mermaid 库。');
}

/**
 * 渲染 Mermaid 图表并设置 PNG 下载按钮。
 * @param {string} drawingKey - 图表元素的唯一标识符。
 * @param {string} safeTitle - 经过净化的图表标题，用于文件名。
 * @param {string} code - 要渲染的 Mermaid 图表代码。
 */
window.renderMermaid = async function(drawingKey, safeTitle, code) {
    /**
     * 从现有的SVG元素推算宽高，缺失时回退到 viewBox 或默认尺寸。
     */
    const resolveSvgSize = (svgEl) => {
        const getNumber = (value) => {
            if (typeof value === 'string' && value.includes('%')) {
                return undefined; // 忽略百分比，避免取到100%等误导性的尺寸
            }
            const num = parseFloat(value);
            return Number.isFinite(num) ? num : undefined;
        };

        const rect = svgEl.getBoundingClientRect ? svgEl.getBoundingClientRect() : { width: 0, height: 0 };

        let width = getNumber(svgEl.getAttribute('width'));
        let height = getNumber(svgEl.getAttribute('height'));

        let viewBox = svgEl.getAttribute('viewBox') || '';
        let vbParts = viewBox.trim().split(/\s+/).map(getNumber);
        if (vbParts.length !== 4 || vbParts.some(v => !Number.isFinite(v))) {
            vbParts = [];
            viewBox = '';
        }

        // 1) 若已有 viewBox，优先信任其宽高
        if (vbParts.length === 4) {
            width = width || vbParts[2];
            height = height || vbParts[3];
        }

        // 2) 使用布局后的真实尺寸（避免被0宽高属性污染）
        if (!width && rect.width) width = rect.width;
        if (!height && rect.height) height = rect.height;

        // 3) 使用 getBBox 捕获真实内容范围
        if ((!width || !height || !viewBox) && svgEl.getBBox) {
            try {
                const box = svgEl.getBBox();
                width = width || Math.ceil(box.width);
                height = height || Math.ceil(box.height);
                if (!viewBox) {
                    viewBox = `${box.x} ${box.y} ${box.width} ${box.height}`;
                }
            } catch (err) {
                console.warn('获取SVG包围盒失败，使用默认尺寸。', err);
            }
        }

        // 4) 最终兜底
        width = width || svgEl.clientWidth || svgEl.scrollWidth || 1024;
        height = height || svgEl.clientHeight || svgEl.scrollHeight || 768;
        if (!viewBox) {
            viewBox = `0 0 ${width} ${height}`;
        }

        // 不修改原始SVG，避免点击下载后实际渲染变小
        return { width, height, viewBox };
    };

    /**
     * 将SVG克隆并内联部分样式，避免外部依赖导致Canvas被污染。
     */
    const cloneSvgForExport = (svgEl, size) => {
        const { width, height, viewBox } = size;
        const cloned = svgEl.cloneNode(true);
        cloned.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
        cloned.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');
        cloned.setAttribute('width', width);
        cloned.setAttribute('height', height);
        if (viewBox) {
            cloned.setAttribute('viewBox', viewBox);
        } else {
            cloned.setAttribute('viewBox', `0 0 ${width} ${height}`);
        }

        // 保证有一个白色背景，避免透明导致的黑底/花色
        const hasBg = cloned.querySelector('rect[data-export-bg]');
        if (!hasBg) {
            const bg = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
            bg.setAttribute('data-export-bg', 'true');
            bg.setAttribute('x', '0');
            bg.setAttribute('y', '0');
            bg.setAttribute('width', width);
            bg.setAttribute('height', height);
            bg.setAttribute('fill', 'white');
            cloned.insertBefore(bg, cloned.firstChild);
        }

        // 将通用字体嵌入，避免中文/特殊字符在Canvas中丢失
        const style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
        style.textContent = `
            * {
                font-family: "Inter", "Segoe UI", "PingFang SC", "Microsoft YaHei", "Helvetica", "Arial", sans-serif !important;
            }
        `;
        cloned.insertBefore(style, cloned.firstChild);

        return cloned;
    };

    /**
     * 将SVG转为PNG DataURL。
     */
    const svgToPng = (svgEl, safeTitleForLog, errorDiv) => {
        return new Promise((resolve, reject) => {
            try {
                const size = resolveSvgSize(svgEl);
                const { width, height } = size;
                const margin = 16;
                const scale = Math.min(Math.max(window.devicePixelRatio || 1, 1), 3); // 控制缩放，避免超大图
                const logicalWidth = width + margin * 2;
                const logicalHeight = height + margin * 2;
                const canvasWidth = Math.ceil(logicalWidth * scale);
                const canvasHeight = Math.ceil(logicalHeight * scale);

                const cloned = cloneSvgForExport(svgEl, size);
                const svgString = new XMLSerializer().serializeToString(cloned);
                const blob = new Blob(
                    [`<?xml version="1.0" encoding="UTF-8"?>\n${svgString}`],
                    { type: 'image/svg+xml;charset=utf-8' }
                );
                const url = URL.createObjectURL(blob);

                const img = new Image();
                img.crossOrigin = 'anonymous';

                img.onload = () => {
                    try {
                        const canvas = document.createElement('canvas');
                        const ctx = canvas.getContext('2d');
                        if (!ctx) {
                            throw new Error('Canvas 2D 上下文不可用。');
                        }

                        canvas.width = canvasWidth;
                        canvas.height = canvasHeight;
                        ctx.scale(scale, scale);
                        ctx.fillStyle = 'white';
                        ctx.fillRect(0, 0, logicalWidth, logicalHeight);
                        ctx.drawImage(img, margin, margin, width, height);
                        URL.revokeObjectURL(url);

                        canvas.toBlob((pngBlob) => {
                            if (!pngBlob) {
                                reject(new Error('无法生成PNG Blob'));
                                return;
                            }
                            const pngUrl = URL.createObjectURL(pngBlob);
                            resolve(pngUrl);
                        }, 'image/png', 1.0);
                    } catch (err) {
                        URL.revokeObjectURL(url);
                        reject(err);
                    }
                };

                img.onerror = (e) => {
                    URL.revokeObjectURL(url);
                    reject(new Error(`SVG图片加载失败：${e?.message || e}`));
                };

                // 若SVG包含非ASCII字符，使用blob可避免 btoa 的编码问题
                img.src = url;
                errorDiv.innerHTML = '<p style="color:blue;">🔄 正在生成PNG，已内联样式并优化尺寸...</p>';
                console.log(`开始导出PNG: ${safeTitleForLog}, size=${width}x${height}, scale=${scale}`);
            } catch (err) {
                reject(err);
            }
        });
    };

    /**
     * 将 dataURL 下载为文件。
     */
    const triggerDownload = (url, filename) => {
        const a = document.createElement('a');
        a.href = url;
        a.download = `${filename || 'patent_drawing'}.png`;
        a.style.display = 'none';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
    };

    const outputDivId = `mermaid-output-${drawingKey}`;
    const downloadBtnId = `download-btn-${drawingKey}`;
    const errorMsgId = `mermaid-error-${drawingKey}`;

    const outputDiv = document.getElementById(outputDivId);
    const downloadBtn = document.getElementById(downloadBtnId);
    const errorDiv = document.getElementById(errorMsgId);

    if (!outputDiv || !downloadBtn || !errorDiv) {
        console.error(`未找到 drawingKey 为 "${drawingKey}" 所需的元素。`);
        return;
    }

    errorDiv.innerHTML = ''; // 清除之前的错误信息
    outputDiv.innerHTML = '正在渲染...'; // 提供反馈

    try {
        const { svg } = await mermaid.render(outputDivId + '_temp', code);
        outputDiv.innerHTML = svg;

        const svgElement = outputDiv.querySelector('svg');
        if (!svgElement) {
            throw new Error("渲染后未找到 SVG 元素。");
        }

        // 设置下载按钮
        downloadBtn.onclick = function() {
            const svgElementForDownload = outputDiv.querySelector('svg');
            if (!svgElementForDownload) {
                errorDiv.innerHTML = '<p style="color:red;">无法找到要下载的图表 SVG 元素。</p>';
                return;
            }

            svgToPng(svgElementForDownload, safeTitle, errorDiv)
                .then((pngUrl) => {
                    triggerDownload(pngUrl, safeTitle);
                    errorDiv.innerHTML = '<p style="color:green;">✅ PNG下载成功！</p>';
                    // 短暂延迟后释放URL，避免下载中断
                    setTimeout(() => URL.revokeObjectURL(pngUrl), 3000);
                })
                .catch((error) => {
                    console.error("💥 PNG转换失败:", error);
                    errorDiv.innerHTML = `
                        <div style="color:red; padding: 15px; border-radius: 8px; background-color: #ffe6e6; border: 2px solid #ff0000;">
                            <h4 style="margin: 0 0 10px 0;">❌ PNG转换失败</h4>
                            <p style="margin: 5px 0; font-size: 0.9em;">
                                <strong>错误信息:</strong> ${error.message || error}
                            </p>
                            <p style="margin: 5px 0; font-size: 0.9em;">
                                <strong>建议:</strong> 请尝试刷新页面或简化图形。如果仍然失败，可优先点击“导出SVG”后自行转换。</p>
                            <button id="fallback-svg-${drawingKey}" style="padding:6px 10px;border-radius:6px;border:1px solid #999;background:#fff;cursor:pointer;">下载SVG备用</button>
                        </div>
                    `;

                    // 提供SVG兜底下载
                    const fallbackBtn = document.getElementById(`fallback-svg-${drawingKey}`);
                    if (fallbackBtn) {
                        fallbackBtn.onclick = () => {
                            try {
                                const size = resolveSvgSize(svgElementForDownload);
                                const cloned = cloneSvgForExport(svgElementForDownload, size);
                                const svgString = new XMLSerializer().serializeToString(cloned);
                                const blob = new Blob(
                                    [`<?xml version="1.0" encoding="UTF-8"?>\n${svgString}`],
                                    { type: 'image/svg+xml;charset=utf-8' }
                                );
                                const url = URL.createObjectURL(blob);
                                const a = document.createElement('a');
                                a.href = url;
                                a.download = `${safeTitle || 'patent_drawing'}.svg`;
                                a.style.display = 'none';
                                document.body.appendChild(a);
                                a.click();
                                document.body.removeChild(a);
                                setTimeout(() => URL.revokeObjectURL(url), 3000);
                            } catch (err) {
                                console.error('SVG兜底下载失败', err);
                            }
                        };
                    }
                });
        };

    } catch (e) {
        console.error(`渲染 Mermaid 图表时出错，key 为 ${drawingKey}：`, e);
        const errorMessage = e.str || e.message || '发生未知错误。';
        errorDiv.innerHTML = `<pre style="color:red;">${errorMessage}</pre>`;
        outputDiv.innerHTML = ''; // 清除任何部分渲染
    }
};
