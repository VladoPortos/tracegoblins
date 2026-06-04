import { SettingsLayout } from './SettingsLayout'
import { Glyph } from '../components/atoms/Glyph'
import { ACCENT_HUE, useTheme, type Density } from '../shell/ThemeProvider'

export function AppearanceSettings() {
  const { theme, setTheme, accent, setAccent, density, setDensity } = useTheme()
  const densities: Density[] = ['compact', 'regular', 'comfy']
  return (
    <SettingsLayout>
      <div className="col" style={{ gap: 18 }}>
        <div>
          <label className="field-label" style={{ marginBottom: 8 }}>Theme</label>
          <div className="row gap2">
            {(['light', 'dark'] as const).map((t) => (
              <button key={t} onClick={() => setTheme(t)} className={'btn ' + (theme === t ? 'btn-primary' : '')} style={{ flex: 1, justifyContent: 'center', padding: 14 }}>
                <Glyph name={t === 'light' ? 'sun' : 'moon'} size={16} />{t === 'light' ? 'Light' : 'Dark'}
              </button>
            ))}
          </div>
        </div>
        <div>
          <label className="field-label" style={{ marginBottom: 8 }}>Accent</label>
          <div className="row gap2 wrap">
            {Object.entries(ACCENT_HUE).map(([id, h]) => (
              <button key={id} title={id} onClick={() => setAccent(id)} aria-label={`accent ${id}`}
                style={{ width: 26, height: 26, borderRadius: 7, cursor: 'pointer', background: `oklch(0.6 0.17 ${h})`,
                         border: accent === id ? '2px solid var(--text)' : '2px solid var(--border)' }} />
            ))}
          </div>
        </div>
        <div>
          <label className="field-label" style={{ marginBottom: 8 }}>Density</label>
          <div className="seg">
            {densities.map((d) => (
              <button key={d} aria-pressed={density === d} onClick={() => setDensity(d)}>{d}</button>
            ))}
          </div>
        </div>
      </div>
    </SettingsLayout>
  )
}
