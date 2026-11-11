// Glance, Desktop half. Plain ESM loaded uncompiled: no JSX, SDK and React imports only.
// Draws the compare PNG that glance_check produces as a before/after slider; anything else keeps
// the built-in image.

import * as sdk from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

// diff.py writes [before | after] at equal size with a verdict bar below; the result's `layout`
// carries the sizes. The slider shows one frame at a time by scaling the image to 200% width inside a
// box with the frame's aspect ratio, which also crops off the verdict bar the caption already shows.
const LAYOUT_KIND = 'glance-compare/v1'
const VERDICT_VARIANT = { PASS: 'success', NO_CHANGE: 'warn', ERROR_SCREEN: 'destructive', BLANK: 'destructive' }

function parseResult(result) {
  if (result && typeof result === 'object') return result
  if (typeof result !== 'string') return null
  try {
    return JSON.parse(result)
  } catch {
    return null
  }
}

const baseName = p => String(p || '').split(/[\\/]/).pop()

function isGlanceCompare(file, res) {
  const layout = res && res.layout
  return Boolean(
    file && file.kind === 'image' && layout && layout.kind === LAYOUT_KIND &&
      layout.frame_width > 0 && layout.frame_height > 0 &&
      typeof res.compare_png === 'string' && baseName(res.compare_png) === baseName(file.path)
  )
}

function VerdictChip({ verdict }) {
  const text = String(verdict || '?')
  if (!sdk.Badge) return jsx('span', { style: { fontWeight: 600 }, children: text })
  return jsx(sdk.Badge, { variant: VERDICT_VARIANT[text] || 'muted', children: text })
}

function Half({ src, side, clip }) {
  return jsx('img', {
    src,
    alt: '',
    draggable: false,
    style: {
      position: 'absolute',
      top: 0,
      left: side === 'after' ? '-100%' : 0,
      width: '200%',
      maxWidth: 'none',
      height: 'auto',
      clipPath: clip,
      pointerEvents: 'none',
      userSelect: 'none'
    }
  })
}

function RegionBox({ region }) {
  const pct = v => `${(Number(v) || 0) * 100}%`
  return jsx('div', {
    style: {
      position: 'absolute',
      left: pct(region.x),
      top: pct(region.y),
      width: pct(region.w),
      height: pct(region.h),
      border: '2px dashed var(--ui-red)',
      borderRadius: 3,
      pointerEvents: 'none'
    }
  })
}

function Slider({ src, res }) {
  const [split, setSplit] = useState(50)
  const { frame_width: w, frame_height: h } = res.layout
  const regions = Array.isArray(res.regions) ? res.regions : []
  const label = { position: 'absolute', top: 8, padding: '2px 6px', borderRadius: 3, fontSize: 11,
    background: 'var(--ui-bg-elevated)', color: 'var(--ui-text-primary)', pointerEvents: 'none' }

  return jsxs('div', {
    style: { position: 'relative', width: '100%', aspectRatio: `${w} / ${h}`, overflow: 'hidden', touchAction: 'none' },
    children: [
      jsx(Half, { src, side: 'before' }),
      jsx(Half, { src, side: 'after', clip: `inset(0 0 0 ${50 + split / 2}%)` }),
      // The after half already has the regions outlined in the PNG, so these mark the same areas on the before side.
      jsx('div', {
        style: { position: 'absolute', inset: 0, clipPath: `inset(0 ${100 - split}% 0 0)`, pointerEvents: 'none' },
        children: regions.map((region, i) => jsx(RegionBox, { region }, i))
      }),
      jsx('div', {
        style: { position: 'absolute', top: 0, bottom: 0, left: `${split}%`, width: 2, marginLeft: -1,
          background: 'var(--ui-accent)', pointerEvents: 'none' }
      }),
      jsx('div', {
        style: { position: 'absolute', top: '50%', left: `${split}%`, width: 22, height: 22, margin: '-11px 0 0 -11px',
          borderRadius: '50%', background: 'var(--ui-accent)', border: '2px solid var(--ui-text-primary)', pointerEvents: 'none' }
      }),
      split > 12 && jsx('span', { style: { ...label, left: 8 }, children: 'Before' }),
      split < 88 && jsx('span', { style: { ...label, right: 8 }, children: 'After' }),
      jsx('input', {
        type: 'range',
        min: 0,
        max: 100,
        step: 1,
        value: split,
        'aria-label': 'Drag to compare before and after',
        onChange: e => setSplit(Number(e.target.value)),
        style: { position: 'absolute', inset: 0, width: '100%', height: '100%', margin: 0, opacity: 0, cursor: 'ew-resize' }
      })
    ]
  })
}

function GlanceCompare({ file, result, fallback }) {
  const res = parseResult(result)
  const ours = isGlanceCompare(file, res)
  const [src, setSrc] = useState(null)

  useEffect(() => {
    if (!ours) return undefined
    let live = true
    file.resolveUrl().then(url => live && setSrc(url), () => live && setSrc(''))
    return () => {
      live = false
    }
  }, [file, ours])

  if (!ours || src === '') return fallback ?? null

  return jsxs('figure', {
    style: { margin: 0, maxWidth: 340, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 10, overflow: 'hidden' },
    children: [
      jsxs('figcaption', {
        style: { display: 'flex', alignItems: 'flex-start', gap: 8, padding: '8px 10px', fontSize: 12, lineHeight: 1.4 },
        children: [
          jsx(VerdictChip, { verdict: res.verdict }),
          jsx('span', { style: { color: 'var(--ui-text-secondary)' }, children: res.reason || '' })
        ]
      }),
      src ? jsx(Slider, { src, res }) : null
    ]
  })
}

export default {
  id: 'glance',
  name: 'Glance',
  register(ctx) {
    if (typeof sdk.TOOL_MEDIA_RENDERER_AREA !== 'string') return
    ctx.register({
      id: 'compare',
      area: sdk.TOOL_MEDIA_RENDERER_AREA,
      data: { tools: ['glance_check'], render: props => jsx(GlanceCompare, props) }
    })
  }
}
