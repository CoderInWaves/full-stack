import http from 'k6/http'
import { check, sleep } from 'k6'
import { Counter, Rate, Trend } from 'k6/metrics'

const rateLimited  = new Counter('rate_limited_requests')
const allowedRate  = new Rate('allowed_rate')
const latencyTrend = new Trend('request_latency', true)

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000'
const API_KEY  = __ENV.API_KEY  || 'REPLACE_WITH_REAL_KEY'

export const options = {
  scenarios: {
    normal_traffic: {
      executor: 'constant-vus',
      vus: 5,
      duration: '30s',
      tags: { scenario: 'normal' },
    },
    spike: {
      executor: 'ramping-vus',
      startVUs: 0,
      stages: [
        { duration: '10s', target: 50 },
        { duration: '20s', target: 50 },
        { duration: '10s', target: 0 },
      ],
      startTime: '35s',
      tags: { scenario: 'spike' },
    },
  },
  thresholds: {
    http_req_duration: ['p(95)<500'],
    allowed_rate:      ['rate>0.05'],
  },
}

const HEADERS = { 'X-API-Key': API_KEY, 'Content-Type': 'application/json' }

export default function () {
  const endpoints = [
    { method: 'GET',  url: `${BASE_URL}/api/products` },
    { method: 'GET',  url: `${BASE_URL}/api/users` },
    { method: 'POST', url: `${BASE_URL}/api/orders`, body: JSON.stringify({ product_id: 1, quantity: 1 }) },
  ]

  const ep = endpoints[Math.floor(Math.random() * endpoints.length)]
  const start = Date.now()

  const res = ep.method === 'POST'
    ? http.post(ep.url, ep.body, { headers: HEADERS })
    : http.get(ep.url, { headers: HEADERS })

  latencyTrend.add(Date.now() - start)

  const allowed = res.status !== 429
  allowedRate.add(allowed)
  if (!allowed) rateLimited.add(1)

  check(res, {
    'status is 200 or 429': r => r.status === 200 || r.status === 429,
    'has ratelimit header':  r => r.headers['X-Ratelimit-Limit'] !== undefined || r.status === 401,
  })

  sleep(0.1)
}
