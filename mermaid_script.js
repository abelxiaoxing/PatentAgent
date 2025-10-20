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
            // 获取当前渲染的 SVG 元素的实际尺寸
            const svgElement = outputDiv.querySelector('svg');
            if (!svgElement) {
                console.error("Download failed: SVG element not found for sizing.");
                errorDiv.innerHTML = '<p style="color:red;">无法找到要下载的图表 SVG 元素。</p>';
                return;
            }
            const svgWidth = svgElement.getBoundingClientRect().width;
            const svgHeight = svgElement.getBoundingClientRect().height;

            // 对原始 SVG 字符串进行处理，确保其包含明确的 width 和 height 属性
            let svgForDownload = svg; // 从 mermaid.render 获取的原始 SVG 字符串
            try {
                const parser = new DOMParser();
                const doc = parser.parseFromString(svgForDownload, "image/svg+xml");
                const root = doc.documentElement;
                root.setAttribute('width', svgWidth);
                root.setAttribute('height', svgHeight);
                svgForDownload = new XMLSerializer().serializeToString(doc);
            } catch (e) {
                console.warn("Failed to add explicit width/height to SVG for download, using original SVG:", e);
            }

            // 哈雷酱的绝对可靠PNG方案：只要PNG！绝对不降级！
            const downloadPNG = () => {
                console.log("🚀 开始PNG下载流程 - 绝对只要PNG！");

                // 获取渲染的SVG元素
                const svgElement = outputDiv.querySelector('svg');
                if (!svgElement) {
                    errorDiv.innerHTML = '<p style="color:red;">❌ 找不到SVG元素</p>';
                    return;
                }

                // 获取准确的尺寸
                const svgRect = svgElement.getBoundingClientRect();
                const width = Math.ceil(svgRect.width) || 800;
                const height = Math.ceil(svgRect.height) || 600;
                const margin = 20;
                const canvasWidth = width + margin * 2;
                const canvasHeight = height + margin * 2;

                console.log(`📐 SVG尺寸: ${width}x${height}, Canvas尺寸: ${canvasWidth}x${canvasHeight}`);

                // 更新状态显示
                errorDiv.innerHTML = '<p style="color:blue;">🔄 正在生成PNG图片...</p>';

                // 方法1: 克隆DOM中的SVG元素（最可靠的方法）
                const method1_CloneSVG = () => {
                    return new Promise((resolve, reject) => {
                        try {
                            console.log("📋 方法1: 克隆DOM中的SVG元素");

                            // 克隆SVG元素及其所有内容
                            const clonedSVG = svgElement.cloneNode(true);

                            // 确保所有必要的属性
                            clonedSVG.setAttribute('width', width);
                            clonedSVG.setAttribute('height', height);
                            clonedSVG.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
                            clonedSVG.setAttribute('xmlns:xlink', 'http://www.w3.org/1999/xlink');

                            // 设置viewBox以确保缩放正确
                            if (!clonedSVG.hasAttribute('viewBox')) {
                                clonedSVG.setAttribute('viewBox', `0 0 ${width} ${height}`);
                            }

                            // 序列化为字符串
                            const svgString = new XMLSerializer().serializeToString(clonedSVG);
                            console.log("📄 SVG字符串长度:", svgString.length);

                            // 创建Blob和URL
                            const blob = new Blob([svgString], {
                                type: 'image/svg+xml;charset=utf-8'
                            });
                            const url = URL.createObjectURL(blob);

                            // 创建Image对象
                            const img = new Image();

                            img.onload = () => {
                                try {
                                    console.log("✅ SVG图片加载成功");
                                    const canvas = document.createElement('canvas');
                                    const ctx = canvas.getContext('2d');

                                    canvas.width = canvasWidth;
                                    canvas.height = canvasHeight;

                                    // 白色背景
                                    ctx.fillStyle = 'white';
                                    ctx.fillRect(0, 0, canvasWidth, canvasHeight);

                                    // 绘制SVG到Canvas
                                    ctx.drawImage(img, margin, margin, width, height);
                                    URL.revokeObjectURL(url);

                                    // 导出为PNG
                                    const pngUrl = canvas.toDataURL('image/png', 1.0);
                                    resolve(pngUrl);
                                } catch (e) {
                                    URL.revokeObjectURL(url);
                                    console.error("❌ Canvas绘制失败:", e);
                                    reject(e);
                                }
                            };

                            img.onerror = (e) => {
                                URL.revokeObjectURL(url);
                                console.error("❌ SVG图片加载失败:", e);
                                reject(new Error('SVG图片加载失败'));
                            };

                            // 重要：设置src以确保触发加载
                            img.src = url;

                        } catch (e) {
                            console.error("❌ 方法1执行失败:", e);
                            reject(e);
                        }
                    });
                };

                // 方法2: 使用mermaid原始输出SVG字符串
                const method2_UseOriginalSVG = () => {
                    return new Promise((resolve, reject) => {
                        try {
                            console.log("📝 方法2: 使用mermaid原始SVG字符串");

                            let cleanSVG = svgForDownload;

                            // 确保基本命名空间
                            if (!cleanSVG.includes('xmlns=')) {
                                cleanSVG = cleanSVG.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"');
                            }

                            // 确保尺寸属性
                            if (!cleanSVG.includes('width=')) {
                                cleanSVG = cleanSVG.replace('<svg', `<svg width="${width}"`);
                            }
                            if (!cleanSVG.includes('height=')) {
                                cleanSVG = cleanSVG.replace('<svg', `<svg height="${height}"`);
                            }
                            if (!cleanSVG.includes('viewBox=')) {
                                cleanSVG = cleanSVG.replace('<svg', ` viewBox="0 0 ${width} ${height}"`);
                            }

                            console.log("🔧 清理后的SVG长度:", cleanSVG.length);

                            const blob = new Blob([cleanSVG], {
                                type: 'image/svg+xml;charset=utf-8'
                            });
                            const url = URL.createObjectURL(blob);

                            const img = new Image();

                            img.onload = () => {
                                try {
                                    console.log("✅ 原始SVG图片加载成功");
                                    const canvas = document.createElement('canvas');
                                    const ctx = canvas.getContext('2d');

                                    canvas.width = canvasWidth;
                                    canvas.height = canvasHeight;

                                    ctx.fillStyle = 'white';
                                    ctx.fillRect(0, 0, canvasWidth, canvasHeight);
                                    ctx.drawImage(img, margin, margin, width, height);
                                    URL.revokeObjectURL(url);

                                    const pngUrl = canvas.toDataURL('image/png', 1.0);
                                    resolve(pngUrl);
                                } catch (e) {
                                    URL.revokeObjectURL(url);
                                    reject(e);
                                }
                            };

                            img.onerror = (e) => {
                                URL.revokeObjectURL(url);
                                console.error("❌ 原始SVG图片加载失败:", e);
                                reject(new Error('原始SVG图片加载失败'));
                            };

                            img.src = url;

                        } catch (e) {
                            console.error("❌ 方法2执行失败:", e);
                            reject(e);
                        }
                    });
                };

                // 方法3: Data URI方法（避免Blob URL问题）
                const method3_DataURI = () => {
                    return new Promise((resolve, reject) => {
                        try {
                            console.log("🔗 方法3: 使用Data URI");

                            let cleanSVG = svgForDownload;

                            // 基本清理
                            if (!cleanSVG.includes('xmlns=')) {
                                cleanSVG = cleanSVG.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"');
                            }
                            if (!cleanSVG.includes('width=')) {
                                cleanSVG = cleanSVG.replace('<svg', `<svg width="${width}"`);
                            }
                            if (!cleanSVG.includes('height=')) {
                                cleanSVG = cleanSVG.replace('<svg', `<svg height="${height}"`);
                            }

                            // 转换为Base64 Data URI
                            const base64 = btoa(unescape(encodeURIComponent(cleanSVG)));
                            const dataUri = `data:image/svg+xml;base64,${base64}`;

                            const img = new Image();

                            img.onload = () => {
                                try {
                                    console.log("✅ Data URI图片加载成功");
                                    const canvas = document.createElement('canvas');
                                    const ctx = canvas.getContext('2d');

                                    canvas.width = canvasWidth;
                                    canvas.height = canvasHeight;

                                    ctx.fillStyle = 'white';
                                    ctx.fillRect(0, 0, canvasWidth, canvasHeight);
                                    ctx.drawImage(img, margin, margin, width, height);

                                    const pngUrl = canvas.toDataURL('image/png', 1.0);
                                    resolve(pngUrl);
                                } catch (e) {
                                    reject(e);
                                }
                            };

                            img.onerror = (e) => {
                                console.error("❌ Data URI图片加载失败:", e);
                                reject(new Error('Data URI图片加载失败'));
                            };

                            img.src = dataUri;

                        } catch (e) {
                            console.error("❌ 方法3执行失败:", e);
                            reject(e);
                        }
                    });
                };

                // 方法4: 最后的备用方案 - 直接Canvas绘制
                const method4_DirectCanvas = () => {
                    return new Promise((resolve, reject) => {
                        try {
                            console.log("🎨 方法4: 直接Canvas绘制");

                            const canvas = document.createElement('canvas');
                            const ctx = canvas.getContext('2d');

                            canvas.width = canvasWidth;
                            canvas.height = canvasHeight;

                            // 白色背景
                            ctx.fillStyle = 'white';
                            ctx.fillRect(0, 0, canvasWidth, canvasHeight);

                            // 尝试获取SVG的HTML内容并直接绘制
                            const svgHTML = svgElement.outerHTML;

                            // 创建一个临时的Image来尝试渲染
                            const img = new Image();
                            const blob = new Blob([svgHTML], { type: 'image/svg+xml' });
                            const url = URL.createObjectURL(blob);

                            img.onload = () => {
                                try {
                                    ctx.drawImage(img, margin, margin, width, height);
                                    URL.revokeObjectURL(url);
                                    const pngUrl = canvas.toDataURL('image/png', 0.9);
                                    resolve(pngUrl);
                                } catch (e) {
                                    URL.revokeObjectURL(url);
                                    reject(e);
                                }
                            };

                            img.onerror = () => {
                                URL.revokeObjectURL(url);
                                reject(new Error('直接Canvas绘制失败'));
                            };

                            img.src = url;

                        } catch (e) {
                            console.error("❌ 方法4执行失败:", e);
                            reject(e);
                        }
                    });
                };

                // 按顺序尝试所有方法
                const tryAllMethods = async () => {
                    const methods = [
                        { name: '克隆SVG', fn: method1_CloneSVG },
                        { name: '原始SVG', fn: method2_UseOriginalSVG },
                        { name: 'Data URI', fn: method3_DataURI },
                        { name: '直接Canvas', fn: method4_DirectCanvas }
                    ];

                    for (let i = 0; i < methods.length; i++) {
                        const method = methods[i];
                        try {
                            console.log(`🔄 尝试方法${i + 1}: ${method.name}`);
                            errorDiv.innerHTML = `<p style="color:blue;">🔄 尝试方法${i + 1}: ${method.name}...</p>`;

                            const pngUrl = await method.fn();
                            console.log(`🎉 方法${i + 1}成功！`);

                            // 下载PNG文件
                            const a = document.createElement('a');
                            a.href = pngUrl;
                            a.download = `${safeTitle || 'patent_drawing'}.png`;
                            a.style.display = 'none';
                            document.body.appendChild(a);
                            a.click();
                            document.body.removeChild(a);

                            errorDiv.innerHTML = '<p style="color:green;">✅ PNG下载成功！</p>';
                            return pngUrl;

                        } catch (error) {
                            console.warn(`❌ 方法${i + 1}失败:`, error.message);

                            if (i === methods.length - 1) {
                                // 所有方法都失败了
                                throw new Error(`所有PNG转换方法都失败了。最后错误: ${error.message}`);
                            }
                        }
                    }
                };

                // 执行下载流程
                tryAllMethods().catch(error => {
                    console.error("💥 所有PNG转换方法都失败了:", error);
                    errorDiv.innerHTML = `
                        <div style="color:red; padding: 15px; border-radius: 8px; background-color: #ffe6e6; border: 2px solid #ff0000;">
                            <h4 style="margin: 0 0 10px 0;">❌ PNG转换失败</h4>
                            <p style="margin: 5px 0; font-size: 0.9em;">
                                <strong>错误信息:</strong> ${error.message}
                            </p>
                            <p style="margin: 5px 0; font-size: 0.9em;">
                                <strong>建议:</strong>
                            </p>
                            <ul style="margin: 5px 0; padding-left: 20px; font-size: 0.9em;">
                                <li>刷新页面重新生成图表</li>
                                <li>检查图表是否过于复杂</li>
                                <li>尝试使用不同的浏览器</li>
                                <li>联系开发者报告此问题</li>
                            </ul>
                        </div>
                    `;
                });
            };

            // 执行PNG下载 - 绝对只要PNG！
            downloadPNG();
        };

    } catch (e) {
        console.error(`渲染 Mermaid 图表时出错，key 为 ${drawingKey}：`, e);
        const errorMessage = e.str || e.message || '发生未知错误。';
        errorDiv.innerHTML = `<pre style="color:red;">${errorMessage}</pre>`;
        outputDiv.innerHTML = ''; // 清除任何部分渲染
    }
};