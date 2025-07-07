window.renderMermaid = (drawingKey, safeTitle, code) => {
    const pngFileName = `${safeTitle || `drawing_${drawingKey}`}.png`;
    
    const outputDiv = document.getElementById(`mermaid-output-${drawingKey}`);
    const downloadBtn = document.getElementById(`download-btn-${drawingKey}`);

    if (!code || !outputDiv || !downloadBtn) {
        console.error("Mermaid script: Missing required elements or code.", { drawingKey, code, outputDiv, downloadBtn });
        if(outputDiv) outputDiv.innerHTML = "<pre style='color: red;'>Error: Missing required elements for rendering.</pre>";
        return;
    }

    const renderDiagram = async () => {
        try {
            // Initialize mermaid for each render to apply theme correctly
            mermaid.initialize({ startOnLoad: false, theme: 'neutral' });
            const { svg } = await mermaid.render(`mermaid-svg-${drawingKey}`, code);
            outputDiv.innerHTML = svg;
        } catch (e) {
            outputDiv.innerHTML = `<pre style="color: red;">Error rendering diagram:\n${e.message}</pre>`;
            console.error("Mermaid render error:", e);
        }
    };

    const downloadPNG = async () => {
        try {
            const svgElement = outputDiv.querySelector('svg');
            if (!svgElement) {
                alert("Diagram not rendered yet.");
                return;
            }
            
            // Ensure the downloaded PNG background is white
            svgElement.style.backgroundColor = 'white';

            const svgData = new XMLSerializer().serializeToString(svgElement);
            const img = new Image();
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');

            img.onload = function() {
                const scale = 2;
                const viewBox = svgElement.viewBox.baseVal;
                const width = viewBox.width;
                const height = viewBox.height;
                
                canvas.width = width * scale;
                canvas.height = height * scale;
                
                ctx.fillStyle = 'white';
                ctx.fillRect(0, 0, canvas.width, canvas.height);
                
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
                
                const pngFile = canvas.toDataURL('image/png');
                const downloadLink = document.createElement('a');
                downloadLink.download = pngFileName;
                downloadLink.href = pngFile;
                document.body.appendChild(downloadLink);
                downloadLink.click();
                document.body.removeChild(downloadLink);
            };
            // Use btoa to handle unicode characters correctly
            img.src = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svgData)))}`;
        } catch (e) {
            console.error("Download failed:", e);
            alert(`Failed to generate PNG: ${e.message}`);
        }
    };

    renderDiagram();
    // Remove old listener to prevent multiple downloads
    const newDownloadBtn = downloadBtn.cloneNode(true);
    downloadBtn.parentNode.replaceChild(newDownloadBtn, downloadBtn);
    newDownloadBtn.addEventListener('click', downloadPNG);
};