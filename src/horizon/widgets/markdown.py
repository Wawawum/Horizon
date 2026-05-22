import base64
import html as _html_mod
import re
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QObject, QSize, Signal, Slot, QUrl
from PySide6.QtGui import QIcon, QPixmap, QTextDocument
from PySide6.QtWidgets import QPlainTextEdit

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
  .mermaid {{ margin-bottom: 0.8em; overflow-x: auto; text-align: center; }}
  .mermaid svg {{ max-width: 100%; height: auto; }}
  .tag {{ display: inline-block; background-color: {t.accent_color}22; border: 1px solid {t.accent_color}; border-radius: 4px; padding: 1px 7px; color: {t.accent_color}; font-size: 0.85em; font-weight: 500; white-space: nowrap; }}
  a.note-link {{ color: {t.accent_color}; text-decoration: none; border-bottom: 1px dashed {t.accent_color}; }}
  a.note-link:hover {{ border-bottom-style: solid; }}
  .note-link-broken {{ color: {t.preview_text}; opacity: 0.45; text-decoration: line-through; cursor: default; font-style: italic; }}
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
    var doc = new DOMParser().parseFromString(html, 'text/html');
    document.getElementById('content').innerHTML = doc.body ? doc.body.innerHTML : html;
    styleTableHeaders();
    attachImageHandlers();
    attachLinkHandlers();
    document.querySelectorAll('#content pre code').forEach(function(el) {{
      hljs.highlightElement(el);
    }});
    var nodes = document.getElementById('content').querySelectorAll('.mermaid');
    if (nodes.length > 0) {{
      mermaid.run({{ nodes: nodes }}).catch(function(err) {{
        console.warn('Mermaid render error:', err);
      }});
    }}
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
            replacement = f'<div class="mermaid">{escaped}</div>'
        html = re.sub(
            r'<p[^>]*>\s*' + re.escape(placeholder) + r'\s*</p>',
            replacement,
            html,
            flags=re.IGNORECASE,
        )
        html = html.replace(placeholder, replacement)
    return html


def _markdown_to_html(
    markdown: str,
    image_repo: ImageRepository | None = None,
    note_repo=None,   # NoteRepository | None
) -> str:
    images: dict[int, bytes | None] = {}

    _title_to_id: dict[str, int] = {}
    _id_exists: set[int] = set()
    if note_repo is not None:
        for _note in note_repo.list_all():
            _title_to_id[_note.title.lower()] = _note.id
            _id_exists.add(_note.id)

    if image_repo is not None:
        def _extract(m: re.Match) -> str:
            img_id = int(m.group(2))
            if img_id not in images:
                images[img_id] = image_repo.get(img_id)
            return f"HORIZONIMG{img_id}END"

        markdown = _MD_IMG_RE.sub(_extract, markdown)

    markdown, inline_tags = _extract_tags(markdown)
    markdown, diagrams = _extract_mermaid(markdown)
    markdown, code_blocks = _extract_code_blocks(markdown)
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

    if images:
        def _inject(m: re.Match) -> str:
            data = images.get(int(m.group(1)))
            if not data:
                return ""
            b64 = base64.b64encode(data).decode()
            return f'<img src="data:image/png;base64,{b64}" style="max-width:100%;">'

        html = _HTML_PH_RE.sub(_inject, html)

    return html


class MarkdownBridge(QObject):
    html_changed  = Signal(str)
    image_clicked = Signal(str)
    link_clicked  = Signal(str)

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
