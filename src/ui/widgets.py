"""Jarvis 데스크톱 UI 에서 재사용하는 위젯 모음입니다.

이 모듈은 마크다운 렌더러, 자동 높이 입력창, 정규식 테스트 패널,
로컬 파일 검색 결과 위젯, 채팅 말풍선을 제공합니다.
"""

import datetime
import os
import re

import markdown2
from pygments.formatters import HtmlFormatter
from PyQt5.QtCore import QObject, QTimer, QRect, QSize, Qt, pyqtSignal, QRunnable, QThreadPool
from PyQt5.QtGui import QColor, QFont
from PyQt5.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStyledItemDelegate,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QStyle,
)

from services.file_action_service import (
    copy_path_to_desktop,
    move_path_to_recycle_bin,
    open_parent_folder,
    open_path,
)
from ui.styles import (
    ASSISTANT_MESSAGE_STYLE,
    CONTEXT_MENU_STYLE,
    FILE_RESULTS_HEADER_STYLE,
    FILE_RESULTS_LIST_STYLE,
    PASTED_BADGE_STYLE,
    REGEX_PANEL_LABEL_STYLE,
    REGEX_PANEL_TITLE_STYLE,
    REGEX_PATTERN_INPUT_STYLE,
    REGEX_RESULT_FAILURE_STYLE,
    REGEX_RESULT_IDLE_STYLE,
    REGEX_RESULT_SUCCESS_STYLE,
    REGEX_RESULT_WARNING_STYLE,
    REGEX_TEST_INPUT_STYLE,
    TEXT_EDIT_STYLE,
    TIMESTAMP_LEFT_STYLE,
    TIMESTAMP_RIGHT_STYLE,
    USER_MESSAGE_STYLE,
)


class MarkdownRenderer:
    """어시스턴트 응답용 마크다운을 HTML 로 렌더링합니다."""

    formatter = HtmlFormatter(style="monokai")

    @staticmethod
    def render(text):
        """마크다운 텍스트를 코드 복사 링크가 포함된 HTML 로 변환합니다."""
        import re as common_re
        # 아직 마크다운 링크 형태가 아닌 순수 http URL을 마크다운 문법으로 감싸 클릭 가능하게 만듭니다.
        text = common_re.sub(r'(?<!\]\()(https?://[^\s\)]+)', r'[\1](\1)', text)
        html = markdown2.markdown(text, extras=["fenced-code-blocks", "target-blank-links"])
        style = MarkdownRenderer.formatter.get_style_defs(".codehilite")
        full_style = f"""
        <style>
        {style}
        body {{ font-family: 'Segoe UI', sans-serif; font-size: 14px; line-height: 1.6; }}
        p {{ margin: 4px 0; }}
        .code-wrapper {{ margin: 6px 0; }}
        .copy-link {{ float: right; font-size: 11px; color: #888;
                      text-decoration: none; padding: 1px 6px;
                      background: #3a3c40; border-radius: 4px; }}
        .copy-link:hover {{ color: #5865F2; background: #2B2D31; }}
        .codehilite {{ border-radius: 8px; padding: 10px; overflow-x: auto;
                       margin: 0; clear: both; }}
        .codehilite pre {{ margin: 0; }}
        code {{ font-family: 'Consolas', monospace; font-size: 13px; }}
        </style>
        """
        import re as html_re
        from html.parser import HTMLParser
        from urllib.parse import quote

        class _TextExtractor(HTMLParser):
            """렌더링된 HTML 조각에서 순수 텍스트만 추출합니다."""

            def __init__(self):
                """텍스트 수집 버퍼를 초기화합니다."""
                super().__init__()
                self.parts = []

            def handle_data(self, data):
                """HTML 의 텍스트 노드를 수집합니다."""
                self.parts.append(data)

            def get_text(self):
                """수집한 텍스트를 하나로 합쳐 반환합니다."""
                return "".join(self.parts)

        def wrap_code(match):
            """코드 블록 위에 복사 링크를 붙여 감쌉니다."""
            raw_html = match.group(0)
            extractor = _TextExtractor()
            extractor.feed(raw_html)
            code_text = extractor.get_text().strip()
            encoded = quote(code_text, safe="")
            button = f'<a class="copy-link" href="copy://{encoded}">복사</a>'
            return f'<div class="code-wrapper">{button}{raw_html}</div>'

        html = html_re.sub(r'<div class="codehilite">.*?</div>', wrap_code, html, flags=html_re.DOTALL)
        return f"{full_style}{html}"


class MarkdownRenderSignals(QObject):
    """QRunnable에서 결과를 전달받기 위한 시그널 전용 컨테이너입니다."""
    finished = pyqtSignal(str)


class MarkdownRenderWorker(QRunnable):
    """마크다운 렌더링을 백그라운드 스레드풀에서 수행하는 워커입니다."""

    def __init__(self, text):
        super().__init__()
        self.text = text
        self.signals = MarkdownRenderSignals()

    def run(self):
        """실제 렌더링을 실행하고 결과를 시그널로 보냅니다."""
        try:
            rendered_html = MarkdownRenderer.render(self.text)
            self.signals.finished.emit(rendered_html)
        except Exception:
            # 실패 시 일반 텍스트라도 반환
            self.signals.finished.emit(self.text)


class AutoExpandingTextEdit(QTextEdit):
    """입력 내용에 따라 높이가 늘어나고 코드 붙여넣기를 감싸주는 입력창입니다."""

    submit = pyqtSignal()

    MIN_H = 46
    MAX_H = 200

    _CODE_PATTERNS = [
        r"^\s*(public|private|protected|class|import|package)\s",
        r"^\s*(def |function |var |let |const |<\?php)",
        r"at\s+[\w\.\$]+\([\w\.]+:\d+\)",
        r"ORA-\d{4,5}",
        r"Exception in thread",
        r"^\s*(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER)\s",
        r"[{};]\s*$",
    ]
    _CODE_RE = [re.compile(pattern, re.MULTILINE | re.IGNORECASE) for pattern in _CODE_PATTERNS]

    def __init__(self):
        """입력창 UI 와 자동 높이 조절 동작을 초기화합니다."""
        super().__init__()
        self.setPlaceholderText("메시지를 입력하세요. Enter 전송 / Shift+Enter 줄바꿈")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setMinimumHeight(self.MIN_H)
        self.setMaximumHeight(self.MIN_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.document().contentsChanged.connect(self._adjust_height)
        self.setStyleSheet(TEXT_EDIT_STYLE)

        self._badge = QLabel("붙여넣음", self)
        self._badge.setStyleSheet(PASTED_BADGE_STYLE)
        self._badge.hide()
        self._badge_timer = QTimer(self)
        self._badge_timer.setSingleShot(True)
        self._badge_timer.timeout.connect(self._badge.hide)

    def _detect_lang(self, text):
        """붙여넣은 코드의 언어를 간단히 추정합니다."""
        text_lower = text.lower()
        if any(keyword in text_lower for keyword in ["select ", "insert ", "update ", "delete ", "from ", "where ", "ora-"]):
            return "sql"
        if any(keyword in text_lower for keyword in ["public class", "import java", "spring", "servlet", "@controller", "exception in thread", "at org.", "at com."]):
            return "java"
        if any(keyword in text_lower for keyword in ["function(", "$(", "jquery", "var ", "const ", "let ", "console.log"]):
            return "javascript"
        if any(keyword in text_lower for keyword in ["<html", "<div", "<jsp:", "<%", "%>"]):
            return "html"
        if any(keyword in text_lower for keyword in ["def ", "import ", "class ", "print(", "python"]):
            return "python"
        return "java"

    def _is_code(self, text):
        """붙여넣은 내용이 코드나 스택트레이스인지 판단합니다."""
        if text.count("\n") < 2:
            return False
        return any(pattern.search(text) for pattern in self._CODE_RE)

    def _show_badge(self):
        """입력창 오른쪽 아래에 붙여넣기 배지를 잠깐 보여줍니다."""
        self._badge.adjustSize()
        x_pos = self.width() - self._badge.width() - 10
        y_pos = self.height() - self._badge.height() - 8
        self._badge.move(x_pos, y_pos)
        self._badge.raise_()
        self._badge.show()
        self._badge_timer.start(2000)

    def resizeEvent(self, event):
        """리사이즈될 때 배지 위치를 다시 맞춥니다."""
        super().resizeEvent(event)
        if self._badge.isVisible():
            x_pos = self.width() - self._badge.width() - 10
            y_pos = self.height() - self._badge.height() - 8
            self._badge.move(x_pos, y_pos)

    def insertFromMimeData(self, source):
        """코드로 보이는 붙여넣기 내용은 마크다운 코드 블록으로 감쌉니다."""
        if source.hasText():
            pasted = source.text()
            if self._is_code(pasted):
                lang = self._detect_lang(pasted)
                current = self.toPlainText().strip()
                if not current:
                    self.setPlainText(f"```{lang}\n{pasted.strip()}\n```")
                else:
                    cursor = self.textCursor()
                    cursor.movePosition(cursor.End)
                    cursor.insertText(f"\n```{lang}\n{pasted.strip()}\n```")
                self._show_badge()
                return
        super().insertFromMimeData(source)

    def _adjust_height(self):
        """문서 높이에 맞춰 입력창 높이를 제한 범위 안에서 조정합니다."""
        document_height = int(self.document().size().height()) + 20
        new_height = max(self.MIN_H, min(document_height, self.MAX_H))
        self.setMinimumHeight(new_height)
        self.setMaximumHeight(new_height)

    def keyPressEvent(self, event):
        """Enter 는 전송, Shift+Enter 는 줄바꿈으로 처리합니다."""
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier:
                super().keyPressEvent(event)
            else:
                self.submit.emit()
        else:
            super().keyPressEvent(event)

    def text(self):
        """현재 입력된 순수 텍스트를 반환합니다."""
        return self.toPlainText()

    def clear(self):
        """입력창을 비우고 최소 높이로 되돌립니다."""
        super().clear()
        self.setMinimumHeight(self.MIN_H)
        self.setMaximumHeight(self.MIN_H)


class AutoTextBrowser(QTextBrowser):
    """어시스턴트 응답 길이에 맞춰 높이를 자동 조절하는 읽기 전용 브라우저입니다."""

    def __init__(self):
        """브라우저와 복사 링크 처리 동작을 초기화합니다."""
        super().__init__()
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().contentsChanged.connect(self._update_height)
        self.anchorClicked.connect(self._handle_anchor)
        self.setOpenLinks(False)

    def _handle_anchor(self, url):
        """copy:// 링크는 클립보드에 복사하고, http/https 일반 링크는 외부 웹 브라우저로 엽니다."""
        if url.scheme() == "copy":
            QApplication.clipboard().setText(url.path().lstrip("/"))
        elif url.scheme() in ("http", "https"):
            from PyQt5.QtGui import QDesktopServices
            QDesktopServices.openUrl(url)

    def _update_height(self):
        """렌더링된 문서 높이에 맞게 위젯 높이를 갱신합니다."""
        self.setFixedHeight(self._calc_height())

    def _calc_height(self):
        """현재 문서 높이를 계산하고 최대 높이를 제한합니다."""
        self.document().setTextWidth(self.viewport().width() or 640)
        height = int(self.document().size().height()) + 28
        return min(height, 800)

    def resizeEvent(self, event):
        """가로폭이 바뀌면 높이도 다시 계산합니다."""
        super().resizeEvent(event)
        self._update_height()


class RegexTestPanel(QWidget):
    """생성된 정규식을 바로 시험해볼 수 있는 보조 패널입니다."""

    def __init__(self, pattern=""):
        """패턴 입력창과 테스트 입력창을 포함한 패널을 만듭니다."""
        super().__init__()
        self.setMaximumWidth(700)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 6, 10, 6)
        outer.setSpacing(6)

        header = QLabel("정규식 테스트")
        header.setStyleSheet(REGEX_PANEL_TITLE_STYLE)
        outer.addWidget(header)

        pattern_row = QHBoxLayout()
        pattern_label = QLabel("패턴")
        pattern_label.setStyleSheet(REGEX_PANEL_LABEL_STYLE)
        pattern_label.setFixedWidth(50)
        self.pattern_input = QLineEdit(pattern)
        self.pattern_input.setPlaceholderText("정규식 패턴을 입력하세요...")
        self.pattern_input.setStyleSheet(REGEX_PATTERN_INPUT_STYLE)
        self.pattern_input.textChanged.connect(self._test)
        pattern_row.addWidget(pattern_label)
        pattern_row.addWidget(self.pattern_input)
        outer.addLayout(pattern_row)

        sample_row = QHBoxLayout()
        sample_label = QLabel("샘플")
        sample_label.setStyleSheet(REGEX_PANEL_LABEL_STYLE)
        sample_label.setFixedWidth(50)
        self.test_input = QLineEdit()
        self.test_input.setPlaceholderText("테스트할 문자열을 입력하세요...")
        self.test_input.setStyleSheet(REGEX_TEST_INPUT_STYLE)
        self.test_input.textChanged.connect(self._test)
        sample_row.addWidget(sample_label)
        sample_row.addWidget(self.test_input)
        outer.addLayout(sample_row)

        self.result_label = QLabel("결과: 패턴과 샘플 문자열을 입력하세요.")
        self.result_label.setStyleSheet(REGEX_RESULT_IDLE_STYLE)
        self.result_label.setWordWrap(True)
        outer.addWidget(self.result_label)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def _test(self):
        """현재 패턴으로 샘플 문자열을 검사합니다."""
        pattern = self.pattern_input.text().strip()
        test_str = self.test_input.text()
        if not pattern or not test_str:
            self.result_label.setText("결과: 패턴과 샘플 문자열을 입력하세요.")
            self.result_label.setStyleSheet(REGEX_RESULT_IDLE_STYLE)
            return

        try:
            matches = list(re.finditer(pattern, test_str))
            if matches:
                groups_info = ""
                for index, match in enumerate(matches[:5], 1):
                    groups = match.groups()
                    groups_info += f"  매칭 {index}: '{match.group()}'"
                    if groups:
                        groups_info += f"  그룹: {groups}"
                    groups_info += "\n"
                self.result_label.setText(f"총 {len(matches)}건 매칭\n{groups_info}")
                self.result_label.setStyleSheet(REGEX_RESULT_SUCCESS_STYLE)
            else:
                self.result_label.setText("매칭 결과가 없습니다.")
                self.result_label.setStyleSheet(REGEX_RESULT_FAILURE_STYLE)
        except re.error as error:
            self.result_label.setText(f"정규식 오류: {error}")
            self.result_label.setStyleSheet(REGEX_RESULT_WARNING_STYLE)

    def set_pattern(self, pattern):
        """패널의 현재 정규식 패턴을 교체합니다."""
        self.pattern_input.setText(pattern)


class FileSearchResultItemDelegate(QStyledItemDelegate):
    """로컬 파일 검색 결과를 2줄 레이아웃으로 그려주는 delegate 입니다."""

    ROW_HEIGHT = 58

    def paint(self, painter, option, index):
        """아이콘, 파일명, 경로를 포함한 검색 결과 행을 그립니다."""
        painter.save()
        if option.state & QStyle.State_Selected:
            painter.fillRect(option.rect, QColor("#5865F2"))
        elif option.state & QStyle.State_MouseOver:
            painter.fillRect(option.rect, QColor("#383A40"))
        else:
            painter.fillRect(option.rect, QColor("#2B2D31"))

        painter.setPen(QColor("#3a3c40"))
        painter.drawLine(option.rect.left(), option.rect.bottom(), option.rect.right(), option.rect.bottom())

        full_path = index.data(Qt.UserRole)
        number = index.data(Qt.UserRole + 1)
        icon = index.data(Qt.UserRole + 2)
        name = index.data(Qt.UserRole + 3)

        x_pos = option.rect.left() + 12
        y_pos = option.rect.top()
        width = option.rect.width() - 24

        is_selected = bool(option.state & QStyle.State_Selected)
        name_color = QColor("#FFFFFF") if is_selected else QColor("#DBDEE1")
        path_color = QColor("#C0C8FF") if is_selected else QColor("#72767D")

        painter.setPen(QColor("#888") if not is_selected else QColor("#C0C8FF"))
        painter.setFont(QFont("Segoe UI", 10))
        painter.drawText(QRect(x_pos, y_pos, 28, self.ROW_HEIGHT), Qt.AlignVCenter | Qt.AlignRight, f"{number}.")

        painter.setFont(QFont("Segoe UI Emoji", 14))
        painter.setPen(name_color)
        painter.drawText(QRect(x_pos + 32, y_pos, 24, self.ROW_HEIGHT), Qt.AlignVCenter | Qt.AlignHCenter, icon)

        text_x = x_pos + 64
        text_width = width - 64

        painter.setFont(QFont("Segoe UI", 11, QFont.Bold))
        painter.setPen(name_color)
        name_rect = QRect(text_x, y_pos + 6, text_width, 22)
        painter.drawText(name_rect, Qt.AlignLeft | Qt.AlignVCenter, painter.fontMetrics().elidedText(name, Qt.ElideMiddle, text_width))

        painter.setFont(QFont("Segoe UI", 9))
        painter.setPen(path_color)
        path_rect = QRect(text_x, y_pos + 30, text_width, 18)
        painter.drawText(path_rect, Qt.AlignLeft | Qt.AlignVCenter, painter.fontMetrics().elidedText(full_path, Qt.ElideMiddle, text_width))
        painter.restore()

    def sizeHint(self, option, index):
        """각 검색 결과 행의 고정 높이를 반환합니다."""
        return QSize(0, self.ROW_HEIGHT)


class FileSearchResultsBubble(QWidget):
    """로컬 파일 검색 결과를 리스트 형태로 보여주는 말풍선 위젯입니다."""

    def __init__(self, items):
        """검색 결과 헤더, 리스트, 시각 정보를 렌더링합니다."""
        super().__init__()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 4, 10, 4)
        outer.setSpacing(4)

        header = QLabel(f"PC 파일 검색 결과 ({len(items)}개)  더블클릭: 열기 / 우클릭: 메뉴")
        header.setStyleSheet(FILE_RESULTS_HEADER_STYLE)
        outer.addWidget(header)

        self.list_widget = QListWidget()
        self.list_widget.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_widget.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_widget.setMouseTracking(True)
        self.list_widget.setItemDelegate(FileSearchResultItemDelegate(self.list_widget))
        self.list_widget.setStyleSheet(FILE_RESULTS_LIST_STYLE)

        for index, (icon, name, _folder, full_path) in enumerate(items, 1):
            item = QListWidgetItem()
            item.setData(Qt.UserRole, full_path)
            item.setData(Qt.UserRole + 1, index)
            item.setData(Qt.UserRole + 2, icon)
            item.setData(Qt.UserRole + 3, name)
            self.list_widget.addItem(item)

        self.list_widget.setFixedHeight(min(len(items) * FileSearchResultItemDelegate.ROW_HEIGHT + 2, 420))
        self.list_widget.setMaximumWidth(700)
        self.list_widget.itemDoubleClicked.connect(self._open_item)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        outer.addWidget(self.list_widget)

        time_label = QLabel(datetime.datetime.now().strftime("%H:%M"))
        time_label.setStyleSheet(TIMESTAMP_LEFT_STYLE)
        outer.addWidget(time_label)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def _open_item(self, item):
        """더블클릭한 검색 결과 파일을 엽니다."""
        path = item.data(Qt.UserRole)
        try:
            open_path(path)
        except Exception as error:
            print("파일 열기에 실패했습니다:", error)

    def _show_context_menu(self, pos):
        """선택한 검색 결과 항목의 컨텍스트 메뉴를 엽니다."""
        item = self.list_widget.itemAt(pos)
        if not item:
            return
        path = item.data(Qt.UserRole)

        menu = QMenu(self)
        menu.setStyleSheet(CONTEXT_MENU_STYLE)

        action_open = menu.addAction("파일 열기")
        action_open_folder = menu.addAction("폴더 열기")
        action_copy_path = menu.addAction("경로 복사")
        menu.addSeparator()
        action_copy_desktop = menu.addAction("바탕화면에 복사")
        menu.addSeparator()
        action_delete = menu.addAction("삭제 (휴지통)")

        chosen_action = menu.exec_(self.list_widget.mapToGlobal(pos))

        if chosen_action == action_open:
            self._do_open(path)
        elif chosen_action == action_open_folder:
            self._do_open_folder(path)
        elif chosen_action == action_copy_path:
            QApplication.clipboard().setText(path)
        elif chosen_action == action_copy_desktop:
            self._do_copy_to_desktop(path)
        elif chosen_action == action_delete:
            self._do_delete(path)

    def _do_open(self, path):
        """선택한 파일 또는 폴더를 엽니다."""
        try:
            open_path(path)
        except Exception as error:
            QMessageBox.warning(self, "오류", str(error))

    def _do_open_folder(self, path):
        """선택한 경로의 상위 폴더를 엽니다."""
        try:
            open_parent_folder(path)
        except Exception as error:
            QMessageBox.warning(self, "오류", str(error))

    def _do_copy_to_desktop(self, path):
        """선택한 파일이나 폴더를 바탕화면으로 복사합니다."""
        try:
            destination = copy_path_to_desktop(path)
            QMessageBox.information(self, "복사 완료", f"바탕화면에 복사했습니다.\n{destination}")
        except Exception as error:
            QMessageBox.warning(self, "복사 실패", str(error))

    def _do_delete(self, path):
        """확인 후 선택한 항목을 휴지통으로 보냅니다."""
        name = os.path.basename(path)
        reply = QMessageBox.question(
            self,
            "삭제 확인",
            f"'{name}' 파일을 휴지통으로 이동하시겠습니까?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        try:
            move_path_to_recycle_bin(path)
            QMessageBox.information(self, "삭제 완료", f"휴지통으로 이동했습니다.\n{path}")
        except Exception as error:
            QMessageBox.warning(self, "삭제 실패", str(error))


class ChatMessageBubble(QWidget):
    """사용자 또는 어시스턴트 메시지를 보여주는 단일 말풍선입니다."""

    def __init__(self, text, is_user):
        """좌우 정렬 방식에 맞는 채팅 말풍선을 생성합니다."""
        super().__init__()
        self.is_user = is_user
        self.text = text
        self._is_rendering = False
        self._pending_text = None
        
        time_str = datetime.datetime.now().strftime("%H:%M")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 4, 10, 4)
        outer.setSpacing(2)
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)

        if is_user:
            label = QLabel(text)
            label.setWordWrap(True)
            # 사용자 말풍선이 지나치게 세로로 길어지는 것을 방지하기 위해
            # 최소 폭을 확보하고(너무 좁게 줄바꿈되지 않게), 어시스턴트 말풍선과 비슷한 폭으로 제한합니다.
            label.setMinimumWidth(320)
            label.setMaximumWidth(680)
            label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setStyleSheet(USER_MESSAGE_STYLE)
            row.addWidget(label, 0, Qt.AlignRight)
            outer.addLayout(row)

            time_label = QLabel(time_str)
            time_label.setStyleSheet(TIMESTAMP_RIGHT_STYLE)
            time_label.setAlignment(Qt.AlignRight)
            outer.addWidget(time_label)
        else:
            self.browser = AutoTextBrowser()
            # 초기 렌더링은 동기로 진행하거나 빈 상태로 시작
            self.browser.setHtml(MarkdownRenderer.render(text))
            self.browser.setMaximumWidth(680)
            self.browser.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            self.browser.setOpenExternalLinks(True)
            self.browser.setStyleSheet(ASSISTANT_MESSAGE_STYLE)
            row.addWidget(self.browser)
            row.addStretch()
            outer.addLayout(row)

            time_label = QLabel(time_str)
            time_label.setStyleSheet(TIMESTAMP_LEFT_STYLE)
            time_label.setAlignment(Qt.AlignLeft)
            outer.addWidget(time_label)

        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Minimum)

    def update_text(self, text):
        """스트리밍 중인 어시스턴트 말풍선 내용을 비동기로 갱신합니다."""
        if not hasattr(self, "browser"):
            return

        if self._is_rendering:
            # 이미 렌더링 중이면 대기열에 저장
            self._pending_text = text
            return

        self._start_async_render(text)

    def _start_async_render(self, text):
        """글로벌 스레드풀을 통해 비동기 렌더링 작업을 예약합니다."""
        self._is_rendering = True
        self.text = text

        worker = MarkdownRenderWorker(text)
        worker.signals.finished.connect(self._on_render_finished)
        QThreadPool.globalInstance().start(worker)

    def _on_render_finished(self, rendered_html):
        """렌더링이 완료되면 UI를 갱신하고 대기 중인 작업이 있는지 확인합니다."""
        if hasattr(self, "browser"):
            self.browser.setHtml(rendered_html)
        
        self._is_rendering = False
        
        # 대기 중인 텍스트가 있으면 다시 렌더링 시작
        if self._pending_text is not None:
            next_text = self._pending_text
            self._pending_text = None
            self._start_async_render(next_text)
