/* Enhanced TRAINING ATLAS with dynamic SVG graphics and animations */
(() => {
  'use strict';

  const init = () => {
    const stage = document.querySelector('.atlas-stage');
    if (!stage || stage.querySelector('.atlas-svg-layer')) return;

    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
    if (reduced.matches) return;

    // Create SVG canvas for dynamic graphics
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('class', 'atlas-svg-layer');
    svg.setAttribute('aria-hidden', 'true');
    svg.setAttribute('focusable', 'false');
    svg.setAttribute('viewBox', '0 0 600 400');
    svg.setAttribute('preserveAspectRatio', 'xMidYMid slice');
    svg.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:0;';
    stage.appendChild(svg);

    // Defs for gradients and filters
    const defs = document.createElementNS('http://www.w3.org/2000/svg', 'defs');

    // Radial gradient for glow effects
    const glowGrad = document.createElementNS('http://www.w3.org/2000/svg', 'radialGradient');
    glowGrad.setAttribute('id', 'atlasGlow');
    glowGrad.innerHTML = `
      <stop offset="0%" style="stop-color:#245EC0;stop-opacity:0.8"/>
      <stop offset="100%" style="stop-color:#245EC0;stop-opacity:0"/>
    `;
    defs.appendChild(glowGrad);

    // Blur filter for soft edges
    const blur = document.createElementNS('http://www.w3.org/2000/svg', 'filter');
    blur.setAttribute('id', 'atlasBlur');
    blur.innerHTML = '<feGaussianBlur in="SourceGraphic" stdDeviation="2"/>';
    defs.appendChild(blur);

    svg.appendChild(defs);

    // Create orbital paths with particles
    const createOrbit = (cx, cy, rx, ry, rotation, particleCount, duration) => {
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('class', 'atlas-orbit-system');

      // Orbital path
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'ellipse');
      path.setAttribute('cx', cx);
      path.setAttribute('cy', cy);
      path.setAttribute('rx', rx);
      path.setAttribute('ry', ry);
      path.setAttribute('transform', `rotate(${rotation} ${cx} ${cy})`);
      path.setAttribute('fill', 'none');
      path.setAttribute('stroke', 'rgba(36,94,192,0.28)');
      path.setAttribute('stroke-width', '1');
      g.appendChild(path);

      // Particles on orbit
      for (let i = 0; i < particleCount; i++) {
        const angle = (i / particleCount) * Math.PI * 2;
        const x = cx + rx * Math.cos(angle);
        const y = cy + ry * Math.sin(angle);

        const particle = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
        particle.setAttribute('r', '2');
        particle.setAttribute('fill', 'url(#atlasGlow)');
        particle.setAttribute('filter', 'url(#atlasBlur)');

        const animateMotion = document.createElementNS('http://www.w3.org/2000/svg', 'animateMotion');
        animateMotion.setAttribute('dur', `${duration}s`);
        animateMotion.setAttribute('repeatCount', 'indefinite');
        animateMotion.setAttribute('begin', `${(i / particleCount) * duration}s`);
        animateMotion.setAttribute('path', `
          M ${cx - rx} ${cy}
          A ${rx} ${ry} ${rotation} 1 1 ${cx + rx} ${cy}
          A ${rx} ${ry} ${rotation} 1 1 ${cx - rx} ${cy}
        `);

        particle.appendChild(animateMotion);
        g.appendChild(particle);
      }

      return g;
    };

    // Add multiple orbital systems
    svg.appendChild(createOrbit(150, 200, 80, 120, 25, 4, 12));
    svg.appendChild(createOrbit(450, 180, 100, 60, -15, 3, 15));
    svg.appendChild(createOrbit(300, 250, 140, 80, 10, 5, 18));

    // Create floating energy nodes
    const createEnergyNode = (x, y, size, delay) => {
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('class', 'atlas-energy-node');

      // Outer glow
      const outer = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      outer.setAttribute('cx', x);
      outer.setAttribute('cy', y);
      outer.setAttribute('r', size * 2);
      outer.setAttribute('fill', 'url(#atlasGlow)');
      outer.setAttribute('opacity', '0.4');

      // Inner core
      const inner = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
      inner.setAttribute('cx', x);
      inner.setAttribute('cy', y);
      inner.setAttribute('r', size);
      inner.setAttribute('fill', '#245EC0');

      // Pulse animation
      const pulseOuter = document.createElementNS('http://www.w3.org/2000/svg', 'animate');
      pulseOuter.setAttribute('attributeName', 'r');
      pulseOuter.setAttribute('values', `${size * 2};${size * 2.5};${size * 2}`);
      pulseOuter.setAttribute('dur', '3s');
      pulseOuter.setAttribute('repeatCount', 'indefinite');
      pulseOuter.setAttribute('begin', `${delay}s`);
      outer.appendChild(pulseOuter);

      const pulseInner = document.createElementNS('http://www.w3.org/2000/svg', 'animate');
      pulseInner.setAttribute('attributeName', 'r');
      pulseInner.setAttribute('values', `${size};${size * 1.2};${size}`);
      pulseInner.setAttribute('dur', '3s');
      pulseInner.setAttribute('repeatCount', 'indefinite');
      pulseInner.setAttribute('begin', `${delay}s`);
      inner.appendChild(pulseInner);

      g.appendChild(outer);
      g.appendChild(inner);
      return g;
    };

    // Add energy nodes at strategic positions
    svg.appendChild(createEnergyNode(120, 80, 4, 0));
    svg.appendChild(createEnergyNode(480, 320, 5, 0.5));
    svg.appendChild(createEnergyNode(320, 150, 3, 1));

    // Create morphing blob background
    const createMorphingBlob = () => {
      const blob = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      blob.setAttribute('class', 'atlas-blob');
      blob.setAttribute('fill', 'rgba(36,94,192,0.12)');
      blob.setAttribute('filter', 'url(#atlasBlur)');

      const morphAnim = document.createElementNS('http://www.w3.org/2000/svg', 'animate');
      morphAnim.setAttribute('attributeName', 'd');
      morphAnim.setAttribute('values', `
        M400,200 Q500,100 500,200 T400,300 T300,200 Z;
        M400,200 Q500,150 480,250 T380,320 T320,200 Z;
        M400,200 Q480,120 520,220 T400,300 T300,200 Z;
        M400,200 Q500,100 500,200 T400,300 T300,200 Z
      `);
      morphAnim.setAttribute('dur', '20s');
      morphAnim.setAttribute('repeatCount', 'indefinite');

      blob.appendChild(morphAnim);
      return blob;
    };

    svg.appendChild(createMorphingBlob());

    // Create constellation connections (connecting energy nodes)
    const createConstellation = () => {
      const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
      g.setAttribute('class', 'atlas-constellation');

      const connections = [
        [120, 80, 320, 150],
        [320, 150, 480, 320],
        [480, 320, 120, 80]
      ];

      connections.forEach(([x1, y1, x2, y2], i) => {
        const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
        line.setAttribute('x1', x1);
        line.setAttribute('y1', y1);
        line.setAttribute('x2', x2);
        line.setAttribute('y2', y2);
        line.setAttribute('stroke', 'rgba(36,94,192,0.2)');
        line.setAttribute('stroke-width', '1');
        line.setAttribute('stroke-dasharray', '4 4');

        const dashAnim = document.createElementNS('http://www.w3.org/2000/svg', 'animate');
        dashAnim.setAttribute('attributeName', 'stroke-dashoffset');
        dashAnim.setAttribute('from', '0');
        dashAnim.setAttribute('to', '8');
        dashAnim.setAttribute('dur', '1s');
        dashAnim.setAttribute('repeatCount', 'indefinite');

        line.appendChild(dashAnim);
        g.appendChild(line);
      });

      return g;
    };

    svg.insertBefore(createConstellation(), svg.firstChild);

    // Keep continuous work local to this stage so it can pause off screen.
    let context;
    if (window.gsap) {
      context = window.gsap.context(() => {
      const gsap = window.gsap;

      // Score remains stable: no entry scale or continuous pulse.

      // Animate stage grid with stagger
      const gridItems = stage.querySelectorAll('.stage-grid i');
      if (gridItems.length) {
        gsap.from(gridItems, {
          scale: 0,
          opacity: 0,
          stagger: 0.05,
          duration: 0.6,
          ease: 'back.out(1.7)',
          delay: 0.3
        });
      }

      // Animate path nodes
      const pathNodes = stage.querySelectorAll('.stage-path span');
      if (pathNodes.length) {
        gsap.from(pathNodes, {
          scale: 0,
          opacity: 0,
          stagger: 0.1,
          duration: 0.5,
          ease: 'elastic.out(1, 0.5)',
          delay: 0.6
        });
      }

      // Floating animation for stage floats
      const floats = stage.querySelectorAll('.stage-float');
      floats.forEach((float, i) => {
        gsap.to(float, {
          y: '+=8',
          duration: 2 + i * 0.5,
          repeat: -1,
          yoyo: true,
          ease: 'sine.inOut'
        });

        gsap.to(float, {
          rotation: i % 2 ? 2 : -2,
          duration: 3,
          repeat: -1,
          yoyo: true,
          ease: 'sine.inOut'
        });
      });

      // Orbits rotation
      const orbits = stage.querySelectorAll('.stage-orbit');
      orbits.forEach((orbit, i) => {
        gsap.to(orbit, {
          rotation: 360,
          duration: 20 + i * 5,
          repeat: -1,
          ease: 'none',
          transformOrigin: 'center center'
        });
      });
      }, stage);
    }
    let visible = false;
    const sync = () => {
      const active = visible && !document.hidden && !reduced.matches;
      if (active) svg.unpauseAnimations(); else svg.pauseAnimations();
      context?.getTweens().forEach(tween => tween.paused(!active));
    };
    new IntersectionObserver(entries => {visible = entries[0].isIntersecting; sync();}).observe(stage);
    document.addEventListener('visibilitychange', sync);
    reduced.addEventListener('change', () => {
      if (reduced.matches) {context?.revert(); svg.remove();} else init();
    });
    sync();
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init, { once: true });
  } else {
    init();
  }
})();
