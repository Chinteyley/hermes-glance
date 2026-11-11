// Glance, Desktop half. Plain ESM loaded uncompiled: no JSX, SDK and React imports only.
// Draws the compare PNG that glance_check produces; anything else keeps the built-in image.

import * as sdk from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

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
  return Boolean(
    file && file.kind === 'image' && res && res.layout && res.layout.kind === LAYOUT_KIND &&
      typeof res.compare_png === 'string' && baseName(res.compare_png) === baseName(file.path)
  )
}

function VerdictChip({ verdict }) {
  const Badge = sdk.Badge
  const text = String(verdict || '?')
  if (!Badge) return jsx('span', { children: text })
  return jsx(Badge, { variant: VERDICT_VARIANT[text] || 'muted', children: text })
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
    style: { margin: 0, maxWidth: 560, border: '1px solid var(--ui-stroke-secondary)', borderRadius: 10, overflow: 'hidden' },
    children: [
      jsxs('figcaption', {
        style: { display: 'flex', alignItems: 'center', gap: 8, padding: '8px 10px', fontSize: 12 },
        children: [
          jsx(VerdictChip, { verdict: res.verdict }),
          jsx('span', { style: { color: 'var(--ui-text-secondary)' }, children: res.reason || '' })
        ]
      }),
      src && jsx('img', { src, alt: `Glance ${res.verdict}: before and after`, style: { display: 'block', width: '100%' } })
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
