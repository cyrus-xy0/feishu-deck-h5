// audits.js — 统一校验引擎 · 单规则源 (UNIFY-VALIDATE-ARCH-2026-06-03, 步骤 2)
// ---------------------------------------------------------------------------
// 设计:所有规则都是"对渲染后 DOM 求值的函数"。每条规则 =
//   { id, severity, evaluate(slide, ctx) -> findings[] }
// 注入到 headless 浏览器里渲染好的 deck,返回一份扁平 findings 列表(每条自带
// rule/severity/slide_idx/message),不再分 static/visual 两套注册表、两种语言。
// 调速靠 scope(只算改动的几帧 vs 全 deck),由 runner(run-audits.py)传入。
//
// 步骤 2 只迁一条做验证闭环:R-VIS-CANVAS-CENTER —— 几何从 visual-audit.js 的
// `canvas_center` producer 逐字移植,finding 文案从 validate.py 的消费段并进来,
// 规则逻辑 + 文案首次合到一处(以前几何在 JS、文案在 Python)。后续步骤逐条迁入
// 此文件,改规则永远只动这一个文件。
//
// 注入约定(与 visual-audit.js 一致):runner 先设 window.__AUDIT_SCOPE__(1-based
// 帧号数组,空/缺 = 全 deck),再 page.evaluate(本文件源码),IIFE 返回结果对象:
//   { engine, version, rules:[ruleId...], scope, findings:[{rule,severity,slide_idx,
//     message, ...payload}] }
(function () {
  'use strict';

  // hero-ZONE 集(与 visual-audit.js 同义):这些版式整体是构图页,豁免居中类几何。
  const HERO_LAYOUTS = new Set([
    'cover', 'section', 'big-stat', 'end', 'quote', 'image-text',
  ]);

  // 短选择器(tag.cls.cls),用于 finding 定位。处理 SVG className.baseVal。
  const shortSel = (el) => {
    const tag = el.tagName.toLowerCase();
    const raw = el.className;
    const clsStr = (raw && raw.baseVal !== undefined ? raw.baseVal : (raw || '')).toString();
    const cls = clsStr.split(/\s+/).filter(Boolean);
    return cls.length ? `${tag}.${cls.join('.')}` : tag;
  };

  // 元素是否有自己的直接文本(不只是子元素)。
  const hasOwnText = (el) => {
    for (const n of el.childNodes) {
      if (n.nodeType === 3 && n.textContent.trim()) return true;
    }
    return false;
  };

  // ==========================================================================
  //  规则注册表 —— 唯一规则源。新增规则 = 往这里加一个 (slide, ctx) => findings。
  // ==========================================================================
  const RULES = [
    {
      // R-VIS-CANVAS-CENTER · 内容并集相对"画布"垂直居中 (2026-05-31)
      // 画布 = [主标题 .header 底边 → 屏幕底 1080];内容并集(排除 .header / 绝对定位 /
      // 隐藏 / 过小 / 被裁)的垂直中心 content_mid 应 ≈ 画布中心 (hb+1080)/2。
      //   offset = canvas_mid - content_mid   (>0 偏上, <0 偏下)
      //   is_full = 内容比可用带还高 → 居中必溢出画布 → 顶对齐是对的,豁免。
      // |offset| > 40 判失衡(warn,留白判断主观,可 data-allow-imbalance opt-out)。
      // 几何全部先减 slide 顶、再 / scale 还原成设计 px,与 1080 同系。
      id: 'R-VIS-CANVAS-CENTER',
      severity: 'warn',
      evaluate(slide, ctx) {
        const { slide_idx, scale, isHeroLayout } = ctx;
        if (isHeroLayout || slide.hasAttribute('data-allow-imbalance')) return [];

        const _ccSr = slide.getBoundingClientRect();
        const _ccSlideTop = _ccSr.top;
        const ccHeader = slide.querySelector(':scope > .header');
        const ccHeaderRendered = !!ccHeader && ccHeader.getClientRects().length > 0;
        const _ccHb = ccHeaderRendered
          ? (ccHeader.getBoundingClientRect().bottom - _ccSlideTop) / scale
          : 0;

        let ccTop = Infinity, ccBot = -Infinity, ccAny = false;
        slide.querySelectorAll('*').forEach((el) => {
          if (el.tagName === 'STYLE' || el.tagName === 'SCRIPT') return;
          if (ccHeader && (el === ccHeader || ccHeader.contains(el))) return;
          const cs = getComputedStyle(el);
          if (cs.display === 'none' || cs.visibility === 'hidden' || +cs.opacity === 0) return;
          if (cs.position === 'absolute' || cs.position === 'fixed') return;
          const tag = el.tagName;
          const isMedia = tag === 'IMG' || tag === 'SVG' || tag === 'svg'
            || tag === 'CANVAS' || tag === 'VIDEO';
          const isLeaf = el.children.length === 0;
          if (!hasOwnText(el) && !isMedia && !isLeaf) return;
          const r = el.getBoundingClientRect();
          if (r.width < 6 || r.height < 6) return;
          // 被 overflow:hidden 祖先裁掉的内容不算可见 —— 与每个非可见溢出祖先求交,
          // 完全被裁则丢弃(否则手机 mock 超出框的聊天/输入条会把并集拉低)。
          let vt = r.top, vb = r.bottom;
          for (let p = el.parentElement; p && p !== slide; p = p.parentElement) {
            if (getComputedStyle(p).overflowY !== 'visible') {
              const pr = p.getBoundingClientRect();
              if (pr.top > vt) vt = pr.top;
              if (pr.bottom < vb) vb = pr.bottom;
            }
          }
          if (vb - vt < 6) return;
          const t = (vt - _ccSlideTop) / scale;
          const b = (vb - _ccSlideTop) / scale;
          if (t < ccTop) ccTop = t;
          if (b > ccBot) ccBot = b;
          ccAny = true;
        });
        if (!ccAny) return [];

        const contentMid = (ccTop + ccBot) / 2;
        const canvasMid = (_ccHb + 1080) / 2;
        const offset = canvasMid - contentMid;        // >0 偏上, <0 偏下
        const contentH = ccBot - ccTop;
        const bandH = 1080 - _ccHb;
        // is_full = 内容并集确实高过可用带 → 无法不溢出地居中 → 顶对齐/溢出是对的,豁免。
        const isFull = bandH <= 8 || contentH > (bandH - 8);

        const content_mid = Math.round(contentMid);
        const canvas_mid = Math.round(canvasMid);
        const off = Math.round(offset);

        if (isFull) return [];
        if (Math.abs(off) <= 40) return [];

        const container_sel = shortSel(slide);
        const dir = off > 0 ? '偏上' : '偏下';
        return [{
          rule: 'R-VIS-CANVAS-CENTER',
          severity: 'warn',
          slide_idx,
          container_sel,
          offset: off,
          content_mid,
          canvas_mid,
          is_full: false,
          top: Math.round(ccTop),
          bot: Math.round(ccBot),
          hb: Math.round(_ccHb),
          message:
            `slide ${slide_idx} · \`${container_sel}\` 内容整体未在[标题底→屏幕底]` +
            `画布垂直居中:${dir} ${Math.abs(off)}px(内容中心 ${content_mid}px / ` +
            `画布中心 ${canvas_mid}px) —— 内容在 .stage 内部看似均衡,但 .stage 相对` +
            `画布整体偏移,所以全页看着上空/下空。Fix: 让 content 的 .grid \`flex:1\` ` +
            `撑满 stage + \`align-content:center\`(稀疏自动居中、满铺自动顶对齐铺满);` +
            `确属设计意图用 \`data-allow-imbalance\` opt-out。`,
        }];
      },
    },
  ];

  // ==========================================================================
  //  driver —— 遍历 slide(可按 scope 过滤),逐条跑规则,汇总 findings。
  // ==========================================================================
  function run(scope) {
    const scopeSet = (Array.isArray(scope) && scope.length)
      ? new Set(scope.map(Number)) : null;
    const slides = document.querySelectorAll('.slide');
    const findings = [];
    slides.forEach((slide, idx) => {
      const slide_idx = idx + 1;
      if (scopeSet && !scopeSet.has(slide_idx)) return;
      const layout = slide.getAttribute('data-layout') || '';
      const ctx = {
        slide_idx,
        label: slide.getAttribute('data-screen-label') || `slide-${slide_idx}`,
        layout,
        isHeroLayout: HERO_LAYOUTS.has(layout),
        scale: parseFloat(getComputedStyle(slide).getPropertyValue('--fs-scale')) || 1,
        shortSel,
        hasOwnText,
        HERO_LAYOUTS,
      };
      for (const rule of RULES) {
        try {
          const fs = rule.evaluate(slide, ctx) || [];
          for (const f of fs) findings.push(f);
        } catch (e) {
          findings.push({
            rule: rule.id, severity: 'error', slide_idx,
            message: `audit '${rule.id}' threw on slide ${slide_idx}: ${e && e.message}`,
          });
        }
      }
    });
    return {
      engine: 'audits.js',
      version: 1,
      rules: RULES.map((r) => r.id),
      scope: scopeSet ? [...scopeSet] : null,
      slides_total: slides.length,
      findings,
    };
  }

  return run((typeof window !== 'undefined' && window.__AUDIT_SCOPE__) || null);
})();
