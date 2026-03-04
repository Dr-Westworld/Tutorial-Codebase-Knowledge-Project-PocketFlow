// DOM Elements
const sourceTypeRadios = document.querySelectorAll('input[name="sourceType"]');
const githubInput = document.getElementById('githubInput');
const localInput = document.getElementById('localInput');
const repoUrl = document.getElementById('repoUrl');
const localPath = document.getElementById('localPath');
const includePatterns = document.getElementById('includePatterns');
const excludePatterns = document.getElementById('excludePatterns');
const maxSize = document.getElementById('maxSize');
const language = document.getElementById('language');
const disableCache = document.getElementById('disableCache');
const processBtn = document.getElementById('processBtn');
const tutorialsList = document.getElementById('tutorialsList');
const statusMessage = document.getElementById('statusMessage');
const loadingSpinner = document.getElementById('loadingSpinner');

// Event Listeners
sourceTypeRadios.forEach(radio => {
    radio.addEventListener('change', (e) => {
        if (e.target.value === 'github') {
            githubInput.classList.remove('hidden');
            githubInput.classList.add('visible');
            localInput.classList.add('hidden');
            localInput.classList.remove('visible');
        } else {
            localInput.classList.remove('hidden');
            localInput.classList.add('visible');
            githubInput.classList.add('hidden');
            githubInput.classList.remove('visible');
        }
    });
});

// Initialize on page load
document.addEventListener('DOMContentLoaded', () => {
    loadTutorials();
});

// Process Repository
async function processRepository() {
    const sourceType = document.querySelector('input[name="sourceType"]:checked').value;
    const source = sourceType === 'github' ? repoUrl.value : localPath.value;

    // Validation
    if (!source.trim()) {
        showStatus('Please enter a source (GitHub URL or local path)', 'error');
        return;
    }

    if (sourceType === 'github' && !isValidGitHubUrl(source)) {
        showStatus('Please enter a valid GitHub URL', 'error');
        return;
    }

    if (sourceType === 'local' && !isValidLocalPath(source)) {
        showStatus('Please enter a valid local directory path', 'error');
        return;
    }

    // Show loading
    showLoading(true);
    processBtn.disabled = true;

    try {
        const payload = {
            sourceType: sourceType,
            source: source,
            include: includePatterns.value.trim(),
            exclude: excludePatterns.value.trim(),
            maxSize: parseInt(maxSize.value) || 100000,
            language: language.value,
            disableCache: disableCache.checked
        };

        const response = await fetch('/api/process', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Processing failed');
        }

        showStatus('Tutorial generated successfully!', 'success');
        await loadTutorials();
        // Don't clear the form on success - user might want to try another repo
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    } finally {
        showLoading(false);
        processBtn.disabled = false;
    }
}

// Load and Display Tutorials
async function loadTutorials() {
    try {
        const response = await fetch('/api/tutorials');
        const data = await response.json();

        if (data.tutorials.length === 0) {
            tutorialsList.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-inbox"></i>
                    <p>No tutorials generated yet</p>
                    <small>Generate a tutorial to see it here</small>
                </div>
            `;
            return;
        }

        tutorialsList.innerHTML = data.tutorials.map(tutorial => `
            <div class="tutorial-card">
                <div class="tutorial-header">
                    <div class="tutorial-title">
                        <i class="fas fa-book"></i>
                        <h3>${tutorial.display_name}</h3>
                    </div>
                    <span class="tutorial-badge">${tutorial.file_count} files</span>
                </div>
                <div class="tutorial-files">
                    ${tutorial.files.map(file => `
                        <a href="/tutorial/${tutorial.name}/${file.path}"
                        // <a href="/tutorial/${tutorial.name}/${file.path.replace('.md', '')}"
                           target="_blank"
                           class="file-link">
                            <i class="fas fa-file-pdf"></i>
                            <span>${file.display_name}</span>
                        </a>
                    `).join('')}
                </div>
            </div>
        `).join('');
    } catch (error) {
        console.error('Failed to load tutorials:', error);
        tutorialsList.innerHTML = `
            <div class="empty-state">
                <i class="fas fa-exclamation-circle"></i>
                <p>Failed to load tutorials</p>
            </div>
        `;
    }
}

// Display Status Message
function showStatus(message, type) {
    statusMessage.textContent = message;
    statusMessage.className = `status-message ${type} visible`;

    // Auto-hide after 5 seconds
    setTimeout(() => {
        statusMessage.classList.remove('visible');
    }, 5000);
}

// Show/Hide Loading Spinner
function showLoading(show) {
    if (show) {
        loadingSpinner.classList.add('visible');
    } else {
        loadingSpinner.classList.remove('visible');
    }
}

// Clear Form
function clearForm() {
    repoUrl.value = '';
    localPath.value = '';
    includePatterns.value = '';
    excludePatterns.value = '';
    maxSize.value = '100000';
    language.value = 'english';
    disableCache.checked = false;
    statusMessage.classList.remove('visible');
}

// Validation Functions
function isValidGitHubUrl(url) {
    url = url.trim();
    // Check if it's a valid GitHub URL format
    const githubRegex = /^(https?:\/\/)?(www\.)?(github\.com\/)?[\w-]+\/[\w-]+\/?$/i;
    return githubRegex.test(url);
}

function isValidLocalPath(path) {
    // Simple validation - just check it's not empty and looks like a path
    return path.trim().length > 0 && (path.includes('/') || path.includes('\\'));
}

// Real-time tutorial list updates
setInterval(() => {
    if (document.hidden === false) {
        loadTutorials();
    }
}, 5000); // Check every 5 seconds when tab is visible

// Keyboard shortcuts
document.addEventListener('keydown', (e) => {
    // Ctrl+Enter or Cmd+Enter to submit
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        if (!processBtn.disabled) {
            processRepository();
        }
    }

    // Ctrl+L or Cmd+L to clear
    if ((e.ctrlKey || e.metaKey) && e.key === 'l') {
        e.preventDefault();
        clearForm();
    }
});

// Handle visibility change to refresh tutorials when tab becomes active
document.addEventListener('visibilitychange', () => {
    if (!document.hidden) {
        loadTutorials();
    }
});
