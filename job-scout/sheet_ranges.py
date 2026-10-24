"""Extend the existing Job List layout without moving rows or copying values."""
from copy import deepcopy
import re

FORMULA_COLUMNS = {'Ready to Apply?', 'Create Resume', 'Enough Data', '# Words',
                   '# Job Desc Words', '# (Gecko) Words', '# (FC) Job Desc Words', 'Total Words'}
METADATA = 'sheets(properties,basicFilter,filterViews,conditionalFormats,bandedRanges,tables)'
CELL_FIELDS = 'sheets(data(startRow,startColumn,rowData(values(userEnteredValue,userEnteredFormat,dataValidation))))'


def shift_formula(formula, delta):
    """Translate relative A1 row references, leaving strings/absolute rows intact."""
    pieces = re.split(r'("(?:[^"]|"")*"|\'(?:[^\']|\'\')*\')', formula)
    def row(absolute, number):
        shifted = int(number) if absolute else int(number) + delta
        if shifted < 1:
            raise ValueError('Formula reference would leave the Sheet')
        return absolute + str(shifted)
    for index in range(0, len(pieces), 2):
        value = re.sub(r'(?<![\w$])(\$?)(\d+):(\$?)(\d+)(?!\w)',
                       lambda m: row(m[1], m[2]) + ':' + row(m[3], m[4]), pieces[index])
        value = re.sub(r'(?<![\w$])(\$?[A-Za-z]{1,3})(\$?)([1-9]\d*)\b(?!\s*\()',
                       lambda m: m[1] + row(m[2], m[3]), value)
        pieces[index] = value
    return ''.join(pieces)


def _extend_range(value, end_row, width, boundary, old_width):
    result = deepcopy(value)
    if result.get('startRowIndex', 0) <= 1 and result.get('endRowIndex', end_row) >= boundary:
        if 'endRowIndex' in result:
            result['endRowIndex'] = max(result['endRowIndex'], end_row)
        if (result.get('startColumnIndex', 0) == 0 and 'endColumnIndex' in result
                and result['endColumnIndex'] >= old_width):
            result['endColumnIndex'] = max(result['endColumnIndex'], width)
    return result


def _boundary(sheet, formula_rows, last):
    # A removed filter stays removed. The last established formula row still
    # identifies newly appended rows that need the existing row structure.
    end = sheet.get('basicFilter', {}).get('range', {}).get('endRowIndex')
    if end is not None:
        return end
    return max((n for n, row in formula_rows
                if any(str(row.get(h, '')).startswith('=') for h in FORMULA_COLUMNS)), default=last)


def _formula_gaps(formula_rows):
    """Repair blanks only after a genuine formula exemplar in that named field.

    An unrelated formula reaching the bottom must not hide gaps in another
    column. Literal Yes/No decisions and manually supplied counts are preserved.
    """
    seeded, missing = set(), set()
    for number, row in sorted(formula_rows):
        if not str(row.get('ID', row.get('Scout ID', ''))).isdigit():
            continue
        for header in FORMULA_COLUMNS:
            value = row.get(header, '')
            if str(value).startswith('='):
                seeded.add(header)
            elif header in seeded and value in ('', None):
                missing.add(number)
    return missing


def plan_ranges(sheet, headers, formula_rows, cells, appended_rows=()):
    """Pure planner. Only tail rows inherit structure; literals are never copied."""
    sheet_id = sheet['properties']['sheetId']
    jobs = [(n, r) for n, r in formula_rows if str(r.get('ID', r.get('Scout ID', ''))).isdigit()]
    if not jobs:
        return [], {}
    last = max(n for n, _ in jobs)
    width = len(headers)
    basic = sheet.get('basicFilter')
    boundary = _boundary(sheet, formula_rows, last)
    old_width = (basic or {}).get('range', {}).get('endColumnIndex', width)
    targets = {n for n, _ in jobs if n > boundary} | set(appended_rows) | _formula_gaps(formula_rows)
    targets &= {n for n, _ in jobs}
    requests, expected = [], {}
    if basic:
        extended = deepcopy(basic)
        extended['range'] = _extend_range(basic['range'], last, width, boundary, old_width)
        if extended != basic:
            requests.append({'setBasicFilter': {'filter': extended}})
    for view in sheet.get('filterViews', []):
        if 'range' not in view:
            continue
        extended = _extend_range(view['range'], last, width, boundary, old_width)
        if extended != view['range']:
            requests.append({'updateFilterView': {'filter': {'filterViewId': view['filterViewId'], 'range': extended}, 'fields': 'range'}})
    for index, rule in enumerate(sheet.get('conditionalFormats', [])):
        updated = deepcopy(rule)
        updated['ranges'] = [_extend_range(r, last, width, boundary, old_width) for r in rule['ranges']]
        if updated != rule:
            requests.append({'updateConditionalFormatRule': {'sheetId': sheet_id, 'index': index, 'rule': updated}})
    for band in sheet.get('bandedRanges', []):
        extended = _extend_range(band['range'], last, width, boundary, old_width)
        if extended != band['range']:
            requests.append({'updateBanding': {'bandedRange': {'bandedRangeId': band['bandedRangeId'], 'range': extended}, 'fields': 'range'}})
    for table in sheet.get('tables', []):
        extended = _extend_range(table['range'], last, width, boundary, old_width)
        if extended != table['range']:
            requests.append({'updateTable': {'table': {'tableId': table['tableId'], 'range': extended}, 'fields': 'range'}})
    if not targets:
        return requests, expected
    first = min(targets)
    template = max((n for n, _ in jobs if n < first), default=0)
    for row in sorted(targets):
        for column, header in enumerate(headers):
            cell = cells.get((row, column), {})
            value, fields = {}, []
            if header in FORMULA_COLUMNS and not cell.get('userEnteredValue'):
                seeds = [(n, r.get(header, '')) for n, r in formula_rows
                         if n < row and str(r.get(header, '')).startswith('=')]
                if seeds:
                    source_row, formula = max(seeds)
                    if 'ARRAYFORMULA(' in formula.upper():
                        raise ValueError('Array formula extension requires review')
                    translated = shift_formula(formula, row-source_row)
                    from description_columns import DESCRIPTION_COLUMNS, description_word_count_formula
                    if (header == '# Job Desc Words'
                            and {h.casefold() for h in DESCRIPTION_COLUMNS}.issubset({h.casefold() for h in headers})):
                        translated = description_word_count_formula(row)
                    value['userEnteredValue'] = {'formulaValue': translated}
                    fields.append('userEnteredValue')
            source = cells.get((template, column), {})
            # Fill missing format properties, retaining destination overrides.
            for key, item in source.get('userEnteredFormat', {}).items():
                if key not in cell.get('userEnteredFormat', {}):
                    value.setdefault('userEnteredFormat', {})[key] = deepcopy(item)
                    fields.append('userEnteredFormat.' + key)
            validation = source.get('dataValidation')
            if (validation and not cell.get('dataValidation')
                    and validation.get('condition', {}).get('type') in {'BOOLEAN', 'ONE_OF_LIST'}):
                value['dataValidation'] = deepcopy(validation)
                fields.append('dataValidation')
            if fields:
                requests.append({'updateCells': {'range': {'sheetId': sheet_id,
                    'startRowIndex': row-1, 'endRowIndex': row, 'startColumnIndex': column, 'endColumnIndex': column+1},
                    'rows': [{'values': [value]}], 'fields': ','.join(fields)}})
                expected[row, column] = value
    return requests, expected


def extend_job_list(remote, tab, appended_rows=()):
    """Caller holds Gecko's writer lock. Preserve filter criteria and formulas."""
    from google_tracker import _col
    def metadata():
        result = remote.api.get(spreadsheetId=remote.config.spreadsheet_id, fields=METADATA).execute()
        return next(s for s in result['sheets'] if s['properties']['sheetId'] == tab.sheet_id)
    before = metadata()
    headers = list(tab.header_values)
    while headers and not headers[-1]:
        headers.pop()
    if not headers or len(set(headers)) != len(headers):
        raise ValueError('Job List needs unique named headers before extending ranges')
    formula_tab = remote.tab(tab.title, value_render_option='FORMULA')
    last = max((n for n, r in formula_tab.rows if str(r.get('ID', r.get('Scout ID', ''))).isdigit()), default=1)
    boundary = _boundary(before, formula_tab.rows, last)
    targets = [boundary+1, *appended_rows, *_formula_gaps(formula_tab.rows)]
    first = min(targets)
    template = max((n for n, _ in formula_tab.rows if n < first), default=1)
    address = "'Job List'!A" + str(template) + ':' + _col(len(headers)) + str(last)
    def read_cells():
        result = remote.api.get(spreadsheetId=remote.config.spreadsheet_id, ranges=[address],
                                includeGridData=True, fields=CELL_FIELDS).execute()
        cells = {}
        for sheet in result.get('sheets', []):
            for data in sheet.get('data', []):
                for offset, row in enumerate(data.get('rowData', [])):
                    for col, value in enumerate(row.get('values', [])):
                        cells[data.get('startRow', 0)+offset+1, data.get('startColumn', 0)+col] = value
        return cells
    cells = read_cells() if first <= last else {}
    requests, expected = plan_ranges(before, headers, formula_tab.rows, cells, appended_rows)
    if not requests:
        return {'requests': 0, 'formulas_filled': 0}
    if metadata() != before or (cells and read_cells() != cells):
        raise RuntimeError('Sheet layout or cells changed while extending ranges; retry safely')
    remote.api.batchUpdate(spreadsheetId=remote.config.spreadsheet_id, body={'requests': requests}).execute()
    after = metadata()
    for request in requests:
        if 'setBasicFilter' in request:
            if after.get('basicFilter') != request['setBasicFilter']['filter']:
                raise RuntimeError('Filter range or criteria readback failed')
        elif 'updateFilterView' in request:
            intended = request['updateFilterView']['filter']
            found = next(v for v in after['filterViews'] if v['filterViewId'] == intended['filterViewId'])
            if found['range'] != intended['range']:
                raise RuntimeError('Filter view extension readback failed')
        elif 'updateConditionalFormatRule' in request:
            intended = request['updateConditionalFormatRule']
            if after['conditionalFormats'][intended['index']] != intended['rule']:
                raise RuntimeError('Conditional formatting extension readback failed')
        elif 'updateBanding' in request:
            intended = request['updateBanding']['bandedRange']
            found = next(v for v in after['bandedRanges'] if v['bandedRangeId'] == intended['bandedRangeId'])
            if found['range'] != intended['range']:
                raise RuntimeError('Banding extension readback failed')
        elif 'updateTable' in request:
            intended = request['updateTable']['table']
            found = next(v for v in after['tables'] if v['tableId'] == intended['tableId'])
            if found['range'] != intended['range']:
                raise RuntimeError('Table extension readback failed')
    actual = read_cells() if expected else {}
    for key, value in expected.items():
        for field, content in value.items():
            saved = actual.get(key, {}).get(field)
            if field == 'userEnteredFormat':
                if any((saved or {}).get(k) != v for k, v in content.items()):
                    raise RuntimeError('New-row formatting readback failed')
            elif saved != content:
                raise RuntimeError('New-row formula or validation readback failed')
    return {'requests': len(requests), 'formulas_filled': sum('userEnteredValue' in v for v in expected.values())}
