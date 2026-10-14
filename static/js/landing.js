(() => {
  const progress = document.getElementById("landingProgress");
  let progressFrame = 0;
  const updateProgress = () => {
    progressFrame = 0;
    const scrollable = document.documentElement.scrollHeight - window.innerHeight;
    const ratio = scrollable > 0 ? Math.min(1, window.scrollY / scrollable) : 0;
    progress?.style.setProperty("--landing-progress", String(ratio));
  };
  const scheduleProgress = () => {
    if (!progressFrame) progressFrame = window.requestAnimationFrame(updateProgress);
  };
  window.addEventListener("scroll", scheduleProgress, { passive: true });
  window.addEventListener("resize", scheduleProgress, { passive: true });
  updateProgress();

  const navigationLinks = [...document.querySelectorAll('.showcase-links a[href^="#"]')];
  const linkBySection = new Map();
  navigationLinks.forEach((link) => {
    const section = document.querySelector(link.getAttribute("href"));
    if (section) linkBySection.set(section, link);
  });
  const setActiveNavigation = (activeLink) => {
    navigationLinks.forEach((link) => {
      const active = link === activeLink;
      link.classList.toggle("is-active", active);
      if (active) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
  };
  if ("IntersectionObserver" in window) {
    const sectionObserver = new IntersectionObserver((entries) => {
      const visible = entries
        .filter((entry) => entry.isIntersecting)
        .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
      if (visible) setActiveNavigation(linkBySection.get(visible.target));
    }, { rootMargin: "-15% 0px -65%", threshold: [0, 0.15, 0.4] });
    linkBySection.forEach((_link, section) => sectionObserver.observe(section));
  }
  navigationLinks.forEach((link) => link.addEventListener("click", () => setActiveNavigation(link)));

  const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const revealElements = document.querySelectorAll("[data-reveal]");
  if (prefersReducedMotion || !("IntersectionObserver" in window)) {
    revealElements.forEach((element) => element.classList.add("is-visible"));
  } else {
    document.body.classList.add("reveal-ready");
    const revealObserver = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("is-visible");
        revealObserver.unobserve(entry.target);
      });
    }, { rootMargin: "120px 0px", threshold: 0.05 });
    revealElements.forEach((element) => revealObserver.observe(element));
  }

  const carousel = document.getElementById("serviceCarousel");
  if (!carousel) return;
  const cards = [...carousel.querySelectorAll("article")];
  let carouselTimer = 0;
  let centerFrame = 0;
  const updateCenteredService = () => {
    centerFrame = 0;
    const carouselBox = carousel.getBoundingClientRect();
    const center = carouselBox.left + carouselBox.width / 2;
    let centeredCard = cards[0];
    let nearestDistance = Number.POSITIVE_INFINITY;
    cards.forEach((card) => {
      const box = card.getBoundingClientRect();
      const distance = Math.abs(box.left + box.width / 2 - center);
      if (distance < nearestDistance) {
        nearestDistance = distance;
        centeredCard = card;
      }
    });
    cards.forEach((card) => {
      const active = card === centeredCard;
      card.classList.toggle("is-centered", active);
      if (active) card.setAttribute("aria-current", "true");
      else card.removeAttribute("aria-current");
    });
  };
  const scheduleCenteredService = () => {
    if (!centerFrame) centerFrame = window.requestAnimationFrame(updateCenteredService);
  };
  carousel.addEventListener("scroll", scheduleCenteredService, { passive: true });
  window.addEventListener("resize", scheduleCenteredService, { passive: true });

  const scrollServices = (direction) => {
    const firstCard = cards[0];
    if (!firstCard) return;
    carousel.scrollBy({
      left: (firstCard.getBoundingClientRect().width + 18) * direction,
      behavior: prefersReducedMotion ? "auto" : "smooth",
    });
  };
  const stopCarousel = () => window.clearInterval(carouselTimer);
  const advanceServices = () => {
    const reachedEnd = carousel.scrollLeft + carousel.clientWidth >= carousel.scrollWidth - 8;
    if (reachedEnd) carousel.scrollTo({ left: 0, behavior: "smooth" });
    else scrollServices(1);
  };
  const startCarousel = () => {
    stopCarousel();
    if (prefersReducedMotion || document.hidden) return;
    carouselTimer = window.setInterval(advanceServices, 6000);
  };
  document.querySelector("[data-service-previous]")?.addEventListener("click", () => {
    scrollServices(-1);
    startCarousel();
  });
  document.querySelector("[data-service-next]")?.addEventListener("click", () => {
    scrollServices(1);
    startCarousel();
  });
  carousel.addEventListener("pointerenter", stopCarousel);
  carousel.addEventListener("pointerleave", startCarousel);
  carousel.addEventListener("focusin", stopCarousel);
  carousel.addEventListener("focusout", startCarousel);
  document.addEventListener("visibilitychange", startCarousel);
  updateCenteredService();
  startCarousel();
})();
