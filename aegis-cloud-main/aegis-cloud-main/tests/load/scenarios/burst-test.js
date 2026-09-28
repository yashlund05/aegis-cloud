import http from 'k6/http';
import { check, sleep } from 'k6';

export const options = {
  stages: [
    { duration: '2m', target: 10 },   // warm up
    { duration: '1m', target: 100 },  // spike
    { duration: '2m', target: 100 },  // sustain
    { duration: '1m', target: 10 },   // cool down
    { duration: '2m', target: 10 },   // steady
  ],
  thresholds: {
    http_req_duration: ['p(99)<500'],
  },
};

export default function () {
  const res = http.get(`http://${__ENV.TARGET_URL || 'localhost:8080'}/`);
  check(res, { 'status is 200': (r) => r.status === 200 });
  sleep(0.1);
}
