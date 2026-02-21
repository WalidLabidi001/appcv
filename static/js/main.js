document.addEventListener('DOMContentLoaded', () => {
    // ── Navigation Scroll Effect ──
    const nav = document.getElementById('main-nav');
    window.addEventListener('scroll', () => {
        if (window.scrollY > 20) {
            nav.querySelector('.absolute').classList.add('bg-surface-950/95');
            nav.querySelector('.absolute').classList.remove('bg-surface-950/80');
        } else {
            nav.querySelector('.absolute').classList.remove('bg-surface-950/95');
            nav.querySelector('.absolute').classList.add('bg-surface-950/80');
        }
    });

    // ── Mobile Menu Toggle ──
    const menuBtn = document.getElementById('mobile-menu-btn');
    const mobileMenu = document.getElementById('mobile-menu');
    if (menuBtn && mobileMenu) {
        menuBtn.addEventListener('click', () => {
            mobileMenu.classList.toggle('hidden');
            const spans = menuBtn.querySelectorAll('span');
            spans[0].classList.toggle('rotate-45');
            spans[0].classList.toggle('translate-y-1.5');
            spans[1].classList.toggle('opacity-0');
            spans[2].classList.toggle('-rotate-45');
            spans[2].classList.toggle('-translate-y-1.5');
            spans[2].classList.toggle('w-5');
            spans[2].classList.toggle('w-3.5');
        });
    }

    // ── Flash Messages Auto-dismiss ──
    const flashMessages = document.querySelectorAll('.flash-message');
    flashMessages.forEach(msg => {
        setTimeout(() => {
            msg.classList.add('opacity-0', '-translate-y-4');
            msg.style.transition = 'all 0.5s ease-out';
            setTimeout(() => msg.remove(), 500);
        }, 5000);
    });

    // ── Input Focus Effects ──
    const inputs = document.querySelectorAll('input, textarea');
    inputs.forEach(input => {
        input.addEventListener('focus', () => {
            input.parentElement.classList.add('ring-2', 'ring-brand-500/20');
        });
        input.addEventListener('blur', () => {
            input.parentElement.classList.remove('ring-2', 'ring-brand-500/20');
        });
    });
});
