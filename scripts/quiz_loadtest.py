#!/usr/bin/env python3
"""
Simulate a room of candidates taking a mock exam: login, start, then autosave + heartbeat like the real page,
and submit at the end. Prints request counts and latency percentiles per endpoint.

    python scripts/quiz_loadtest.py --base http://127.0.0.1:8765 --slug thi-thu-1 \
        --users 60 --prefix hs --password pw --duration 120

Accounts <prefix>1..<prefix>N must already exist, belong to the exam's course, and the exam must be open.
Run it against a staging copy: it creates real attempts. Uses the `requests` package already in the virtualenv.
"""
import argparse
import random
import re
import statistics
import threading
import time
from collections import defaultdict

import requests

TOKEN_RE = re.compile(r'name="attempt_token" value="([^"]+)"')
CSRF_RE = re.compile(r"""name=["']csrfmiddlewaretoken["'] value=["']([^"']+)["']""")
CHOICE_RE = re.compile(r'name="(q\d+)" value="(\d+)"')
TF_RE = re.compile(r'name="(q\d+_\d+)" value="T"')

lock = threading.Lock()
timings = defaultdict(list)
statuses = defaultdict(lambda: defaultdict(int))


def record(name, started, response=None, error=None):
    with lock:
        timings[name].append(time.perf_counter() - started)
        statuses[name]['error' if error else response.status_code] += 1


def timed(session, name, method, url, **kwargs):
    started = time.perf_counter()
    try:
        response = session.request(method, url, timeout=30, **kwargs)
    except requests.RequestException as exc:
        record(name, started, error=exc)
        return None
    record(name, started, response)
    return response


def candidate(args, number, start_barrier):
    base = args.base.rstrip('/')
    session = requests.Session()
    username = '%s%d' % (args.prefix, number)
    page = timed(session, 'login page', 'GET', base + '/accounts/login/')
    if page is None:
        return
    csrf = CSRF_RE.search(page.text)
    response = timed(session, 'login', 'POST', base + '/accounts/login/', data={
        'username': username, 'password': args.password,
        'csrfmiddlewaretoken': csrf.group(1) if csrf else '', 'next': '/'}, headers={'Referer': base})
    if response is None or 'sessionid' not in session.cookies:
        print('login failed for', username)
        return
    csrf_token = session.cookies.get('csrftoken', '')
    start_barrier.wait()   # everybody presses "Start" together, like the first minute of a real exam
    response = timed(session, 'start', 'POST', '%s/quiz/%s/start/' % (base, args.slug),
                     data={'agree': '1', 'csrfmiddlewaretoken': csrf_token}, headers={'Referer': base})
    if response is None or response.status_code != 200 or 'attempt_token' not in response.text:
        print('could not open the exam for', username, response.status_code if response is not None else '')
        return
    html = response.text
    token = TOKEN_RE.search(html).group(1)
    attempt_url = response.url.rstrip('/')
    choices = defaultdict(list)
    for name, value in CHOICE_RE.findall(html):
        choices[name].append(value)
    tf_fields = TF_RE.findall(html)

    end = time.time() + args.duration
    next_beat = time.time() + 15 * random.random()
    answers = {}
    while time.time() < end:
        time.sleep(random.uniform(2, 6))
        name = random.choice(list(choices)) if choices else None
        if name:
            answers[name] = random.choice(choices[name])
        for field in random.sample(tf_fields, min(2, len(tf_fields))):
            answers[field] = random.choice('TF')
        data = dict(answers, attempt_token=token, csrfmiddlewaretoken=csrf_token)
        timed(session, 'autosave', 'POST', attempt_url + '/save/', data=data, headers={'Referer': base})
        if time.time() >= next_beat:
            timed(session, 'heartbeat', 'POST', attempt_url + '/heartbeat/',
                  data={'attempt_token': token, 'csrfmiddlewaretoken': csrf_token}, headers={'Referer': base})
            next_beat = time.time() + 15
    timed(session, 'submit', 'POST', attempt_url + '/', data=dict(answers, csrfmiddlewaretoken=csrf_token),
          headers={'Referer': base})


def percentile(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--base', required=True)
    parser.add_argument('--slug', required=True)
    parser.add_argument('--users', type=int, default=30)
    parser.add_argument('--prefix', default='hs')
    parser.add_argument('--first', type=int, default=1, help='number of the first account (prefix + number)')
    parser.add_argument('--password', default='pw')
    parser.add_argument('--duration', type=int, default=60, help='seconds each candidate keeps working')
    args = parser.parse_args()

    barrier = threading.Barrier(args.users)
    threads = [threading.Thread(target=candidate, args=(args, n, barrier), daemon=True)
               for n in range(args.first, args.first + args.users)]
    started = time.time()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    print('\n%d candidates, %.0f s' % (args.users, time.time() - started))
    print('%-12s %6s %8s %8s %8s %8s  %s' % ('endpoint', 'calls', 'p50 ms', 'p95 ms', 'p99 ms', 'max ms', 'status codes'))  # noqa: E501
    for name, values in sorted(timings.items()):
        print('%-12s %6d %8.0f %8.0f %8.0f %8.0f  %s' % (
            name, len(values), 1000 * statistics.median(values), 1000 * percentile(values, 95),
            1000 * percentile(values, 99), 1000 * max(values), dict(statuses[name])))


if __name__ == '__main__':
    main()
