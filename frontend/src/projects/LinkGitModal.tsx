import { useState } from 'react'
import { Modal } from '../components/atoms/Modal'
import { Field } from '../components/atoms/Field'
import { errorMessage } from '../api/client'
import { useSetProjectGit } from '../api/projects'
import type { Project } from '../api/projects'

export function LinkGitModal({ project, onClose }: { project: Project; onClose: () => void }) {
  const [url, setUrl] = useState(project.git_url_override ?? project.scm_url ?? '')
  const [authType, setAuthType] = useState<'none' | 'token' | 'userpass'>(project.git_auth_type ?? 'none')
  const [username, setUsername] = useState(project.git_username ?? '')
  const [secret, setSecret] = useState('')           // write-only; blank = leave existing
  const [error, setError] = useState<string | null>(null)
  const setGit = useSetProjectGit(project.id)

  async function submit() {
    setError(null)
    try {
      await setGit.mutateAsync({
        git_url_override: url || null,
        auth_type: authType,
        username: authType === 'userpass' ? username : null,
        // omit `secret` entirely when blank so the backend sentinel leaves it intact
        ...(secret ? { secret } : {}),
      })
      onClose()
    } catch (e) { setError(errorMessage(e)) }
  }

  return (
    <Modal open onOpenChange={(o) => { if (!o) onClose() }} title="Link git source" width={520}>
      <div className="col" style={{ gap: 14 }}>
        <Field label="Git URL (https)" placeholder="https://git.example.com/repo.git"
          value={url} onChange={(e) => setUrl(e.target.value)} />
        <div className="col" style={{ gap: 6 }}>
          <label className="field-label">Authentication</label>
          <div className="row gap2">
            {(['none', 'token', 'userpass'] as const).map((a) => (
              <label key={a} className="row gap2" style={{ alignItems: 'center', fontSize: 13.5 }}>
                <input type="radio" name="auth" checked={authType === a} onChange={() => setAuthType(a)} />
                {a === 'none' ? 'Public' : a === 'token' ? 'Token / PAT' : 'User + password'}
              </label>
            ))}
          </div>
        </div>
        {authType === 'userpass' && (
          <Field label="Username" value={username} onChange={(e) => setUsername(e.target.value)} />
        )}
        {authType !== 'none' && (
          <Field label={project.has_git_secret ? 'Secret (leave blank to keep existing)' : 'Secret'}
            type="password" autoComplete="new-password"
            placeholder={project.has_git_secret ? '••••••••' : (authType === 'token' ? 'Personal access token' : 'Password')}
            value={secret} onChange={(e) => setSecret(e.target.value)} />
        )}
        {error && <div style={{ fontSize: 12.5, color: 'var(--unreachable)' }}>{error}</div>}
        <div className="row gap2" style={{ justifyContent: 'flex-end' }}>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" onClick={submit} disabled={setGit.isPending}>
            {setGit.isPending ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </Modal>
  )
}
