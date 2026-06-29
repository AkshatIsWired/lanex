// toast.js — Simple toast notifications

export const toast = {
  container: null,
  init() {
    this.container = document.createElement("div");
    // Announce toasts to assistive tech (errors are assertive, the rest polite).
    this.container.setAttribute("role", "status");
    this.container.setAttribute("aria-live", "polite");
    this.container.style.cssText = `
      position: fixed;
      bottom: 20px;
      right: 20px;
      display: flex;
      flex-direction: column;
      gap: 10px;
      z-index: 9999;
    `;
    document.body.appendChild(this.container);
  },
  show(message, type = "info", duration = 3000) {
    if (!this.container) this.init();
    
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.textContent = message;
    
    // Inline styles for glassmorphism
    el.style.cssText = `
      background: var(--surface-2);
      border: 1px solid var(--border);
      border-left: 4px solid var(--${type === 'error' ? 'fail' : type === 'success' ? 'pass' : 'accent'});
      color: var(--text-strong);
      padding: 12px 20px;
      border-radius: var(--r-md);
      box-shadow: 0 10px 30px rgba(0,0,0,0.3);
      backdrop-filter: blur(12px);
      -webkit-backdrop-filter: blur(12px);
      font-size: var(--t-sm);
      transform: translateX(120%);
      opacity: 0;
      transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
    `;
    
    this.container.appendChild(el);
    
    // Trigger animation
    requestAnimationFrame(() => {
      el.style.transform = "translateX(0)";
      el.style.opacity = "1";
    });
    
    setTimeout(() => {
      el.style.transform = "translateX(120%)";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 300);
    }, duration);
  }
};
