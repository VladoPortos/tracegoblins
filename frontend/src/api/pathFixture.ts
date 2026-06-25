import type { PathTree, PathNode, PathEdge, NodeResult, RunInputs, PathViewRef } from './path'

const PKG_NAMES = ['nginx','curl','vim','git','htop','jq','tmux','wget','unzip','rsync','gcc','make','python3-pip','kernel-devel','nodejs','redis','postgresql','mariadb','docker-ce','firewalld','chrony','openssl','ca-certificates','net-tools','bind-utils','telnet','lsof','strace','tcpdump','sysstat','iotop','ncdu','tree','zip','bzip2','gzip','tar','cronie','logrotate','rsyslog','audit','policycoreutils','oracle-instantclient','java-11-openjdk','maven','ansible-core','podman','skopeo','buildah','jdk-temurin']

export interface PkgItem { idx: number; name: string; status: 'ok' | 'changed' | 'failed'; output: string }
export function packages(): PkgItem[] {
  return PKG_NAMES.map((name, i) => {
    const failed = i === 13 || i === 42
    const status: PkgItem['status'] = failed ? 'failed' : (i % 3 === 0 ? 'ok' : 'changed')
    const output = failed
      ? `Failure talking to dnf: No package ${name} available.`
      : (status === 'changed' ? `Installed: ${name}-${2 + (i % 6)}.${i % 9}.${i % 5}-1.el9` : `${name} is already at the latest version`)
    return { idx: i, name, status, output }
  })
}

const N = (p: Partial<PathNode> & Pick<PathNode, 'id' | 'type' | 'label' | 'status'>): PathNode => ({
  sub: null, action: null, host_count: null, taken_hosts: null, item_count: null, ok_count: null, fail_count: null,
  has_failures: false, is_conditional: false, condition: null, branch: null, enter_to: null,
  child_count: null, duration_s: null, task_path: null, ...p,
})

export function mainTree(runId: string): PathTree {
  const nodes: PathNode[] = [
    N({ id: 'facts', type: 'task', label: 'gather_facts', sub: 'setup', status: 'ok', host_count: 50, action: 'ansible.builtin.setup' }),
    N({ id: 'cdb', type: 'task', label: 'fetch chain template', sub: 'uri · CDB', status: 'ok', host_count: 50, action: 'ansible.builtin.uri' }),
    N({ id: 'base', type: 'role', label: 'base_setup', sub: 'role · 12 tasks', status: 'ok', child_count: 12, enter_to: { type: 'container', id: 'base' } }),
    N({ id: 'install', type: 'loop', label: 'install packages', sub: 'loop · 50 items', status: 'changed', item_count: 50, ok_count: 48, fail_count: 2, has_failures: true, action: 'ansible.builtin.package', enter_to: { type: 'loop', id: 'install' }, task_path: 'roles/day2/tasks/packages.yml:3' }),
    N({ id: 'when', type: 'when', label: 'OS family', sub: 'decision', status: 'ok', is_conditional: true, condition: 'ansible_os_family == "RedHat"' }),
    N({ id: 'yum', type: 'task', label: 'configure yum repo', sub: 'yum_repository', status: 'ok', host_count: 49, branch: 'redhat', action: 'ansible.builtin.yum_repository' }),
    N({ id: 'choco', type: 'task', label: 'configure choco repo', sub: 'win_chocolatey', status: 'ok', host_count: 1, branch: 'windows', action: 'chocolatey.chocolatey.win_chocolatey' }),
    N({ id: 'restart', type: 'task', label: 'restart service', sub: 'service', status: 'failed', host_count: 50, action: 'ansible.builtin.service' }),
  ]
  const edges: PathEdge[] = [
    { from: 'facts', to: 'cdb', branch: null }, { from: 'cdb', to: 'base', branch: null },
    { from: 'base', to: 'install', branch: null }, { from: 'install', to: 'when', branch: null },
    { from: 'when', to: 'yum', branch: 'redhat' }, { from: 'when', to: 'choco', branch: 'windows' },
    { from: 'yum', to: 'restart', branch: 'redhat' }, { from: 'choco', to: 'restart', branch: 'windows' },
  ]
  return { run_id: runId, view: { type: 'main' }, nodes, edges }
}

export function containerTree(runId: string, id: string): PathTree {
  const defs: [string, string, PathNode['status']][] = [
    ['create app group', 'group', 'ok'], ['create app user', 'user', 'ok'], ['set sysctl limits', 'sysctl', 'changed'],
    ['install base pkgs', 'package', 'ok'], ['configure timezone', 'timezone', 'ok'], ['write motd', 'copy', 'changed'],
    ['ensure /opt/app dir', 'file', 'ok'], ['template logrotate', 'template', 'ok'], ['enable firewalld', 'systemd', 'ok'],
    ['open port 8080', 'firewalld', 'changed'], ['set selinux context', 'sefcontext', 'ok'], ['flush handlers', 'meta', 'ok'],
  ]
  const nodes = defs.map((t, i) => N({ id: `b${i}`, type: 'task', label: t[0], sub: t[1], status: t[2], host_count: 50, action: `ansible.builtin.${t[1]}` }))
  const edges: PathEdge[] = []
  for (let i = 0; i < defs.length - 1; i++) edges.push({ from: `b${i}`, to: `b${i + 1}`, branch: null })
  return { run_id: runId, view: { type: 'container', id }, nodes, edges }
}

export function loopTree(runId: string, id: string, iter: number): PathTree {
  const it = packages()[iter]
  const nodes: PathNode[] = [
    N({ id: 'loopRoot', type: 'loop', label: 'install packages', sub: 'loop · 50 items', status: 'changed', item_count: 50, ok_count: 48, fail_count: 2 }),
    N({ id: 'item', type: 'item', label: 'item', sub: `iteration ${iter + 1}`, status: 'ok', condition: null, action: null }),
    N({ id: 'apt', type: 'task', label: 'package', sub: `name="${it.name}"`, status: it.status, host_count: 50, action: 'ansible.builtin.package', task_path: 'roles/day2/tasks/packages.yml:3' }),
    N({ id: 'result', type: 'result', label: 'result', sub: it.status, status: it.status }),
  ]
  // item value carried on the node label for the mock; the drawer reads loopResults for detail.
  nodes[1].label = `= "${it.name}"`
  const edges: PathEdge[] = [
    { from: 'loopRoot', to: 'item', branch: null }, { from: 'item', to: 'apt', branch: null }, { from: 'apt', to: 'result', branch: null },
  ]
  return { run_id: runId, view: { type: 'loop', id }, nodes, edges }
}

export function loopResults(): NodeResult[] {
  return packages().map((p) => ({
    host: 'aggregate', item_index: p.idx, item_value: p.name,
    status: p.status, changed: p.status === 'changed', output: p.output, skip_reason: null,
    duration_s: Number((0.3 + (p.idx % 9) * 0.12).toFixed(1)),
  }))
}

export const MOCK_INPUTS: RunInputs = {
  extra_vars: { packages: `[50 packages]`, target_env: 'prod', enable_repo: true },
  survey: { ticket: 'CHG0042199' },
  limit: 'day2_batch_3', scm_revision: 'a1b9f4c', project_id: 7, project_name: 'day2-playbooks',
}

export function treeFor(runId: string, view: PathViewRef, iter: number): PathTree {
  if (view.type === 'container') return containerTree(runId, view.id)
  if (view.type === 'loop') return loopTree(runId, view.id, iter)
  return mainTree(runId)
}
