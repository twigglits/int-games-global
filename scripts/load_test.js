/*
 * k6 load test for the movie search endpoint.
 *
 * Run it against a running platform:
 *
 *   docker run --rm --network movie-search-platform_movie-search \
 *     -v "$PWD/scripts:/scripts:ro" \
 *     -e API_BASE_URL=http://api:8080 \
 *     -e CLIENT_ID=reader-client -e CLIENT_SECRET=reader-secret-change-me \
 *     grafana/k6:latest run /scripts/load_test.js
 *
 * ...or from the host, if k6 is installed:
 *
 *   API_BASE_URL=http://localhost:8080 k6 run scripts/load_test.js
 *
 * What it checks
 * --------------
 * The requirement is "all endpoints respond within 500 ms at p95 under normal
 * load". That is expressed below as a threshold, so the run fails rather than
 * producing a number somebody has to read and judge.
 *
 * The API rate limit is 60 requests per minute **per client**, and every virtual
 * user here authenticates as the same client, so they all share one budget. A
 * test that ignored that would measure the rate limiter rather than the search
 * path: at 10 virtual users and one request per second each, three quarters of
 * the requests come back 429.
 *
 * The script therefore paces itself to the configured limit:
 *
 *     think time per VU = VUS * 60 / RATE_LIMIT_PER_MINUTE  seconds
 *
 * To measure real throughput instead, raise the API limit and tell the script:
 *
 *     docker compose exec api sh -c 'true'   # the limit is set at start-up
 *     # in .env or the compose file: RequestLimits__PermitsPerWindow=6000
 *     docker compose up -d api
 *     ... k6 run -e RATE_LIMIT_PER_MINUTE=6000 -e VUS=20 /scripts/load_test.js
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

const BASE_URL = __ENV.API_BASE_URL || 'http://localhost:8080';
const CLIENT_ID = __ENV.CLIENT_ID || 'reader-client';
const CLIENT_SECRET = __ENV.CLIENT_SECRET || 'reader-secret-change-me';
const VUS = parseInt(__ENV.VUS || '5', 10);
const DURATION = __ENV.DURATION || '60s';
// Must match RequestLimits:PermitsPerWindow on the API, or the run measures the
// rate limiter instead of the search.
const RATE_LIMIT_PER_MINUTE = parseInt(__ENV.RATE_LIMIT_PER_MINUTE || '60', 10);
// Think time that keeps every VU together inside the shared budget, with a 10%
// margin so that a clock difference does not push the run over the edge.
const THINK_TIME_SECONDS = (VUS * 60) / RATE_LIMIT_PER_MINUTE * 1.1;

const searchDuration = new Trend('search_duration_ms', true);
const searchErrors = new Rate('search_errors');
const rateLimited = new Counter('search_rate_limited');
const emptyResults = new Counter('search_empty_results');

export const options = {
  scenarios: {
    search: {
      executor: 'constant-vus',
      vus: VUS,
      duration: DURATION,
      gracefulStop: '10s',
    },
  },
  thresholds: {
    // The stated requirement.
    'http_req_duration{endpoint:search}': ['p(95)<500'],
    // A failure rate above one percent means the platform is not merely slow.
    search_errors: ['rate<0.01'],
    // Rate limiting is not an error, but a run that is mostly 429 measured
    // nothing, so it is surfaced rather than hidden.
    checks: ['rate>0.95'],
  },
};

/*
 * The five queries from the specification, plus a few that exercise different
 * filter combinations. Picking at random keeps the response cache from turning
 * the test into a cache benchmark.
 */
const QUERIES = [
  { q: 'action movies from the 90s with high IMDB ratings', genre: 'Action', decade: 1990, min_imdb_rating: 7.0 },
  { q: 'critically acclaimed drama films with small budgets', genre: 'Drama' },
  { q: 'animated family movies distributed by Disney' },
  { q: 'sci-fi films directed by James Cameron' },
  { q: 'dark psychological thrillers with low Rotten Tomatoes scores' },
  { q: 'heist movies with a clever twist', top_k: 20 },
  { q: 'romantic comedies set in New York', genre: 'Romantic Comedy' },
  { q: 'war epics based on real events', min_imdb_rating: 6.5 },
  { q: 'low budget horror that made a lot of money', genre: 'Horror' },
  { q: 'family friendly adventure films', mpaa_rating: 'PG' },
];

/** Obtain one access token. Runs once per virtual user, in setup. */
export function setup() {
  const response = http.post(
    `${BASE_URL}/auth/token`,
    JSON.stringify({ client_id: CLIENT_ID, client_secret: CLIENT_SECRET }),
    { headers: { 'Content-Type': 'application/json' }, tags: { endpoint: 'token' } },
  );

  if (response.status !== 200) {
    throw new Error(`could not obtain a token: ${response.status} ${response.body}`);
  }
  return { token: response.json('access_token') };
}

// Built by hand rather than with URLSearchParams: the k6 runtime is not a
// browser, and a missing global here fails every iteration silently.
function buildUrl(query) {
  const parts = [
    `q=${encodeURIComponent(query.q)}`,
    `top_k=${query.top_k || 10}`,
  ];
  if (query.genre) parts.push(`genre=${encodeURIComponent(query.genre)}`);
  if (query.decade) parts.push(`decade=${query.decade}`);
  if (query.min_imdb_rating) parts.push(`min_imdb_rating=${query.min_imdb_rating}`);
  if (query.mpaa_rating) parts.push(`mpaa_rating=${encodeURIComponent(query.mpaa_rating)}`);
  return `${BASE_URL}/api/v1/movies/search?${parts.join('&')}`;
}

export default function (data) {
  const query = QUERIES[Math.floor(Math.random() * QUERIES.length)];

  const response = http.get(buildUrl(query), {
    headers: { Authorization: `Bearer ${data.token}` },
    tags: { endpoint: 'search' },
  });

  searchDuration.add(response.timings.duration);

  if (response.status === 429) {
    rateLimited.add(1);
    // Back off for a whole window rather than hammering a closed door.
    sleep(Math.max(THINK_TIME_SECONDS, 5));
    return;
  }

  const ok = check(response, {
    'status is 200': (r) => r.status === 200,
    'body carries results': (r) => {
      try {
        return Array.isArray(r.json('results'));
      } catch (error) {
        return false;
      }
    },
    'answered within 500 ms': (r) => r.timings.duration < 500,
  });

  searchErrors.add(!ok);

  if (ok && response.json('count') === 0) {
    emptyResults.add(1);
  }

  sleep(THINK_TIME_SECONDS);
}

export function handleSummary(data) {
  const p95 = data.metrics['http_req_duration{endpoint:search}']
    ? data.metrics['http_req_duration{endpoint:search}'].values['p(95)']
    : data.metrics.http_req_duration.values['p(95)'];

  const lines = [
    '',
    '=============================================================',
    ' MOVIE SEARCH LOAD TEST',
    '=============================================================',
    ` virtual users     : ${VUS}`,
    ` duration          : ${DURATION}`,
    ` client rate limit : ${RATE_LIMIT_PER_MINUTE}/minute  (think time ${THINK_TIME_SECONDS.toFixed(1)}s per VU)`,
    ` requests          : ${data.metrics.http_reqs.values.count}`,
    ` p50 latency       : ${data.metrics.http_req_duration.values.med.toFixed(1)} ms`,
    ` p95 latency       : ${p95.toFixed(1)} ms   (budget 500 ms)`,
    ` p99 latency       : ${data.metrics.http_req_duration.values['p(99)'].toFixed(1)} ms`,
    ` failed requests   : ${data.metrics.http_req_failed.values.passes}`,
    ` rate limited      : ${data.metrics.search_rate_limited ? data.metrics.search_rate_limited.values.count : 0}`,
    ` empty results     : ${data.metrics.search_empty_results ? data.metrics.search_empty_results.values.count : 0}`,
    '=============================================================',
    '',
  ];

  return {
    stdout: lines.join('\n'),
    'load-test-summary.json': JSON.stringify(data, null, 2),
  };
}
