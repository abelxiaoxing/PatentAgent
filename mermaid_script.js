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

            // 关键修复：对原始 SVG 字符串进行处理，确保其包含明确的 width 和 height 属性
            // 这有助于 Image 对象更可靠地加载 SVG。
            let svgForDownload = svg; // 从 mermaid.render 获取的原始 SVG 字符串
            try {
                const parser = new DOMParser();
                const doc = parser.parseFromString(svgForDownload, "image/svg+xml");
                const root = doc.documentElement;

                // 设置 width 和 height 属性
                root.setAttribute('width', svgWidth);
                root.setAttribute('height', svgHeight);

                // 序列化回字符串
                svgForDownload = new XMLSerializer().serializeToString(doc);
            } catch (e) {
                console.warn("Failed to add explicit width/height to SVG for download, using original SVG:", e);
                // 如果处理失败，回退到原始 SVG，但可能会再次遇到加载问题
            }

            const svgBlob = new Blob([svgForDownload], { type: 'image/svg+xml;charset=utf-8' });
            const url = URL.createObjectURL(svgBlob);

            const image = new Image();

            image.onload = () => {
                // 图片加载后，创建 canvas
                const canvas = document.createElement('canvas');
                const context = canvas.getContext('2d');

                // 为美观添加边距
                const margin = 20;
                
                // 使用加载后图像的自然尺寸，这是最可靠的尺寸获取方式
                const imgWidth = image.width;
                const imgHeight = image.height;

                canvas.width = imgWidth + margin * 2;
                canvas.height = imgHeight + margin * 2;

                // 用白色背景填充画布
                context.fillStyle = 'white';
                context.fillRect(0, 0, canvas.width, canvas.height);

                // 将图像绘制到画布上，并留出边距
                context.drawImage(image, margin, margin, imgWidth, imgHeight);

                // 触发下载
                const a = document.createElement('a');
                a.href = canvas.toDataURL('image/png');
                a.download = `${safeTitle || 'patent_drawing'}.png`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);

                // 清理 blob URL
                URL.revokeObjectURL(url);
            };

            image.onerror = (e) => {
                console.error("图像加载失败，无法转换为画布：", e);
                errorDiv.innerHTML = '<p style="color:red;">无法将图表转换为 PNG。图像加载失败。</p>';
                URL.revokeObjectURL(url);
            };

            image.src = url;
        };

    } catch (e) {
        console.error(`渲染 Mermaid 图表时出错，key 为 ${drawingKey}：`, e);
        const errorMessage = e.str || e.message || '发生未知错误。';
        errorDiv.innerHTML = `<pre style="color:red;">${errorMessage}</pre>`;
        outputDiv.innerHTML = ''; // 清除任何部分渲染
    }
};