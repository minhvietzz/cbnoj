from django.conf import settings

# Executors the run service loads; a language of the site can be tried out only if its key is in this set.
RUN_LANGUAGES = frozenset(getattr(settings, 'RUN_LANGUAGES', ('C', 'C11', 'CPP11', 'CPP14', 'CPP17', 'CPP20', 'PY3',
                                                              'PAS', 'JAVA')))


def language_family(key):
    """The group a language belongs to in the editor and in the code templates of the profile."""
    if key.startswith('CPP'):
        return 'cpp'
    if key in ('C', 'C11'):
        return 'c'
    if key.startswith('PY'):
        return 'py'
    if key == 'PAS':
        return 'pas'
    return None


def runner_key():
    with open(getattr(settings, 'RUNNER_KEY_FILE', '/home/vnojsite/judge-conf/runner.key')) as f:
        return f.read().strip()
