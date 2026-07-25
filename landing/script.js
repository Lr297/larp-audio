const DOWNLOADS = {
    macos: "../release/0.1.0/LARP-Audio-macOS-arm64.dmg",
    windows: "../release/0.1.0/LARP-Audio-Windows-x64-Setup.exe"
};

document.addEventListener('DOMContentLoaded', () => {
    setupDownloads();
    setupMouseGlow();
    setupScrollReveal();
});

function setupDownloads() {
    const btnMac = document.getElementById('btn-macos');
    const btnWin = document.getElementById('btn-windows');
    const msgElement = document.getElementById('download-message');

    function isUrlValid(url) {
        if (!url) return false;
        if (url === "MACOS_DOWNLOAD_URL" || url === "WINDOWS_DOWNLOAD_URL") return false;
        return true;
    }

    function configureButton(btn, platform, emptyMessage, downloadName) {
        if (!btn) return;
        
        const url = DOWNLOADS[platform];
        
        if (isUrlValid(url)) {
            btn.href = url;
            if (downloadName) {
                btn.setAttribute("download", downloadName);
            }
            // Explicitly force navigation to bypass local file:// block on `<a download>`
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                window.location.href = url;
            });
        } else {
            btn.href = "#";
            btn.addEventListener('click', (e) => {
                e.preventDefault();
                msgElement.textContent = emptyMessage;
                msgElement.style.opacity = "1";
                setTimeout(() => {
                    msgElement.style.opacity = "0";
                }, 3000);
            });
        }
    }

    configureButton(btnMac, 'macos', 'macOS download link not configured yet', 'LARP-Audio-macOS-arm64.dmg');
    configureButton(btnWin, 'windows', 'Windows version is being prepared', 'LARP-Audio-Windows-x64-Setup.exe');
}

function setupMouseGlow() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;

    const glow = document.getElementById('mouseGlow');
    const heroSection = document.querySelector('.hero');
    
    if (!glow || !heroSection) return;

    let isMouseOver = false;
    let targetX = 0, targetY = 0;
    let currentX = 0, currentY = 0;

    heroSection.addEventListener('mousemove', (e) => {
        isMouseOver = true;
        targetX = e.clientX;
        targetY = e.clientY;
        glow.style.opacity = '0.8';
    });

    heroSection.addEventListener('mouseleave', () => {
        isMouseOver = false;
        glow.style.opacity = '0';
    });

    function renderGlow() {
        if (isMouseOver) {
            // Smooth easing for performance and feeling
            currentX += (targetX - currentX) * 0.1;
            currentY += (targetY - currentY) * 0.1;
            glow.style.left = `${currentX}px`;
            glow.style.top = `${currentY}px`;
        }
        requestAnimationFrame(renderGlow);
    }
    
    requestAnimationFrame(renderGlow);
}

function setupScrollReveal() {
    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (prefersReducedMotion) return;

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.classList.add('visible');
                observer.unobserve(entry.target);
            }
        });
    }, {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    });

    document.querySelectorAll('.scroll-reveal').forEach((el) => {
        observer.observe(el);
    });
}
