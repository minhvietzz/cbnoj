import os
import shutil
import subprocess
import time

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils.translation import gettext as _
from django.views.generic import TemplateView, View

from judge.models import Judge
from judge.utils.views import TitleMixin

__all__ = ['ServerStatusPage', 'ServerStatusData', 'can_view_server_status']

PERMISSION = 'judge.view_server_status'


def can_view_server_status(user):
    return user.is_authenticated and (user.is_superuser or user.has_perm(PERMISSION))


class StatusAccessMixin(object):
    def dispatch(self, request, *args, **kwargs):
        if not can_view_server_status(request.user):
            raise PermissionDenied(_('You do not have permission to view the server status.'))
        return super().dispatch(request, *args, **kwargs)


def _read_cpu_times():
    with open('/proc/stat') as f:
        fields = [int(x) for x in f.readline().split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)  # idle + iowait
    return idle, sum(fields)


def cpu_percent(interval=0.3):
    idle1, total1 = _read_cpu_times()
    time.sleep(interval)
    idle2, total2 = _read_cpu_times()
    total = total2 - total1
    return round(100.0 * (1 - (idle2 - idle1) / total), 1) if total > 0 else 0.0


def meminfo():
    info = {}
    with open('/proc/meminfo') as f:
        for line in f:
            key, value = line.split(':', 1)
            info[key] = int(value.split()[0]) * 1024
    total = info['MemTotal']
    available = info.get('MemAvailable', info['MemFree'])
    used = total - available
    swap_total = info.get('SwapTotal', 0)
    swap_used = swap_total - info.get('SwapFree', 0)
    return {
        'total': total, 'used': used, 'available': available,
        'cache': info.get('Cached', 0) + info.get('Buffers', 0),
        'percent': round(100.0 * used / total, 1) if total else 0,
        'swap_total': swap_total, 'swap_used': swap_used,
        'swap_percent': round(100.0 * swap_used / swap_total, 1) if swap_total else 0,
    }


def disk_info(path='/'):
    usage = shutil.disk_usage(path)
    return {'path': path, 'total': usage.total, 'used': usage.used, 'free': usage.free,
            'percent': round(100.0 * usage.used / usage.total, 1) if usage.total else 0}


def top_processes(limit=8):
    try:
        out = subprocess.check_output(['ps', '-eo', 'rss,pcpu,user:12,comm', '--sort=-rss'], timeout=3).decode()
    except (OSError, subprocess.SubprocessError):
        return []
    rows = []
    for line in out.splitlines()[1:limit + 1]:
        rss, cpu, user, name = line.split(None, 3)
        rows.append({'memory': int(rss) * 1024, 'cpu': float(cpu), 'user': user, 'name': name.strip()})
    return rows


def uptime_seconds():
    with open('/proc/uptime') as f:
        return int(float(f.read().split()[0]))


def collect():
    load = os.getloadavg()
    judges = [{'name': j.name, 'online': j.online, 'ping': round(j.ping * 1000) if j.ping else None,
               'load': j.load, 'blocked': j.is_blocked or j.is_disabled}
              for j in Judge.objects.order_by('name')]
    return {
        'cpu': {'percent': cpu_percent(), 'cores': os.cpu_count() or 1, 'load': [round(x, 2) for x in load]},
        'memory': meminfo(),
        'disk': disk_info('/'),
        'uptime': uptime_seconds(),
        'processes': top_processes(),
        'judges': judges,
        'time': int(time.time()),
    }


class ServerStatusPage(StatusAccessMixin, TitleMixin, TemplateView):
    template_name = 'server-status.html'

    def get_title(self):
        return _('Server status')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['status'] = collect()
        return context


class ServerStatusData(StatusAccessMixin, View):
    def get(self, request, *args, **kwargs):
        return JsonResponse(collect())
