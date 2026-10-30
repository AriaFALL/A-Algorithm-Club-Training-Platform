/**
 * GSAP 全局配置与插件注册
 * 算法社团训练台 UI 动画系统
 */

// 检查用户是否偏好减少动画
const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

// GSAP 全局默认配置
gsap.config({
  nullTargetWarn: false,
  force3D: true  // 强制 GPU 加速
});

// 根据用户偏好设置动画时长
gsap.defaults({
  duration: prefersReducedMotion ? 0.01 : 0.6,
  ease: prefersReducedMotion ? 'none' : 'power2.out'
});

// 标准动画时长
const DURATIONS = {
  instant: 0.1,
  fast: 0.2,
  normal: 0.4,
  slow: 0.6,
  verySlow: 1.2
};

// 标准缓动曲线
const EASINGS = {
  smooth: 'power2.out',
  smoothIn: 'power2.in',
  smoothInOut: 'power2.inOut',
  bounce: 'back.out(1.7)',
  bounceStrong: 'back.out(2)',
  elastic: 'elastic.out(1, 0.5)',
  snap: 'power3.inOut'
};

// 导出配置供其他模块使用
window.AnimationConfig = {
  prefersReducedMotion,
  DURATIONS,
  EASINGS
};

console.log('✨ GSAP Animation System initialized');
