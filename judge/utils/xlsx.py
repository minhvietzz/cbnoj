"""A tiny .xlsx writer (one sheet, text and numbers, bold header row) built on zipfile, so no extra dependency."""
import io
import re
import zipfile
from xml.sax.saxutils import escape

CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/styles.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    '</Types>'
)
ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
    'Target="xl/workbook.xml"/></Relationships>'
)
WORKBOOK = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets><sheet name="%s" sheetId="1" r:id="rId1"/></sheets></workbook>'
)
WORKBOOK_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    'Target="worksheets/sheet1.xml"/>'
    '<Relationship Id="rId2" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    '</Relationships>'
)
STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '</fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
    '</styleSheet>'
)
# Characters XML 1.0 cannot carry (control characters other than tab, newline, carriage return).
ILLEGAL = re.compile('[\x00-\x08\x0b\x0c\x0e-\x1f]')


def column_name(index):
    name = ''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        name = chr(65 + rest) + name
    return name


def cell(row, col, value, bold=False):
    ref = '%s%d' % (column_name(col), row)
    style = ' s="1"' if bold else ''
    if isinstance(value, bool):
        value = 'yes' if value else ''
    if isinstance(value, (int, float)):
        return '<c r="%s"%s><v>%s</v></c>' % (ref, style, repr(value))
    text = escape(ILLEGAL.sub('', '' if value is None else str(value)))
    return '<c r="%s"%s t="inlineStr"><is><t xml:space="preserve">%s</t></is></c>' % (ref, style, text)


def build_xlsx(header, rows, sheet_name='Sheet1'):
    """header: list of column titles; rows: list of lists. Returns the bytes of a valid .xlsx file."""
    sheet_name = escape(re.sub(r'[\[\]:*?/\\]', ' ', sheet_name)[:31] or 'Sheet1', {'"': '&quot;'})
    body = []
    for number, values in enumerate([header] + list(rows), 1):
        cells = ''.join(cell(number, col, value, bold=number == 1) for col, value in enumerate(values))
        body.append('<row r="%d">%s</row>' % (number, cells))
    widths = ''.join('<col min="%d" max="%d" width="%d" customWidth="1"/>' % (i + 1, i + 1, max(10, min(40, len(str(h)) + 4)))  # noqa: E501
                     for i, h in enumerate(header))
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<cols>%s</cols><sheetData>%s</sheetData></worksheet>') % (widths, ''.join(body))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', CONTENT_TYPES)
        archive.writestr('_rels/.rels', ROOT_RELS)
        archive.writestr('xl/workbook.xml', WORKBOOK % sheet_name)
        archive.writestr('xl/_rels/workbook.xml.rels', WORKBOOK_RELS)
        archive.writestr('xl/styles.xml', STYLES)
        archive.writestr('xl/worksheets/sheet1.xml', sheet)
    return buffer.getvalue()


def read_rows(data):
    """Read the first sheet of an .xlsx file into a list of rows (lists of strings).

    Only plain cell values are supported (numbers, text, shared strings, inline strings), which is all a class list
    needs. Raises ValueError when the file is not a readable workbook.
    """
    import xml.etree.ElementTree as ET
    ns = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        shared = []
        if 'xl/sharedStrings.xml' in names:
            for si in ET.fromstring(zf.read('xl/sharedStrings.xml')).findall('m:si', ns):
                shared.append(''.join(t.text or '' for t in si.iter('{%s}t' % ns['m'])))
        sheets = sorted(n for n in names if re.match(r'xl/worksheets/sheet\d+\.xml$', n))
        if not sheets:
            raise ValueError('no sheet')
        root = ET.fromstring(zf.read(sheets[0]))
    except (zipfile.BadZipFile, ET.ParseError, KeyError) as e:
        raise ValueError(str(e))

    def column(ref):
        letters = re.match(r'[A-Z]+', ref).group(0)
        n = 0
        for ch in letters:
            n = n * 26 + ord(ch) - 64
        return n - 1

    rows = []
    for row in root.iter('{%s}row' % ns['m']):
        cells = {}
        for c in row.findall('m:c', ns):
            ref = c.get('r') or ''
            if not ref:
                continue
            kind = c.get('t')
            if kind == 'inlineStr':
                text = ''.join(t.text or '' for t in c.iter('{%s}t' % ns['m']))
            else:
                v = c.find('m:v', ns)
                text = (v.text or '') if v is not None else ''
                if kind == 's' and text.isdigit() and int(text) < len(shared):
                    text = shared[int(text)]
                elif kind != 's' and text.endswith('.0'):
                    text = text[:-2]
            cells[column(ref)] = text.strip()
        if cells:
            rows.append([cells.get(i, '') for i in range(max(cells) + 1)])
    return rows
