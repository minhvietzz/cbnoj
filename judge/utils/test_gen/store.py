"""Writing a set of tests into a problem, shared by the MCP tools (problem_set_tests, test generation)."""
import io
import json
import zipfile

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import transaction

from judge.models import ProblemData, ProblemTestCase
from judge.utils.problem_data import ProblemDataCompiler

FLOAT_CHECKERS = ('floats', 'floatsabs', 'floatsrel')


class StoreError(Exception):
    """The tests cannot be written; the message is in Vietnamese and meant for the teacher."""


def check_tests_writable(problem):
    if problem.is_manually_managed:
        raise StoreError('Bài này do quản trị viên tự quản lý dữ liệu, không đặt test bằng công cụ được.')
    if problem.is_archived:
        raise StoreError('Bài này đã được lưu trữ, không sửa test được.')
    org = problem.organization if problem.is_organization_private else None
    if org is not None and settings.VNOJ_QUOTA_ENFORCEMENT_ENABLED and not org.can_upload_data():
        raise StoreError('Tổ chức đã hết dung lượng lưu test.')


def write_tests(problem, cleaned, checker='standard', float_precision=6):
    """Replace all tests of the problem. `cleaned`: list of (input text, output text, points). Returns ProblemData."""
    buffer = io.BytesIO()
    names = []
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        for number, (text_in, text_out, _) in enumerate(cleaned, 1):
            archive.writestr('%d.in' % number, text_in)
            archive.writestr('%d.out' % number, text_out)
            names += ['%d.in' % number, '%d.out' % number]

    with transaction.atomic():
        data, _created = ProblemData.objects.get_or_create(problem=problem)
        if data.zipfile:
            data.zipfile.delete(save=False)
        data.zipfile.save('tests.zip', ContentFile(buffer.getvalue()), save=False)
        data.checker = checker
        data.checker_args = json.dumps({'precision': int(float_precision)}) if checker in FLOAT_CHECKERS else ''
        data.grader = 'standard'
        data.save()
        problem.cases.all().delete()
        for number, (_i, _o, points) in enumerate(cleaned, 1):
            ProblemTestCase.objects.create(
                dataset=problem, order=number, type='C', input_file='%d.in' % number, output_file='%d.out' % number,
                points=points, is_pretest=False)
    ProblemDataCompiler.generate(problem, data, problem.cases.order_by('order'), names)
    data.refresh_from_db()
    if data.feedback:
        raise StoreError('Đã lưu test nhưng chưa sinh được init.yml: %s' % data.feedback)
    return data
