import base64
import html as _html_mod
import re
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, Signal, Slot, QUrl
from PySide6.QtGui import QIcon, QPixmap, QTextCursor, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from horizon import theme as _theme
from horizon.image import ImageRepository

_PLUS_ICON: QIcon | None = None
_PLUS_ICON_SIZE = QSize(12, 12)


def _plus_icon() -> QIcon:
    global _PLUS_ICON
    if _PLUS_ICON is None:
        _PLUS_ICON = _theme.make_icon(":/icons/plus_cyan.svg", _PLUS_ICON_SIZE)
    return _PLUS_ICON


_JETBRAINS_MONO_URL       = (Path(__file__).parent.parent / "resources" / "JetBrainsMono-Regular.ttf").as_uri()
_MERMAID_JS_URL           = (Path(__file__).parent.parent / "resources" / "mermaid.min.js").as_uri()
_HIGHLIGHT_JS_URL         = (Path(__file__).parent.parent / "resources" / "highlight.min.js").as_uri()
_HIGHLIGHT_CSHARP_URL     = (Path(__file__).parent.parent / "resources" / "highlight-csharp.min.js").as_uri()
_HIGHLIGHT_DOCKERFILE_URL = (Path(__file__).parent.parent / "resources" / "highlight-dockerfile.min.js").as_uri()
_HIGHLIGHT_POWERSHELL_URL = (Path(__file__).parent.parent / "resources" / "highlight-powershell.min.js").as_uri()
_HIGHLIGHT_CSS_LIGHT_URL  = (Path(__file__).parent.parent / "resources" / "highlight-light.min.css").as_uri()
_HIGHLIGHT_CSS_DARK_URL   = (Path(__file__).parent.parent / "resources" / "highlight-dark.min.css").as_uri()
_RESOURCES_BASE_URL       = QUrl((Path(__file__).parent.parent / "resources" / "").as_uri())

_TAG_RE    = re.compile(r'\{#([A-Za-z0-9_\-]+)\}')
_TAG_PH_RE = re.compile(r'HORIZONTAG(\d+)END')

_MERMAID_FENCE_RE = re.compile(
    r'^[ \t]*```[ \t]*mermaid[^\n]*\n(.*?)^[ \t]*```[ \t]*$',
    re.MULTILINE | re.DOTALL,
)
_MERMAID_PH_RE = re.compile(r'HORIZONMERMAID(\d+)END')

_CODE_FENCE_RE = re.compile(
    r'^[ \t]*(`{3,}|~{3,})([^\n]*)\n(.*?)^\1[ \t]*$',
    re.MULTILINE | re.DOTALL,
)
_CODE_PH_RE = re.compile(r'HORIZONCODEBLOCK(\d+)END')

_MD_IMG_RE  = re.compile(r'!\[([^\]]*)\]\(horizon-image://(\d+)\)')
_HTML_PH_RE = re.compile(r'HORIZONIMG(\d+)END')

_WIKILINK_RE = re.compile(
    r'\[\[(\d+)\|([^\]]+)\]\]'   # [[42|Texte]] : group 1=id, group 2=label
    r'|\[\[(\d+)\]\]'             # [[42]]       : group 3=id
    r'|\[\[([^\]]+)\]\]'          # [[Titre]]    : group 4=title
)
_WIKILINK_PH_RE = re.compile(r'HORIZONWIKILINK(\d+)END')

# Blockquote extraction: one or more "> …" lines + optional {.is-TYPE} annotation
_BQ_EXTRACT_RE   = re.compile(
    r'((?:^[ \t]*>[ \t]?[^\n]*\n?)+)(?:\{\.is-(info|success|warning|danger)\}[ \t]*\n?)?',
    re.MULTILINE,
)
_BQ_GT_PREFIX_RE = re.compile(r'^[ \t]*>[ \t]?', re.MULTILINE)
# Strip Qt inline styles from <p> so our CSS rules apply (used on both full and inner HTML)
_BLOCK_STYLE_RE  = re.compile(r'(<(?:p|blockquote)\b[^>]*?) style="[^"]*"')
# Locate <body>…</body> in Qt's full HTML output
_QT_BODY_RE      = re.compile(r'<body[^>]*>(.*)</body>', re.DOTALL | re.IGNORECASE)
# Detect lines that begin a block-level element (must not receive a line-break marker)
_BLOCK_LINE_RE   = re.compile(r'^(#{1,6} |> ?|[-*+] |\d+\. |    |\t|```|~~~|\|)')
# Detect standalone horizontal-rule lines (---, ***, ___, with optional spaces)
_HR_LINE_RE      = re.compile(r'^[-*_](\s*[-*_]){2,}\s*$')

# Footnote inline reference: [^label] — but not [^label]: (definition)
_FOOTNOTE_REF_RE = re.compile(r'\[\^([A-Za-z0-9_-]+)\](?!\:)')
# Footnote definition: [^label]: text, with optional indented continuation lines
_FOOTNOTE_DEF_RE = re.compile(
    r'^\[\^([A-Za-z0-9_-]+)\]:\s*(.*(?:\n(?:    |\t)[^\n]*)*)',
    re.MULTILINE,
)

# HTML block extraction: tag opening at the start of a line
_HTML_BLOCK_OPEN_RE = re.compile(r'^[ \t]*<([A-Za-z][A-Za-z0-9\-]*)', re.MULTILINE)
_HTML_BLOCK_PH_RE   = re.compile(r'HORIZONHTMLBLOCK(\d+)END')

_HTML_VOID_ELEMENTS = frozenset({
    'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
    'link', 'meta', 'param', 'source', 'track', 'wbr',
})


def _make_preview_html() -> str:
    t = _theme.current()
    _mermaid_theme = "default" if t.name == "light" else "dark"
    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  @font-face {{
    font-family: 'JetBrains Mono';
    src: url('{_JETBRAINS_MONO_URL}');
    font-weight: normal;
    font-style: normal;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: '{t.font_family}', sans-serif;
    font-size: 13px; line-height: 1.6; color: {t.preview_text};
    background: {t.preview_bg}; padding: 16px 24px; max-width: 860px;
  }}
  h1, h2, h3, h4, h5, h6 {{ margin-top: 1.2em; margin-bottom: 0.4em; font-weight: 600; }}
  h1 {{ font-size: 1.75em; border-bottom: 1px solid {t.preview_border}; padding-bottom: 0.2em; }}
  h2 {{ font-size: 1.4em; border-bottom: 1px solid {t.preview_border}; padding-bottom: 0.15em; }}
  p {{ margin-bottom: 0.8em !important; }}
  ul, ol {{ padding-left: 1.5em; margin-bottom: 0.8em; }}
  li {{ margin-bottom: 0.2em; }}
  code {{ font-family: 'JetBrains Mono', monospace; background: {t.preview_code_bg}; border-radius: 3px; padding: 0.1em 0.35em; font-size: 0.9em; }}
  pre {{ background: {t.preview_code_bg}; border-radius: 4px; padding: 12px 16px; overflow-x: auto; margin-bottom: 0.8em; }}
  pre code {{ background: none; padding: 0; }}
  blockquote {{ border-left: 4px solid {t.preview_blockquote_border}; background: {t.preview_blockquote_bg}; margin-left: 0; padding: 0.6em 1em; color: {t.preview_blockquote_text}; margin-bottom: 0.8em; border-radius: 0 4px 4px 0; }}
  blockquote.bq-info    {{ border-left-color: #3b82f6; background: rgba(59,130,246,0.10); color: inherit; }}
  blockquote.bq-success {{ border-left-color: #22c55e; background: rgba(34,197,94,0.10);  color: inherit; }}
  blockquote.bq-warning {{ border-left-color: #f59e0b; background: rgba(245,158,11,0.10); color: inherit; }}
  blockquote.bq-danger  {{ border-left-color: #ef4444; background: rgba(239,68,68,0.10);  color: inherit; }}
  hr {{ border: none; border-top: 1px solid {t.preview_border}; margin: 1em 0; }}
  a {{ color: {t.preview_link}; }}
  table {{ border-collapse: collapse; margin-bottom: 0.8em; width: 100%; }}
  td {{ border: 1px solid {t.preview_border}; padding: 6px 12px; }}
  .mermaid-wrapper {{ margin-bottom: 0.8em; }}
  .mermaid-open-btn {{ display: inline-block; margin-bottom: 4px; cursor: pointer; background: {t.accent_color}22; border: 1px solid {t.accent_color}; color: {t.accent_color}; border-radius: 4px; padding: 2px 8px; font-size: 0.82em; font-family: inherit; }}
  .mermaid-open-btn:hover {{ background: {t.accent_color}44; }}
  .mermaid {{ overflow-x: auto; text-align: center; }}
  .mermaid svg {{ max-width: 100%; height: auto; }}
  .tag {{ display: inline-block; background-color: {t.accent_color}22; border: 1px solid {t.accent_color}; border-radius: 4px; padding: 1px 7px; color: {t.accent_color}; font-size: 0.85em; font-weight: 500; white-space: nowrap; }}
  a.note-link {{ color: {t.accent_color}; text-decoration: none; border-bottom: 1px dashed {t.accent_color}; }}
  a.note-link:hover {{ border-bottom-style: solid; }}
  .note-link-broken {{ color: {t.preview_text}; opacity: 0.45; text-decoration: line-through; cursor: default; font-style: italic; }}
  sup.footnote-ref a {{ color: {t.preview_link}; text-decoration: none; }}
  .footnotes {{ margin-top: 2em; font-size: 0.9em; opacity: 0.8; }}
  .footnotes hr.footnotes-sep {{ margin-bottom: 0.8em; }}
  .footnotes-list {{ padding-left: 1.5em; }}
  .footnotes-list li {{ margin-bottom: 0.4em; }}
  .footnote-backref {{ color: {t.preview_link}; text-decoration: none; margin-left: 0.3em; }}
</style>
<link rel="stylesheet" href="{_HIGHLIGHT_CSS_LIGHT_URL if t.name == 'light' else _HIGHLIGHT_CSS_DARK_URL}">
<style>
  pre code.hljs {{ background: transparent !important; padding: 0 !important; font-size: inherit; }}
</style>
<script src="{_MERMAID_JS_URL}"></script>
<script src="{_HIGHLIGHT_JS_URL}"></script>
<script src="{_HIGHLIGHT_CSHARP_URL}"></script>
<script src="{_HIGHLIGHT_DOCKERFILE_URL}"></script>
<script src="{_HIGHLIGHT_POWERSHELL_URL}"></script>
</head>
<body>
<div id="content"></div>
<script src="qrc:///qtwebchannel/qwebchannel.js"></script>
<script>
  mermaid.initialize({{ startOnLoad: false, theme: '{_mermaid_theme}', securityLevel: 'loose' }});
  var TABLE_HEADER_BG = '{t.preview_table_header_bg}';
  function styleTableHeaders() {{
    document.querySelectorAll('#content table').forEach(function(table) {{
      var firstRow = table.querySelector('tr');
      if (firstRow) {{
        firstRow.querySelectorAll('td').forEach(function(td) {{
          td.style.backgroundColor = TABLE_HEADER_BG;
          td.style.fontWeight = '600';
        }});
      }}
    }});
  }}
  function attachImageHandlers() {{
    document.querySelectorAll('#content img').forEach(function(img) {{
      if (img.dataset.zoomBound) return;
      img.dataset.zoomBound = '1';
      img.style.cursor = 'zoom-in';
      img.addEventListener('click', function() {{
        var src = img.getAttribute('src');
        if (src && src.startsWith('data:')) {{
          window.bridge.open_image(src);
        }}
      }});
    }});
  }}
  function attachLinkHandlers() {{
    document.querySelectorAll('#content a[href]').forEach(function(a) {{
      if (a.dataset.linkBound) return;
      a.dataset.linkBound = '1';
      a.addEventListener('click', function(e) {{
        e.preventDefault();
        window.bridge.open_link(a.getAttribute('href'));
      }});
    }});
  }}
  function applyHtml(html) {{
    var scrollY = window.scrollY;
    var doc = new DOMParser().parseFromString(html, 'text/html');
    document.getElementById('content').innerHTML = doc.body ? doc.body.innerHTML : html;
    styleTableHeaders();
    attachImageHandlers();
    attachLinkHandlers();
    document.querySelectorAll('#content pre code').forEach(function(el) {{
      hljs.highlightElement(el);
    }});
    function addMermaidButtons() {{
      document.querySelectorAll('#content .mermaid').forEach(function(div) {{
        if (div.dataset.btnBound) return;
        div.dataset.btnBound = '1';
        var source = div.dataset.mermaidSource || '';
        var wrapper = document.createElement('div');
        wrapper.className = 'mermaid-wrapper';
        div.parentNode.insertBefore(wrapper, div);
        wrapper.appendChild(div);
        var btn = document.createElement('button');
        btn.textContent = '⛶ Plein écran';
        btn.className = 'mermaid-open-btn';
        btn.addEventListener('click', function() {{
          window.bridge.open_mermaid(source);
        }});
        wrapper.insertBefore(btn, div);
      }});
    }}
    var nodes = document.getElementById('content').querySelectorAll('.mermaid');
    if (nodes.length > 0) {{
      mermaid.run({{ nodes: nodes }}).then(function() {{
        addMermaidButtons();
      }}).catch(function(err) {{
        console.warn('Mermaid render error:', err);
      }});
    }}
    requestAnimationFrame(function() {{
      window.scrollTo(0, scrollY);
    }});
  }}
  new QWebChannel(qt.webChannelTransport, function(channel) {{
    window.bridge = channel.objects.bridge;
    window.bridge.html_changed.connect(function(html) {{ applyHtml(html); }});
    window.bridge.get_current_html(function(html) {{ if (html) applyHtml(html); }});
  }});
</script>
</body>
</html>"""


def _add_hard_breaks(md: str) -> str:
    lines = md.split('\n')
    result = []
    in_fence = False

    for i, line in enumerate(lines):
        stripped = line.strip()

        if stripped.startswith('```') or stripped.startswith('~~~'):
            in_fence = not in_fence
            result.append(line)
            continue

        if in_fence or not stripped:
            result.append(line)
            continue

        if _BLOCK_LINE_RE.match(stripped) or _HR_LINE_RE.match(stripped):
            result.append(line)
            continue

        next_stripped = lines[i + 1].strip() if i + 1 < len(lines) else ''
        next_is_para  = (
            bool(next_stripped)
            and not _BLOCK_LINE_RE.match(next_stripped)
            and not _HR_LINE_RE.match(next_stripped)
        )

        result.append(line + ('HORIZONLBR' if next_is_para else ''))

    return '\n'.join(result)


def _extract_tags(md: str) -> tuple[str, list[str]]:
    tags: list[str] = []

    def replace(m: re.Match) -> str:
        idx = len(tags)
        tags.append(m.group(1))
        return f'HORIZONTAG{idx}END'

    return _TAG_RE.sub(replace, md), tags


def _inject_tags(html: str, tags: list[str]) -> str:
    for idx, name in enumerate(tags):
        placeholder = f'HORIZONTAG{idx}END'
        span = f'<span class="tag">#{name}</span>'
        html = html.replace(placeholder, span)
    return html


def _extract_wikilinks(
    md: str,
    title_to_id: dict[str, int],
    id_exists: set[int],
) -> tuple[str, list[str]]:
    links: list[str] = []

    def replace(m: re.Match) -> str:
        idx = len(links)
        if m.group(1) is not None:        # [[42|Texte]]
            note_id = int(m.group(1))
            label = m.group(2).strip()
        elif m.group(3) is not None:      # [[42]]
            note_id = int(m.group(3))
            label = f"#{note_id}"
        else:                             # [[Titre]]
            title = m.group(4)
            label = title
            # If multiple notes share the same title, the most recently inserted wins
            note_id = title_to_id.get(title.lower(), -1)

        if note_id > 0 and note_id in id_exists:
            html = (
                f'<a href="horizon://note/{note_id}" '
                f'class="note-link">{_html_mod.escape(label)}</a>'
            )
        else:
            html = f'<span class="note-link-broken">{_html_mod.escape(label)}</span>'

        links.append(html)
        return f'HORIZONWIKILINK{idx}END'

    return _WIKILINK_RE.sub(replace, md), links


def _inject_wikilinks(html: str, links: list[str]) -> str:
    def replace(m: re.Match) -> str:
        return links[int(m.group(1))]
    return _WIKILINK_PH_RE.sub(replace, html)


def _extract_blockquotes(md: str) -> tuple[str, list[tuple[list[str], str | None]]]:
    bq_list: list[tuple[list[str], str | None]] = []

    def replace(m: re.Match) -> str:
        idx    = len(bq_list)
        raw_bq = m.group(1)
        cls    = m.group(2)
        lines  = [
            _BQ_GT_PREFIX_RE.sub('', ln)
            for ln in raw_bq.rstrip('\n').split('\n')
        ]
        bq_list.append((lines, cls))
        return f'\nHORIZONBLOCKQUOTE{idx}END\n\n'

    return _BQ_EXTRACT_RE.sub(replace, md), bq_list


def _blockquote_inner_html(lines: list[str]) -> str:
    md = _add_hard_breaks('\n'.join(lines))
    doc = QTextDocument()
    doc.setMarkdown(md)
    raw = doc.toHtml()
    body = _QT_BODY_RE.search(raw)
    inner = body.group(1).strip() if body else '\n'.join(lines)
    inner = _BLOCK_STYLE_RE.sub(r'\1', inner)
    inner = inner.replace('HORIZONLBR ', '<br>').replace('HORIZONLBR', '<br>')
    return inner


def _inject_blockquotes(html: str, bq_list: list[tuple[list[str], str | None]]) -> str:
    for idx, (lines, cls) in enumerate(bq_list):
        placeholder = f'HORIZONBLOCKQUOTE{idx}END'
        inner       = _blockquote_inner_html(lines)
        cls_attr    = f' class="bq-{cls}"' if cls else ''
        bq_html     = f'<blockquote{cls_attr}>{inner}</blockquote>'
        html = re.sub(
            r'<p[^>]*>\s*' + re.escape(placeholder) + r'\s*</p>',
            bq_html,
            html,
            flags=re.IGNORECASE,
        )
        html = html.replace(placeholder, bq_html)
    return html


def _extract_mermaid(md: str) -> tuple[str, list[str]]:
    diagrams: list[str] = []

    def _replace(m: re.Match) -> str:
        idx = len(diagrams)
        diagrams.append(m.group(1))
        return f'\nHORIZONMERMAID{idx}END\n\n'

    return _MERMAID_FENCE_RE.sub(_replace, md), diagrams


def _extract_code_blocks(md: str) -> tuple[str, list[tuple[str, str]]]:
    blocks: list[tuple[str, str]] = []

    def replace(m: re.Match) -> str:
        idx  = len(blocks)
        lang = m.group(2).strip()
        code = m.group(3)
        blocks.append((lang, code))
        return f'\nHORIZONCODEBLOCK{idx}END\n\n'

    return _CODE_FENCE_RE.sub(replace, md), blocks


def _inject_code_blocks(html: str, blocks: list[tuple[str, str]]) -> str:
    for idx, (lang, code) in enumerate(blocks):
        placeholder = f'HORIZONCODEBLOCK{idx}END'
        escaped     = _html_mod.escape(code.rstrip('\n'))
        lang_attr   = f' class="language-{lang}"' if lang else ''
        block_html  = f'<pre><code{lang_attr}>{escaped}</code></pre>'
        html = re.sub(
            r'<p[^>]*>\s*' + re.escape(placeholder) + r'\s*</p>',
            block_html,
            html,
            flags=re.IGNORECASE,
        )
        html = html.replace(placeholder, block_html)
    return html


def _inject_mermaid(html: str, diagrams: list[str]) -> str:
    for idx, source in enumerate(diagrams):
        placeholder = f'HORIZONMERMAID{idx}END'
        stripped = source.strip()
        if not stripped:
            replacement = ''
        else:
            escaped = _html_mod.escape(stripped)
            replacement = f'<div class="mermaid" data-mermaid-source="{escaped}">{escaped}</div>'
        html = re.sub(
            r'<p[^>]*>\s*' + re.escape(placeholder) + r'\s*</p>',
            replacement,
            html,
            flags=re.IGNORECASE,
        )
        html = html.replace(placeholder, replacement)
    return html


def _extract_html_blocks(md: str) -> tuple[str, list[str]]:
    blocks: list[str] = []
    result_parts: list[str] = []
    pos = 0

    while pos < len(md):
        m = _HTML_BLOCK_OPEN_RE.search(md, pos)
        if m is None:
            result_parts.append(md[pos:])
            break

        tag_name    = m.group(1).lower()
        block_start = m.start()
        result_parts.append(md[pos:block_start])

        if tag_name in _HTML_VOID_ELEMENTS:
            line_end = md.find('\n', block_start)
            line_end = (line_end + 1) if line_end != -1 else len(md)
            idx = len(blocks)
            blocks.append(md[block_start:line_end])
            result_parts.append(f'\nHORIZONHTMLBLOCK{idx}END\n\n')
            pos = line_end
            continue

        open_re    = re.compile(r'<' + re.escape(tag_name) + r'(?=[>\s/])', re.IGNORECASE)
        close_re   = re.compile(r'</' + re.escape(tag_name) + r'\s*>', re.IGNORECASE)
        depth      = 0
        search_pos = block_start
        block_end  = None

        while search_pos < len(md):
            mo = open_re.search(md, search_pos)
            mc = close_re.search(md, search_pos)
            if mo is None and mc is None:
                block_end = len(md)
                break
            elif mc is None or (mo is not None and mo.start() < mc.start()):
                depth += 1
                search_pos = mo.end()
            else:
                if depth <= 1:
                    block_end = mc.end()
                    break
                depth -= 1
                search_pos = mc.end()

        if block_end is None:
            block_end = len(md)

        idx = len(blocks)
        blocks.append(md[block_start:block_end])
        result_parts.append(f'\nHORIZONHTMLBLOCK{idx}END\n\n')
        pos = block_end

    return ''.join(result_parts), blocks


def _inject_html_blocks(html: str, blocks: list[str]) -> str:
    for idx, raw_html in enumerate(blocks):
        placeholder = f'HORIZONHTMLBLOCK{idx}END'
        replaced = re.sub(
            r'<p[^>]*>\s*' + re.escape(placeholder) + r'\s*</p>',
            raw_html,
            html,
            flags=re.IGNORECASE,
        )
        html = replaced if replaced != html else html.replace(placeholder, raw_html)
    return html


def _extract_footnotes(md: str) -> tuple[str, list[tuple[str, str]]]:
    defs: dict[str, str] = {}

    def collect_def(m: re.Match) -> str:
        label = m.group(1)
        raw = m.group(2)
        # Strip continuation indent (4 spaces or tab)
        content = re.sub(r'\n(?:    |\t)', '\n', raw).strip()
        defs[label] = content
        return ''

    md = _FOOTNOTE_DEF_RE.sub(collect_def, md)

    refs: list[tuple[str, str]] = []
    label_to_num: dict[str, int] = {}

    def replace_ref(m: re.Match) -> str:
        label = m.group(1)
        if label not in label_to_num:
            label_to_num[label] = len(refs) + 1
            refs.append((label, defs.get(label, '')))
        return f'HORIZONFNREF{label_to_num[label]}END'

    md = _FOOTNOTE_REF_RE.sub(replace_ref, md)
    return md, refs


def _inject_footnotes(html: str, refs: list[tuple[str, str]]) -> str:
    if not refs:
        return html

    for i, (label, _) in enumerate(refs):
        num = i + 1
        escaped_label = _html_mod.escape(label)
        sup = (
            f'<sup class="footnote-ref">'
            f'<a href="#fn-{escaped_label}" id="fnref-{escaped_label}">{num}</a>'
            f'</sup>'
        )
        html = html.replace(f'HORIZONFNREF{num}END', sup)

    items_html = ''
    for i, (label, content) in enumerate(refs):
        escaped_label = _html_mod.escape(label)
        inner = _blockquote_inner_html([content]) if content else ''
        backref = f'<a href="#fnref-{escaped_label}" class="footnote-backref">&#x21A9;</a>'
        # Insert backref inside the last </p> so it stays inline with the text
        last_p = inner.rfind('</p>')
        if last_p != -1:
            inner = inner[:last_p] + ' ' + backref + inner[last_p:]
        else:
            inner = inner + ' ' + backref
        items_html += f'<li id="fn-{escaped_label}">{inner}</li>'

    section = (
        '<section class="footnotes">'
        '<hr class="footnotes-sep">'
        '<ol class="footnotes-list">' + items_html + '</ol>'
        '</section>'
    )

    if '</body>' in html:
        html = html.replace('</body>', section + '</body>', 1)
    else:
        html += section

    return html


def _markdown_to_html(
    markdown: str,
    image_repo: ImageRepository | None = None,
    note_repo=None,   # NoteRepository | None
    title_to_id: dict[str, int] | None = None,
    id_exists: set[int] | None = None,
    image_cache: dict[int, bytes | None] | None = None,
) -> str:
    # Use pre-computed note maps when provided to avoid hitting the DB on every render
    if title_to_id is not None and id_exists is not None:
        _title_to_id = title_to_id
        _id_exists = id_exists
    else:
        _title_to_id = {}
        _id_exists = set()
        if note_repo is not None:
            for _note in note_repo.list_all():
                _title_to_id[_note.title.lower()] = _note.id
                _id_exists.add(_note.id)

    # image_cache is mutated in-place so the caller accumulates loaded images across renders
    images: dict[int, bytes | None] = image_cache if image_cache is not None else {}

    if image_repo is not None:
        def _extract(m: re.Match) -> str:
            img_id = int(m.group(2))
            if img_id not in images:
                images[img_id] = image_repo.get(img_id)
            return f"HORIZONIMG{img_id}END"

        markdown = _MD_IMG_RE.sub(_extract, markdown)

    markdown, html_blocks = _extract_html_blocks(markdown)
    markdown, inline_tags = _extract_tags(markdown)
    markdown, diagrams = _extract_mermaid(markdown)
    markdown, code_blocks = _extract_code_blocks(markdown)
    markdown, footnotes = _extract_footnotes(markdown)
    markdown, wikilinks = _extract_wikilinks(markdown, _title_to_id, _id_exists)
    markdown, bq_list = _extract_blockquotes(markdown)
    markdown = _add_hard_breaks(markdown)

    doc = QTextDocument()
    doc.setMarkdown(markdown)
    html = doc.toHtml()

    html = _BLOCK_STYLE_RE.sub(r'\1', html)
    html = _inject_blockquotes(html, bq_list)
    html = _inject_code_blocks(html, code_blocks)
    html = _inject_mermaid(html, diagrams)
    html = html.replace('HORIZONLBR ', '<br>').replace('HORIZONLBR', '<br>')
    html = _inject_tags(html, inline_tags)
    html = _inject_wikilinks(html, wikilinks)
    html = _inject_footnotes(html, footnotes)

    if images:
        def _inject(m: re.Match) -> str:
            data = images.get(int(m.group(1)))
            if not data:
                return ""
            b64 = base64.b64encode(data).decode()
            return f'<img src="data:image/png;base64,{b64}" style="max-width:100%;">'

        html = _HTML_PH_RE.sub(_inject, html)

    html = _inject_html_blocks(html, html_blocks)

    return html


class MarkdownBridge(QObject):
    html_changed           = Signal(str)
    image_clicked          = Signal(str)
    link_clicked           = Signal(str)
    mermaid_open_requested = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_html: str = ""

    def push_html(self, html: str) -> None:
        self._current_html = html
        self.html_changed.emit(html)

    @Slot(result=str)
    def get_current_html(self) -> str:
        return self._current_html

    @Slot(str)
    def open_image(self, data_uri: str) -> None:
        self.image_clicked.emit(data_uri)

    @Slot(str)
    def open_link(self, url: str) -> None:
        self.link_clicked.emit(url)

    @Slot(str)
    def open_mermaid(self, source: str) -> None:
        self.mermaid_open_requested.emit(source)


class MarkdownEditor(QPlainTextEdit):
    def __init__(self, image_repo: ImageRepository, parent=None) -> None:
        super().__init__(parent)
        self._image_repo = image_repo

    def insertFromMimeData(self, source) -> None:
        if source.hasImage():
            image = source.imageData()
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.OpenModeFlag.WriteOnly)
            image.save(buf, "PNG")
            buf.close()
            image_id = self._image_repo.create(bytes(ba))
            self.insertPlainText(f"![](horizon-image://{image_id})")
        else:
            super().insertFromMimeData(source)


_HEADING_PREFIX_RE = re.compile(r'^#{1,6} +')

_TOOLBAR_ICON_SIZE = QSize(16, 16)
_TOOLBAR_BUTTON_SIZE = QSize(26, 26)


class MarkdownToolbar(QWidget):
    """Vertical column of icon buttons that insert/wrap markdown syntax in the given editor."""

    def __init__(self, editor: QPlainTextEdit, parent=None) -> None:
        super().__init__(parent)
        self._editor = editor

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        def add_button(icon_name: str, tooltip: str, handler) -> QToolButton:
            btn = QToolButton()
            btn.setIcon(_theme.make_icon(f":/icons/{icon_name}.svg", _TOOLBAR_ICON_SIZE))
            btn.setIconSize(_TOOLBAR_ICON_SIZE)
            btn.setFixedSize(_TOOLBAR_BUTTON_SIZE)
            btn.setToolTip(tooltip)
            btn.clicked.connect(handler)
            layout.addWidget(btn)
            return btn

        for level in (1, 2, 3, 4):
            add_button(f"heading{level}_cyan", f"Titre {level}", lambda _checked=False, lvl=level: self._apply_heading(lvl))

        add_button("bullet_list_cyan", "Liste à puce", self._apply_bullet_list)

        add_button("bold_cyan", "Gras", lambda: self._wrap_selection("**", "**"))
        add_button("italic_cyan", "Italique", lambda: self._wrap_selection("*", "*"))
        add_button("underline_cyan", "Souligné", lambda: self._wrap_selection("_", "_", underline=True))
        add_button("strikethrough_cyan", "Barré", lambda: self._wrap_selection("~~", "~~"))

        add_button("table_cyan", "Insérer un tableau", self._insert_table)
        add_button("link_external_cyan", "Insérer un lien externe", self._insert_external_link)
        add_button("link_internal_cyan", "Insérer un lien vers une note interne", self._insert_internal_link)
        add_button("mermaid_cyan", "Insérer un diagramme Mermaid", self._insert_mermaid)
        add_button("code_cyan", "Insérer un bloc de code", self._insert_code_block)

        layout.addStretch()
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

    def _apply_heading(self, level: int) -> None:
        cursor = self._editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
        cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock, QTextCursor.MoveMode.KeepAnchor)
        text = cursor.selectedText()
        text = _HEADING_PREFIX_RE.sub('', text)
        cursor.beginEditBlock()
        cursor.insertText(f"{'#' * level} {text}")
        cursor.endEditBlock()
        self._editor.setTextCursor(cursor)

    def _apply_bullet_list(self) -> None:
        cursor = self._editor.textCursor()
        doc = self._editor.document()
        start = doc.findBlock(cursor.selectionStart())
        end = doc.findBlock(cursor.selectionEnd())

        blocks = []
        block = start
        while True:
            blocks.append(block)
            if block.blockNumber() >= end.blockNumber():
                break
            block = block.next()

        non_empty = [b for b in blocks if b.text().strip()]
        already_bulleted = non_empty and all(b.text().startswith("- ") for b in non_empty)

        cursor.beginEditBlock()
        for block in blocks:
            if not block.text().strip():
                continue
            block_cursor = QTextCursor(block)
            block_cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock)
            if already_bulleted:
                block_cursor.movePosition(QTextCursor.MoveOperation.Right, QTextCursor.MoveMode.KeepAnchor, 2)
                block_cursor.removeSelectedText()
            else:
                block_cursor.insertText("- ")
        cursor.endEditBlock()

    def _wrap_selection(self, prefix: str, suffix: str, underline: bool = False) -> None:
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()
        if cursor.hasSelection():
            text = cursor.selectedText()
            start = cursor.selectionStart()
            cursor.insertText(f"{prefix}{text}{suffix}")
            if underline and cursor.atBlockEnd():
                cursor.insertText(" ")
            cursor.setPosition(start + len(prefix))
            cursor.setPosition(start + len(prefix) + len(text), QTextCursor.MoveMode.KeepAnchor)
        else:
            pos = cursor.position()
            cursor.insertText(f"{prefix}{suffix}")
            if underline and cursor.atBlockEnd():
                cursor.insertText(" ")
            cursor.setPosition(pos + len(prefix))
        cursor.endEditBlock()
        self._editor.setTextCursor(cursor)

    def _insert_block(self, text: str) -> None:
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()
        needs_leading_nl = not cursor.atBlockStart()
        cursor.insertText(("\n" if needs_leading_nl else "") + text + "\n")
        cursor.endEditBlock()
        self._editor.setTextCursor(cursor)

    def _insert_table(self) -> None:
        self._insert_block(
            "| Colonne 1 | Colonne 2 | Colonne 3 |\n"
            "| --- | --- | --- |\n"
            "|  |  |  |\n"
            "|  |  |  |"
        )

    def _insert_external_link(self) -> None:
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()
        cursor.insertText("[texte](https://exemple.com)")
        cursor.endEditBlock()
        self._editor.setTextCursor(cursor)

    def _insert_internal_link(self) -> None:
        cursor = self._editor.textCursor()
        cursor.beginEditBlock()
        cursor.insertText("[[id|texte]]")
        cursor.endEditBlock()
        self._editor.setTextCursor(cursor)

    def _insert_mermaid(self) -> None:
        self._insert_block(
            "```mermaid\n"
            "flowchart TD\n"
            "    A[Début] --> B{Condition}\n"
            "    B -->|Oui| C[Fin]\n"
            "    B -->|Non| A\n"
            "```"
        )

    def _insert_code_block(self) -> None:
        self._insert_block(
            "```python\n"
            "print(\"Hello world\")\n"
            "```"
        )
