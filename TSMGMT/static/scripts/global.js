window.addEventListener('load', function () {
    var overlay = document.getElementById('loading-overlay');
    if (overlay) overlay.style.display = 'none';
});

// Optionally: re-show the overlay on internal link clicks
document.addEventListener('DOMContentLoaded', function () {
    var overlay = document.getElementById('loading-overlay');
    document.querySelectorAll('a.js-block-ui').forEach(function (a) {
        a.addEventListener('click', function () {
            if (overlay) overlay.style.display = 'flex';
        });
    });
});
