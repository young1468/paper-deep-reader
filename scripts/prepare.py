"""Extract a local article into an editable, provenance-preserving reading draft."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import shutil
import statistics
import sys


def normalize(text):
    return re.sub(r'\s+', ' ', text.replace('\u00ad', '')).strip()


class Draft:
    def __init__(self, title):
        self.data = {'schema_version': 2, 'title': title, 'source': {}, 'notes': [],
                     'warnings': [], 'overview': [], 'glossary': [], 'parts': [],
                     'research_focus':'', 'research_card':{}, 'visuals':[]}
        self.current = None
        self.counter = 0
        self.math_counter = 0
        self.reference_section = False

    def heading(self, title, level=2):
        self.current = {'id': f's{len(self.data["parts"])+1:03d}', 'title': title,
                        'title_zh': '', 'level': level, 'guide': '', 'paragraphs': []}
        self.reference_section = bool(re.search(
            r'^(?:\d+\s+)?(?:references|bibliography|acknowledg\w*|author contributions|参考文献|致谢)\b', title, re.I))
        self.data['parts'].append(self.current)

    def add(self, text, pages=None, protected=None, kind='paragraph', visual_kind=''):
        text = normalize(text)
        if not text:
            return
        if self.current is None:
            self.heading('正文 / Article')
        self.counter += 1
        uid = f'p{self.counter:05d}'
        refs = protected or {}
        text = re.sub(r'\$\$[\s\S]+?\$\$|\\\([\s\S]+?\\\)|\$(?!\s)[^$\n]+?(?<!\s)\$',
                      lambda m: self.math(refs, m.group()), text)
        # Narrative names and author-year citations are retained verbatim.
        def protect(match):
            key = f'C{len(refs)+1}'
            while key in refs:
                key = f'C{int(key[1:])+1}'
            refs[key] = {'kind': 'citation', 'text': match.group()}
            return f'[[{key}]]'
        text = re.sub(r'\([^()]{0,180}\b(?:19|20)\d{2}[a-z]?[^()]{0,180}\)', protect, text)
        text = re.sub(r'\b[A-Z][A-Za-z-]+(?:\s+(?:and|&)\s+[A-Z][A-Za-z-]+)?\s+et\s+al\.', protect, text)
        self.current['paragraphs'].append({
            'id': uid, 'source_ids': [uid],
            'kind': 'reference' if self.reference_section else kind,
            'original': text, 'translation': '', 'explanation': '', 'terms': [],
            'pages': pages or [], 'protected': refs, 'analysis':[], 'review':{}})
        if visual_kind:
            self.current['paragraphs'][-1]['visual_kind']=visual_kind

    def math(self, refs, text, **extra):
        self.math_counter += 1
        key = f'M{self.math_counter}'
        refs[key] = {'kind': 'math', 'text': text, **extra}
        return f'[[{key}]]'


def read_html(path, draft):
    try:
        from lxml import html, etree
    except ImportError:
        raise ValueError('HTML 提取需要 lxml；请使用已有依赖环境或安装 lxml。')
    doc = html.fromstring(path.read_bytes())
    containers = doc.xpath('//article') or doc.xpath('//main') or doc.xpath('//body') or [doc]
    article = containers[0]
    title = article.xpath('.//h1') or doc.xpath('//title')
    if title and not draft.data['title']:
        draft.data['title'] = normalize(title[0].text_content())
    excluded = {'script', 'style', 'nav', 'footer', 'form', 'noscript'}
    for el in article.iter():
        if not isinstance(el.tag, str):
            continue
        ancestors = list(el.iterancestors())
        if el.tag in excluded or any(a.tag in excluded for a in ancestors):
            continue
        if any(a.tag in ('p', 'li', 'table', 'figure', 'pre') for a in ancestors):
            continue
        if re.fullmatch(r'h[2-6]', el.tag):
            draft.heading(normalize(el.text_content()), 2 if el.tag == 'h2' else 3)
        elif el.tag in ('p', 'li', 'blockquote', 'table', 'figure', 'pre', 'math'):
            if el.tag == 'blockquote' and el.xpath('.//p'):
                continue
            refs = {}
            def walk(node):
                tag = node.tag.split('}')[-1] if isinstance(node.tag, str) else ''
                if tag in excluded or tag.startswith('annotation'):
                    return ''
                if tag == 'math':
                    return draft.math(refs, node.get('alttext', normalize(node.text_content())),
                                      mathml=etree.tostring(node, encoding='unicode', with_tail=False))
                if tag == 'cite':
                    key = f'C{len(refs)+1}'
                    refs[key] = {'kind': 'citation', 'text': normalize(node.text_content())}
                    return f'[[{key}]]'
                text = node.text or ''
                for child in node:
                    piece=walk(child)
                    if child.tag in ('tr','td','th','caption','figcaption','div','p','li'):
                        piece=' '+piece+' '
                    text += piece + (child.tail or '')
                return text
            text = walk(el)
            kind = 'reference' if el.tag in ('table', 'figure', 'pre', 'math') else 'paragraph'
            if any(re.search(r'bibliography|references|acknowledg', a.get('class', ''), re.I) for a in ancestors):
                kind = 'reference'
            draft.add(text, protected=refs, kind=kind,
                      visual_kind={'table':'table','figure':'figure','math':'formula'}.get(el.tag,''))


def read_text(path, draft):
    lines = path.read_text(encoding='utf-8-sig').splitlines()
    pending = []
    fence = None
    def flush(kind='paragraph'):
        if pending:
            draft.add(' '.join(pending), kind=kind)
            pending.clear()
    for line in lines + ['']:
        s = line.strip()
        if s.startswith(('```', '~~~')) or s == '$$':
            if fence is None:
                flush(); fence = s[:3] if s != '$$' else '$$'
            elif s.startswith(fence):
                flush('reference'); fence = None
            continue
        if fence:
            pending.append(line)
            continue
        heading = re.match(r'^(#{1,6})\s+(.*)', s)
        if heading:
            flush()
            if len(heading[1]) == 1 and not draft.data['title']:
                draft.data['title'] = heading[2]
            else:
                draft.heading(heading[2], 2 if len(heading[1]) <= 2 else 3)
        elif not s:
            flush()
        else:
            pending.append(s)
    if fence:
        flush('reference')
        draft.data['warnings'].append('原文有未闭合的代码/数学围栏，请核对。')


def word_rows(words):
    rows = []
    for w in sorted(words, key=lambda x: (round(x['top']/3), x['x0'])):
        if not rows or abs(w['top'] - statistics.median(x['top'] for x in rows[-1])) > 3:
            rows.append([w])
        else:
            rows[-1].append(w)
    return [sorted(row, key=lambda w: w['x0']) for row in rows]


def columns(words, width, height):
    """Use a persistent central gutter, not a fixed paper-specific crop."""
    rows = word_rows(words)
    # The two columns need not share baselines. Count gutter occupancy by words.
    sample = [w for w in words if height*.72<w['top']<height*.94]
    if len(sample)<60:
        return [rows], False
    candidates = [width*f/100 for f in range(43,58)]
    occupancy = lambda x: sum(w['x0']<x+4 and w['x1']>x-4 for w in sample)
    center = min(candidates,key=lambda x:(occupancy(x),abs(x-width/2)))
    left_count = sum(w['x1']<center for w in sample)
    right_count = sum(w['x0']>center for w in sample)
    if occupancy(center)>max(1,len(sample)*.008) or min(left_count,right_count)<len(sample)*.2:
        return [rows], False
    crossing = [r for r in rows if r[0]['top']<height*.7
                and any(w['x0']<center+4 and w['x1']>center-4 for w in r)]
    cut = max((max(w['bottom'] for w in r) for r in crossing), default=0)
    top = [w for w in words if w['top']<cut]
    body = [w for w in words if w['top']>=cut]
    left = [w for w in body if (w['x0']+w['x1'])/2<center]
    right = [w for w in body if (w['x0']+w['x1'])/2>=center]
    return [word_rows(top), word_rows(left), word_rows(right)], True


def read_pdf(path, draft):
    try:
        import pdfplumber
    except ImportError:
        raise ValueError('PDF 提取需要 pdfplumber；请使用已有依赖环境或安装 pdfplumber。')
    pending = []
    pages = []
    refs = {}
    def flush():
        nonlocal refs
        if pending:
            draft.add(' '.join(pending), sorted(set(pages)), refs)
            pending.clear(); pages.clear(); refs = {}
    with pdfplumber.open(path) as pdf:
        page_words = [[w for w in p.extract_words(x_tolerance=2, y_tolerance=3, extra_attrs=['fontname', 'size'])
                       if w.get('upright',True) and w['x0']>p.width*.03 and w['x1']<p.width*.98] for p in pdf.pages]
        if sum(len(w) for w in page_words)<25:
            raise ValueError('PDF 文字层不足：请先 OCR；没有生成可读正文。')
        edges = Counter()
        for p, words in zip(pdf.pages, page_words):
            for row in word_rows(words):
                if row[0]['top']<50 or row[0]['top']>p.height-45:
                    text = normalize(' '.join(w['text'] for w in row))
                    edges[text] += 1
        repeated = {t for t,n in edges.items() if n>=max(2, len(pdf.pages)//3)}
        sizes = [w['size'] for words in page_words for w in words if len(w['text'])>2]
        body_size = statistics.median(sizes)
        two_column_pages = []
        for pn, (p, words) in enumerate(zip(pdf.pages, page_words), 1):
            if len(words)<12:
                draft.data['warnings'].append(f'第 {pn} 页文字很少，需判断是整页图表还是需 OCR。')
            groups, is_two = columns(words, p.width, p.height)
            if is_two:
                two_column_pages.append(pn)
            if pn==1 and not draft.data['title']:
                large = [r for r in word_rows(words) if r[0]['top']<p.height*.35
                         and statistics.median(w['size'] for w in r)>body_size*1.35]
                draft.data['title'] = re.sub(r'\b([A-Z]) ([A-Z]{2,})\b', r'\1\2', normalize(' '.join(w['text'] for r in large for w in r)))
            for rows in groups:
                prev = None
                for row in rows:
                    text = normalize(' '.join(w['text'] for w in row))
                    top, bottom = min(w['top'] for w in row), max(w['bottom'] for w in row)
                    if ((top<50 or bottom>p.height-45) and text in repeated) or (
                        re.fullmatch(r'\d+', text) and (top<40 or bottom>p.height-40)):
                        continue
                    size = statistics.median(w['size'] for w in row)
                    caption=re.match(r'^(Figure|Fig\.|Table)\s+\d+',text,re.I)
                    if caption:
                        flush();draft.add(text,[pn],kind='reference',visual_kind='table' if caption[1].lower()=='table' else 'figure');prev=None
                        continue
                    heading_title = re.sub(r'\b([A-Z]) ([A-Z]{2,})\b', r'\1\2', text)
                    heading = bool(re.match(r'^(?:\d+(?:\.\d+)*|[A-Z](?:\.\d+)*)\.?\s+[A-Z\u4e00-\u9fff]', heading_title))
                    named = bool(re.fullmatch(r'abstract|references|bibliography|conclusions?|introduction|摘要|参考文献', heading_title, re.I))
                    if len(text)<145 and (named or (heading and size>=body_size*.98) or size>body_size*1.2):
                        flush(); draft.heading(heading_title, 3 if re.match(r'^[A-Z0-9]+\.', text) else 2); prev=None
                        continue
                    math_words = [w for w in row if re.search(r'(^|[+-])CM(?:MI|SY|EX)\d|(^|[+-])MS[AB]M\d|Math|Symbol', w['fontname'], re.I)]
                    # Keep independent math out of prose translation. The PDF remains authoritative.
                    if math_words and sum(len(w['text']) for w in math_words) > max(3, len(text)*.35):
                        flush(); draft.add(text, [pn], kind='reference',visual_kind='formula'); prev=None
                        continue
                    if prev:
                        gap = top-prev[1]
                        indent = row[0]['x0']-prev[0]
                        if gap>max(4, body_size*.6) or (indent>7 and pending and re.search(r'[.!?。！？]$', pending[-1])):
                            flush()
                    # Inline math uses stable tokens, never translation input as broken prose.
                    bits = []
                    for w in row:
                        if w in math_words:
                            bits.append(draft.math(refs, w['text']))
                        else:
                            bits.append(w['text'])
                    line = normalize(' '.join(bits))
                    if pending and re.search(r'[A-Za-z]-$', pending[-1]) and re.match(r'^[a-z]', line):
                        pending[-1] = pending[-1][:-1] + line
                    else:
                        pending.append(line)
                    pages.append(pn)
                    prev = (row[0]['x0'], bottom)
                # A column or page break alone never ends an unfinished sentence.
                if pending and re.search(r'[.!?。！？][”\"]?$', pending[-1]):
                    flush()
        flush()
        draft.data['warnings'].append('PDF 标题、自然段、公式字体为启发式提取；需对照原页审查，复杂公式以 PDF 为准。')
        if two_column_pages:
            draft.data['warnings'].append('检测为双栏的页码：'+', '.join(map(str, two_column_pages)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--title', default='')
    parser.add_argument('--source-url', default='')
    args = parser.parse_args()
    path = args.input.resolve()
    if not path.is_file():
        parser.error('输入必须是已存在的本地文件；链接请先获取正文并保存。')
    suffix = path.suffix.lower()
    if suffix not in ('.pdf', '.html', '.htm', '.md', '.markdown', '.txt'):
        parser.error('支持 PDF、HTML、Markdown、TXT。')
    if args.out.exists():
        parser.error('输出目录已存在。请选新目录；更新旧阅读包时直接编辑 reading.json。')
    draft = Draft(args.title)
    try:
        if suffix == '.pdf': read_pdf(path, draft)
        elif suffix in ('.html', '.htm'): read_html(path, draft)
        else: read_text(path, draft)
    except ValueError as exc:
        parser.error(str(exc))
    if not draft.counter:
        parser.error('没有提取到正文，未创建阅读包。')
    draft.data['title'] = draft.data['title'] or path.stem
    draft.data['source'] = {'file': '原文'+suffix, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                            'url': args.source_url, 'version': ''}
    args.out.mkdir(parents=True)
    shutil.copyfile(path, args.out / ('原文'+suffix))
    for name in ('source.json', 'reading.json'):
        (args.out/name).write_text(json.dumps(draft.data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'output': str(args.out.resolve()), 'paragraphs': draft.counter,
                      'warnings': draft.data['warnings'], 'next': '完成 reading.json 的翻译、详细解读、图表和阅读卡片，运行 audit.py 并完成第二轮审校后运行 render.py'}, ensure_ascii=False))


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    main()
