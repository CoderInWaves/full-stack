export interface MetricSnapshot {
  allowed: number;
  denied: number;
  approvalRequired: number;
  redacted: number;
  authenticationFailures: number;
  upstreamFailures: number;
  dlpBlocks: number;
  total: number;
  requestRate: null;
  latencyAverageMs: number | null;
}

export function parsePrometheus(raw: string): MetricSnapshot {
  const snapshot: MetricSnapshot = {
    allowed: 0,
    denied: 0,
    approvalRequired: 0,
    redacted: 0,
    authenticationFailures: 0,
    upstreamFailures: 0,
    dlpBlocks: 0,
    total: 0,
    requestRate: null,
    latencyAverageMs: null,
  };
  let latencyCount = 0;
  let latencySum = 0;
  for (const line of raw.split('\n')) {
    if (!line || line.startsWith('#')) continue;
    const match = line.match(/^([a-zA-Z_:][\w:]*)(?:\{([^}]*)\})?\s+([\d.eE+-]+)/);
    if (!match) continue;
    const [, name, labels = '', rawValue] = match;
    const value = Number(rawValue);
    if (!Number.isFinite(value)) continue;
    if (name === 'mcp_guard_requests_total') {
      const decision = labels.match(/(?:^|,)decision="([^"]+)"/)?.[1];
      if (decision === 'allowed') snapshot.allowed += value;
      if (decision === 'denied') snapshot.denied += value;
      if (decision === 'approval_required') snapshot.approvalRequired += value;
      if (decision === 'redacted') snapshot.redacted += value;
    } else if (name === 'mcp_guard_authentication_failures_total') {
      snapshot.authenticationFailures = value;
    } else if (name === 'mcp_guard_upstream_failures_total') {
      snapshot.upstreamFailures = value;
    } else if (name === 'mcp_guard_dlp_blocks_total') {
      snapshot.dlpBlocks = value;
    } else if (name === 'mcp_guard_request_duration_seconds_sum') {
      latencySum += value;
    } else if (name === 'mcp_guard_request_duration_seconds_count') {
      latencyCount += value;
    }
  }
  snapshot.total = snapshot.allowed + snapshot.denied + snapshot.approvalRequired + snapshot.redacted;
  snapshot.latencyAverageMs = latencyCount ? (latencySum / latencyCount) * 1000 : null;
  return snapshot;
}

export function groupAuditByAgent(events: { agent_id?: string }[]) {
  const counts = new Map<string, number>();
  for (const event of events) if (event.agent_id) counts.set(event.agent_id, (counts.get(event.agent_id) ?? 0) + 1);
  return [...counts.entries()].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value).slice(0, 5);
}

export function groupDeniedTools(events: { tool?: string; decision?: string }[]) {
  const counts = new Map<string, number>();
  for (const event of events) {
    if (event.tool && event.decision?.toUpperCase() === 'DENY') counts.set(event.tool, (counts.get(event.tool) ?? 0) + 1);
  }
  return [...counts.entries()].map(([name, value]) => ({ name, value })).sort((a, b) => b.value - a.value).slice(0, 5);
}

export function groupAuditByHour(events: { timestamp: string }[], now = new Date()) {
  const buckets = Array.from({ length: 12 }, (_, index) => {
    const hour = new Date(now.getTime() - (11 - index) * 60 * 60 * 1000);
    hour.setMinutes(0, 0, 0);
    return { hour, label: hour.toLocaleTimeString([], { hour: '2-digit' }), requests: 0 };
  });
  for (const event of events) {
    const date = new Date(event.timestamp);
    if (Number.isNaN(date.valueOf())) continue;
    date.setMinutes(0, 0, 0);
    const bucket = buckets.find(({ hour }) => hour.getTime() === date.getTime());
    if (bucket) bucket.requests += 1;
  }
  return buckets;
}
