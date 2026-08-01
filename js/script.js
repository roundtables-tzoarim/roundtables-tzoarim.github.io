// אנימציית הופעה קלה בגלילה. רץ גם ב-DOMContentLoaded וגם אחרי טעינת התוכן
// הדינמי מ-content.json (אירוע "content-rendered" שנשלח ע"י content-loader.js).

let observer;

function observeFadeTargets() {
  if (!observer) {
    observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("in-view");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.15 }
    );
  }

  document.querySelectorAll(".article-card, .discussion-box, .media-wrapper, .audio-wrapper").forEach((el) => {
    if (el.dataset.fadeBound) return;
    el.dataset.fadeBound = "1";
    el.classList.add("fade-init");
    observer.observe(el);
  });
}

document.addEventListener("DOMContentLoaded", observeFadeTargets);
document.addEventListener("content-rendered", observeFadeTargets);
